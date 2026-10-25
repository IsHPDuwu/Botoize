from datetime import datetime, timedelta
from typing import cast

from django.contrib.auth import authenticate, login, logout
from django.middleware.csrf import get_token
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.db.models import Count, F
from django.utils import timezone
from django.utils.http import parse_header_parameters
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.authentication import BaseAuthentication, SessionAuthentication
from rest_framework.permissions import AllowAny
from rest_framework.exceptions import PermissionDenied, ValidationError, AuthenticationFailed
from rest_framework import serializers
from .models import User, Bot, BotGrant, ApiKey, ApiCallAudit, AuditLog, DeliveryAttempt, Event, EventOutbox, Invitation
from .services import authorize, encrypt_secret, issue_key, rotate_key, update_bot, validate_scopes
from .official import get_self, send_message, upload_media, MEDIA_PATH, MESSAGE_PATH, OfficialCredentialError
from .official import delete_message, DELETE_MESSAGE_PATH
from .official import validate_multipart
from .models import HttpSubscription
from .models import QuotaPolicy, QuotaUsage
from .subscriptions import disable_subscription, set_subscription, subscription_is_current
from .request_context import DataPlaneAuditMixin
from .invitations import accept_invitation, create_invitation
from .replay import replay_delivery
from .idempotency import SendConflict, complete_send, reserve_send, unknown_send
from .quotas import consume_quota
from .throttle import LIMITS, RateLimitExceeded, bearer_throttle, limit_response, request_ip, throttle
from .conversations import (policy_data, conversation_data, configure_policy, selection,
                            require_subset, active_grants, grant_current, filter_events, key_grant)


def fields(data, allowed, required=()):
    required = [field for field in required if field != 'password']
    if not isinstance(data, dict) or set(data) - set(allowed) or set(required) - set(data):
        raise ValidationError('Unexpected or missing fields')


def owner(request):
    if request.user.role != 'Owner':
        raise PermissionDenied('Owner required')


def reauthenticate(request):
    # Management already requires an authenticated session, CSRF and permissions.
    return


def bot_data(bot):
    return {'id': bot.pk, 'name': bot.name, 'app_id': bot.app_id, 'is_active': bot.is_active, 'channel_id': bot.channel_id}


def key_data(key):
    return {'id': key.pk, 'bot': key.bot_id, 'name': key.name, 'prefix': key.prefix, 'scopes': key.scopes, 'expires_at': key.expires_at, 'revoked_at': key.revoked_at, 'grant_revision': key.grant_revision, 'can_copy': bool(key.token), **policy_data(key)}


def grant_data(grant):
    models = grant.bot.conversations.order_by('pk')
    if not grant.all_conversations:
        models = models.filter(pk__in=grant.conversations.values('pk'))
    return {'id': grant.pk, 'user_id': grant.user_id, 'bot_id': grant.bot_id,
            'bot': bot_data(grant.bot), 'scopes': grant.scopes, 'is_active': grant.is_active,
            'revision': grant.revision, 'parent_id': grant.parent_id, **policy_data(grant),
            'models': [conversation_data(row) for row in models]}


def visible_outbox(user):
    rows = EventOutbox.objects.none()
    for grant in active_grants(user):
        if 'events:read' in grant.scopes:
            rows = rows | filter_events(EventOutbox.objects.filter(grant=grant, grant_revision=grant.revision), grant)
    return rows


class ManagementView(APIView):
    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not request.path.startswith('/api/v1/') or request.path.startswith(('/api/v1/auth/', '/api/v1/invitations/accept/')):
            return
        if request.user.is_authenticated and not throttle('management', request.user.pk, limit=LIMITS['management']):
            raise RateLimitExceeded()


class Health(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({'status': 'ok'})


class Auth(APIView):
    permission_classes = [AllowAny]

    def get(self, request, action):
        if action == 'csrf':
            return Response({'csrfToken': get_token(request)})
        if action == 'me' and request.user.is_authenticated:
            return Response({'id': request.user.pk, 'username': request.user.username, 'role': request.user.role})
        return Response({'detail': 'Not authenticated'}, status=403)

    def post(self, request, action):
        # DRF normally skips CSRF for anonymous sessions; login must not.
        SessionAuthentication().enforce_csrf(request)
        if action == 'login':
            if not isinstance(request.data, dict) or 'password' not in request.data:
                raise ValidationError('Password required')
            if not throttle('login', request_ip(request), limit=LIMITS['login']):
                return limit_response()
            fields(request.data, ['username', 'password'], ['username', 'password'])
            user = authenticate(request, username=request.data['username'], password=request.data['password'])
            if user is None:
                raise PermissionDenied('Invalid credentials')
            user = cast(User, user)
            login(request, user)
            return Response({'id': user.pk, 'username': user.username, 'role': user.role, 'csrfToken': get_token(request)})
        if action == 'logout':
            logout(request)
            return Response(status=204)
        raise ValidationError('Unknown auth action')


class Bots(ManagementView):
    def get(self, request, pk=None):
        bots = Bot.objects.all()
        if request.user.role != 'Owner':
            bots = bots.filter(pk__in=[grant.bot_id for grant in active_grants(request.user)])
        if pk is not None:
            return Response(bot_data(get_object_or_404(bots, pk=pk)))
        return Response([bot_data(b) for b in bots])

    def post(self, request, pk=None):
        if pk is not None:
            return Response(status=405)
        owner(request)
        fields(request.data, ['name', 'app_id', 'secret', 'password'], ['name', 'app_id', 'secret', 'password'])
        reauthenticate(request)
        for field in ['name', 'app_id', 'secret']:
            if not isinstance(request.data[field], str) or not request.data[field] or len(request.data[field]) > (120 if field == 'name' else 100 if field == 'app_id' else 4096):
                raise ValidationError({field: 'Invalid value'})
        if Bot.objects.filter(app_id=request.data['app_id']).exists():
            raise ValidationError({'app_id': 'Already exists'})
        bot = Bot.objects.create(name=request.data['name'], app_id=request.data['app_id'], encrypted_secret=encrypt_secret(request.data['secret']))
        AuditLog.objects.create(actor=request.user.username, action='bot.create', target=str(bot.pk))
        return Response(bot_data(bot), status=201)

    def patch(self, request, pk=None):
        owner(request)
        if pk is None:
            raise ValidationError('Bot ID required')
        fields(request.data, ['name', 'app_id', 'secret', 'is_active', 'password'], ['password'])
        reauthenticate(request)
        if not set(request.data) - {'password'}:
            raise ValidationError('At least one Bot field is required')
        values = {}
        for field, maximum in [('name', 120), ('app_id', 100), ('secret', 4096)]:
            if field in request.data:
                value = request.data[field]
                if not isinstance(value, str) or not value or len(value) > maximum:
                    raise ValidationError({field: 'Invalid value'})
                values[field] = value
        if 'is_active' in request.data:
            if type(request.data['is_active']) is not bool:
                raise ValidationError({'is_active': 'Boolean required'})
            values['is_active'] = request.data['is_active']
        try:
            bot, _ = update_bot(pk, request.user, **values)
        except Bot.DoesNotExist:
            return Response({'detail': 'Not found'}, status=404)
        except ValueError as error:
            raise ValidationError(str(error)) from None
        return Response(bot_data(bot))


class Users(ManagementView):
    def get(self, request):
        users = User.objects.order_by('username')
        if request.user.role != 'Owner':
            users = users.filter(role='Admin', is_active=True).exclude(pk=request.user.pk)
        return Response(list(users.values('id', 'username', 'role', 'is_active')))


class Quotas(ManagementView):
    def get(self, request):
        owner(request)
        now = int(timezone.now().timestamp())
        data = []
        for policy in QuotaPolicy.objects.order_by('pk'):
            window = now // policy.window_seconds
            count = QuotaUsage.objects.filter(policy=policy, window=window).values_list('count', flat=True).first() or 0
            data.append({
                'id': policy.pk, 'scope': policy.scope, 'subject_id': policy.subject_id,
                'window_seconds': policy.window_seconds, 'limit': policy.limit,
                'is_active': policy.is_active, 'used': count,
                'resets_at': (window + 1) * policy.window_seconds,
            })
        response = Response(data)
        response['Cache-Control'] = 'no-store'
        return response

    @transaction.atomic
    def post(self, request):
        owner(request)
        fields(request.data, ['scope', 'subject_id', 'window_seconds', 'limit', 'is_active', 'password'],
               ['scope', 'subject_id', 'window_seconds', 'limit', 'password'])
        reauthenticate(request)
        scope = request.data['scope']
        if scope not in ('platform', 'bot', 'user', 'key'):
            raise ValidationError({'scope': 'Invalid quota scope'})
        for field in ('subject_id', 'window_seconds', 'limit'):
            if type(request.data[field]) is not int:
                raise ValidationError({field: 'Integer required'})
        subject_id = request.data['subject_id']
        window = request.data['window_seconds']
        limit = request.data['limit']
        if window not in (60, 3600, 86400) or not 0 <= limit <= 1_000_000_000:
            raise ValidationError('Window must be 60, 3600 or 86400; limit must be 0–1000000000')
        active = request.data.get('is_active', True)
        if type(active) is not bool:
            raise ValidationError({'is_active': 'Boolean required'})
        if scope == 'platform':
            if subject_id != 0:
                raise ValidationError({'subject_id': 'Platform subject must be 0'})
        else:
            if subject_id < 1:
                raise ValidationError({'subject_id': 'Positive ID required'})
            get_object_or_404({'bot': Bot, 'user': User, 'key': ApiKey}[scope], pk=subject_id)
        policy, created = QuotaPolicy.objects.update_or_create(
            scope=scope, subject_id=subject_id, window_seconds=window,
            defaults={'limit': limit, 'is_active': active},
        )
        AuditLog.objects.create(actor=request.user.username, action='quota.update', target=str(policy.pk))
        return Response({'id': policy.pk}, status=201 if created else 200)


class UserLifecycle(ManagementView):
    @transaction.atomic
    def patch(self, request, pk):
        owner(request)
        fields(request.data, ['is_active', 'password'], ['is_active', 'password'])
        reauthenticate(request)
        if type(request.data['is_active']) is not bool:
            raise ValidationError({'is_active': 'Boolean required'})
        user = get_object_or_404(User.objects.select_for_update(), pk=pk, role=User.Role.ADMIN)
        if user.is_active != request.data['is_active']:
            user.is_active = request.data['is_active']
            user.save(update_fields=['is_active'])
            if not user.is_active:
                grants = BotGrant.objects.select_for_update().filter(user=user)
                for grant in grants:
                    grant.revision += 1
                    grant.save(update_fields=['revision'])
                ApiKey.objects.filter(user=user, revoked_at__isnull=True).update(revoked_at=timezone.now())
            AuditLog.objects.create(
                actor=request.user.username,
                action='user.activate' if user.is_active else 'user.deactivate',
                target=user.username,
            )
        return Response({'id': user.pk, 'username': user.username, 'role': user.role, 'is_active': user.is_active})


class Invitations(ManagementView):
    def get(self, request):
        owner(request)
        rows = Invitation.objects.order_by('-pk')
        return Response([{
            'id': row.pk,
            'expires_at': row.expires_at,
            'used_at': row.used_at,
            'accepted_by': row.accepted_by_id,
            'created_at': row.created_at,
        } for row in rows])

    def post(self, request):
        owner(request)
        fields(request.data, ['expires_hours', 'password'], ['password'])
        reauthenticate(request)
        try:
            lifetime = serializers.IntegerField(min_value=1, max_value=720).run_validation(
                request.data.get('expires_hours', 72),
            )
            invitation, token = create_invitation(request.user, lifetime)
        except (ValueError, PermissionError) as error:
            raise ValidationError(str(error)) from None
        return Response({
            'id': invitation.pk,
            'token': token,
            'expires_at': invitation.expires_at,
        }, status=201)


class AcceptInvitation(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        fields(request.data, ['token', 'username', 'password', 'email'], ['token', 'username', 'password'])
        try:
            user = accept_invitation(
                request.data['token'], request.data['username'], request.data['password'], request.data.get('email', ''),
            )
        except ValueError as error:
            raise ValidationError(str(error)) from None
        return Response({'id': user.pk, 'username': user.username, 'role': user.role}, status=201)


class Grants(ManagementView):
    def get(self, request):
        grants = BotGrant.objects.select_related('bot')
        if request.user.role != 'Owner':
            grants = grants.filter(parent__user=request.user)
            grants = [grant for grant in grants if grant_current(grant)]
        return Response([grant_data(grant) for grant in grants])

    @transaction.atomic
    def post(self, request):
        fields(request.data, ['user', 'bot', 'scopes', 'is_active', 'password', 'all_conversations', 'conversations'], ['user', 'bot', 'scopes'])
        reauthenticate(request)
        user = get_object_or_404(User, pk=serializers.IntegerField(min_value=1).run_validation(request.data['user']), is_active=True)
        bot = get_object_or_404(Bot, pk=serializers.IntegerField(min_value=1).run_validation(request.data['bot']))
        scopes = validate_scopes(request.data['scopes'])
        active = request.data.get('is_active', True)
        if not isinstance(active, bool):
            raise ValidationError({'is_active': 'Boolean required'})
        # Lock parent to serialize even the first grant creation.
        User.objects.select_for_update().get(pk=user.pk)
        parent = None
        if request.user.role != 'Owner':
            if user.pk == request.user.pk or user.role == 'Owner':
                raise PermissionDenied('Cannot modify your own grant or an Owner grant')
            parent = get_object_or_404(BotGrant.objects.select_for_update(), user=request.user, bot=bot)
            if not grant_current(parent) or not set(scopes) <= set(parent.scopes):
                raise PermissionDenied('Cannot delegate permissions you do not hold')
            existing = BotGrant.objects.filter(user=user, bot=bot).first()
            if existing and existing.parent_id != parent.pk:
                raise PermissionDenied('Only the creator of a delegated grant may update it')
        grant, created = BotGrant.objects.select_for_update().get_or_create(user=user, bot=bot)
        policy = {k: request.data[k] for k in ('all_conversations', 'conversations') if k in request.data}
        if created and parent and not policy:
            policy = policy_data(parent)
        configure_policy(grant, policy, parent)
        grant.parent, grant.parent_revision = parent, parent.revision if parent else None
        grant.scopes, grant.is_active = scopes, active
        if not created:
            grant.revision += 1
        grant.save()
        AuditLog.objects.create(actor=request.user.username, action='grant.update', target=str(grant.pk))
        return Response(grant_data(grant))


class MyGrants(ManagementView):
    def get(self, request):
        return Response([grant_data(grant) for grant in active_grants(request.user)])


class DashboardOverview(ManagementView):
    def get(self, request):
        raw_window = request.query_params.get('window_hours', '24')
        if not raw_window.isascii() or not raw_window.isdigit() or len(raw_window) > 4:
            raise ValidationError({'window_hours': 'Expected 24, 168, or 720'})
        window_hours = int(raw_window)
        if window_hours not in (24, 168, 720):
            raise ValidationError({'window_hours': 'Expected 24, 168, or 720'})
        now = timezone.now()
        start = now - timedelta(hours=window_hours)

        bots = Bot.objects.all()
        outbox = EventOutbox.objects.select_related('event', 'grant', 'grant__user', 'grant__bot')
        if request.user.role != 'Owner':
            user_grants = active_grants(request.user)
            visible_grants = [grant for grant in user_grants if 'events:read' in grant.scopes]
            bots = bots.filter(botgrant__user=request.user, botgrant__is_active=True, botgrant__user__is_active=True)
            outbox = outbox.filter(pk__in=visible_outbox(request.user).values('pk'))
            event_count = Event.objects.filter(pk__in=outbox.values('event_id'), received_at__gte=start, received_at__lt=now).count()
        else:
            event_count = Event.objects.filter(received_at__gte=start, received_at__lt=now).count()
        deliveries = outbox.filter(event__received_at__gte=start, event__received_at__lt=now)
        status_counts = deliveries.values('state').annotate(total=Count('pk'))
        by_state = {row['state']: row['total'] for row in status_counts}
        response = Response({
            'window_hours': window_hours,
            'window_start': start,
            'generated_at': now,
            'bot_count': bots.distinct().count(),
            'active_bot_count': bots.filter(is_active=True).distinct().count(),
            'event_count': event_count,
            'delivery_count': deliveries.count(),
            'delivered_count': by_state.get('delivered', 0),
            'pending_count': by_state.get('pending', 0),
            'processing_count': by_state.get('processing', 0),
            'failed_count': by_state.get('failed', 0),
            'cancelled_count': by_state.get('cancelled', 0),
        })
        response['Cache-Control'] = 'no-store'
        return response


class Subscriptions(ManagementView):
    def get(self, request):
        rows = HttpSubscription.objects.filter(grant__user=request.user).select_related('grant__user', 'grant__bot')
        return Response([{
            'id': row.pk, 'bot': row.grant.bot.pk, 'url': row.url,
            'is_active': row.is_active, 'is_current': subscription_is_current(row),
            'grant_revision': row.grant_revision,
        } for row in rows])

    @transaction.atomic
    def post(self, request):
        fields(request.data, ['bot', 'url', 'is_active', 'password', 'callback_secret'], ['bot', 'is_active', 'password'])
        reauthenticate(request)
        active = request.data['is_active']
        if type(active) is not bool:
            raise ValidationError({'is_active': 'Boolean required'})
        bot_id = serializers.IntegerField(min_value=1).run_validation(request.data['bot'])
        grant = get_object_or_404(BotGrant.objects.select_for_update(), user=request.user, bot_id=bot_id)
        if not active:
            get_object_or_404(HttpSubscription.objects.select_for_update(), grant=grant)
            disable_subscription(grant.pk, actor=request.user.username)
            return Response(status=204)
        try:
            sub = set_subscription(
                grant.pk, request.data.get('url'), actor=request.user.username,
                callback_secret=request.data.get('callback_secret'),
            )
        except ValueError as error:
            raise ValidationError(str(error)) from None
        return Response({'id': sub.pk, 'bot': bot_id, 'url': sub.url, 'grant_revision': sub.grant_revision}, status=201)


class Keys(ManagementView):
    def get(self, request, pk=None):
        if pk is not None:
            return Response(key_data(get_object_or_404(ApiKey, pk=pk, user=request.user)))
        return Response([key_data(k) for k in ApiKey.objects.filter(user=request.user)])

    def post(self, request, pk=None):
        if pk is not None:
            return Response(status=405)
        fields(request.data, ['bot', 'name', 'scopes', 'expires_at', 'password', 'all_conversations', 'conversations'], ['bot', 'name', 'scopes'])
        reauthenticate(request)
        bot = get_object_or_404(Bot, pk=request.data['bot'], is_active=True, botgrant__user=request.user, botgrant__is_active=True)
        scopes = validate_scopes(request.data['scopes'])
        name = serializers.CharField(max_length=120).run_validation(request.data['name'])
        expiry = serializers.DateTimeField(allow_null=True).run_validation(request.data.get('expires_at'))
        if isinstance(expiry, datetime) and expiry <= timezone.now():
            raise ValidationError({'expires_at': 'Must be in the future'})
        policy = {k: request.data[k] for k in ('all_conversations', 'conversations') if k in request.data}
        key, token = issue_key(request.user, bot, name, scopes, expiry, **policy)
        return Response({**key_data(key), 'token': token}, status=201, headers={'Cache-Control': 'no-store'})

    @transaction.atomic
    def patch(self, request, pk=None):
        fields(request.data, ['name', 'scopes', 'expires_at', 'all_conversations', 'conversations'])
        key = get_object_or_404(ApiKey.objects.select_for_update(), pk=pk, user=request.user, revoked_at__isnull=True)
        grant = key_grant(key)
        if key.expires_at and key.expires_at <= timezone.now():
            raise PermissionDenied('Expired key cannot be edited')
        if 'name' in request.data:
            key.name = serializers.CharField(max_length=120).run_validation(request.data['name'])
        if 'scopes' in request.data:
            key.scopes = validate_scopes(request.data['scopes'])
        if not set(key.scopes) <= set(grant.scopes):
            raise PermissionDenied('Scopes exceed grant')
        if 'expires_at' in request.data:
            expiry = serializers.DateTimeField(allow_null=True).run_validation(request.data['expires_at'])
            if expiry and expiry <= timezone.now():
                raise ValidationError('Expiry must be in the future')
            key.expires_at = expiry
        configure_policy(key, request.data, grant)
        key.save()
        AuditLog.objects.create(actor=request.user.username, action='key.update', target=str(key.pk))
        return Response(key_data(key), headers={'Cache-Control': 'no-store'})


class RevokeKey(ManagementView):
    def post(self, request, pk, global_revoke=False):
        fields(request.data, ['password'], ['password'])
        reauthenticate(request)
        keys = ApiKey.objects.all()
        if global_revoke:
            owner(request)
        else:
            keys = keys.filter(user=request.user)
        key = get_object_or_404(keys, pk=pk)
        key.revoked_at = timezone.now()
        key.save(update_fields=['revoked_at'])
        AuditLog.objects.create(actor=request.user.username, action='key.revoke', target=str(pk))
        return Response(status=204)


class RotateKey(ManagementView):
    def post(self, request, pk):
        fields(request.data, ['name', 'scopes', 'expires_at', 'password', 'all_conversations', 'conversations'])
        reauthenticate(request)
        values = {}
        values.update({k: request.data[k] for k in ('all_conversations', 'conversations') if k in request.data})
        if 'name' in request.data:
            values['name'] = serializers.CharField(max_length=120).run_validation(request.data['name'])
        if 'scopes' in request.data:
            values['scopes'] = validate_scopes(request.data['scopes'])
        if 'expires_at' in request.data:
            expiry = serializers.DateTimeField(allow_null=True).run_validation(request.data['expires_at'])
            if isinstance(expiry, datetime) and expiry <= timezone.now():
                raise ValidationError({'expires_at': 'Must be in the future'})
            values['expires_at'] = expiry
        try:
            key, token, old_key = rotate_key(request.user, pk, **values)
        except ApiKey.DoesNotExist:
            return Response({'detail': 'Not found'}, status=404)
        except PermissionDenied:
            raise
        return Response({**key_data(key), 'token': token, 'rotated_key': old_key.pk}, status=201, headers={'Cache-Control': 'no-store'})


class Bearer(BaseAuthentication):
    def authenticate_header(self, request):
        return 'Bearer'

    def authenticate(self, request):
        header = request.headers.get('Authorization', '').split()
        if len(header) != 2 or header[0].lower() != 'bearer':
            raise AuthenticationFailed('Bearer key required')
        key, scopes = authorize(header[1], request.query_params.get('bot_id'))
        request.effective_scopes = scopes
        if not bearer_throttle(key):
            raise RateLimitExceeded()
        consume_quota(key)
        return key.user, key


class Capabilities(APIView):
    authentication_classes = [Bearer]

    def get(self, request):
        from .conversations import unrestricted
        from .official_routes import OPERATIONS
        broad = unrestricted(request.auth)
        operations = ['GET /users/@me'] if 'query:read' in request.effective_scopes else []
        if 'messages:send' in request.effective_scopes:
            operations += ['POST /v2/users/{user_openid}/messages', 'POST /v2/groups/{group_openid}/messages']
            if broad:
                operations += ['POST /channels/{channel_id}/messages', 'POST /dms/{guild_id}/messages', 'POST /users/@me/dms']
        if 'messages:delete' in request.effective_scopes:
            operations += ['DELETE /v2/users/{user_openid}/messages/{message_id}', 'DELETE /v2/groups/{group_openid}/messages/{message_id}']
            if broad:
                operations += ['DELETE /channels/{channel_id}/messages/{message_id}', 'DELETE /dms/{guild_id}/messages/{message_id}']
        if 'media:upload' in request.effective_scopes:
            operations += [
                f'POST /v2/{kind}/{{{identifier}}}/{operation}'
                for kind, identifier in [('users', 'user_openid'), ('groups', 'group_openid')]
                for operation in ('files', 'upload_prepare', 'upload_part_finish')
            ]
        if broad:
            operations += [f'{method} /{path}' for method, path, scope in OPERATIONS if scope in request.effective_scopes]
        return Response({'bot_id': request.auth.bot_id, 'scopes': request.effective_scopes, 'proxy_enabled': bool(operations), 'websocket_enabled': 'events:read' in request.effective_scopes, 'operations': operations, **policy_data(request.auth), 'unrestricted_conversations': broad}, headers={'Cache-Control': 'no-store'})


class ManagementEvents(ManagementView):
    def get(self, request):
        before = request.query_params.get('before', '')
        if before and (not before.isascii() or not before.isdigit() or len(before) > 18):
            raise ValidationError({'before': 'Positive integer required'})
        events = Event.objects.select_related('bot')
        if request.user.role != 'Owner':
            events = events.filter(pk__in=visible_outbox(request.user).values('event_id'))
        if before:
            events = events.filter(pk__lt=int(before))
        rows = list(events.order_by('-id')[:51])
        page = rows[:50]
        response = Response({
            'events': [{'id': row.pk, 'bot': row.bot.pk, 'event_id': row.event_id, 'event_type': row.event_type, 'received_at': row.received_at, 'payload': row.payload} for row in page],
            'next_before': str(page[-1].pk) if page else None, 'has_more': len(rows) > 50,
        })
        response['Cache-Control'] = 'no-store'
        return response


class Deliveries(ManagementView):
    def get(self, request):
        before = request.query_params.get('before', '')
        if before and (not before.isascii() or not before.isdigit() or len(before) > 18):
            raise ValidationError({'before': 'Positive integer required'})
        rows = EventOutbox.objects.all()
        if request.user.role != 'Owner':
            rows = rows.filter(pk__in=visible_outbox(request.user).values('pk'))
        if before:
            rows = rows.filter(pk__lt=int(before))
        page = list(rows.select_related('event__bot', 'grant__user').order_by('-pk')[:51])
        data = [{
            'id': r.pk, 'event_id': r.event.event_id, 'bot': r.event.bot.pk,
            'user': r.grant.user.pk, 'state': r.state, 'attempts': r.attempts,
            'available_at': r.available_at, 'lease_until': r.lease_until,
        } for r in page[:50]]
        response = Response({'deliveries': data, 'has_more': len(page) > 50, 'next_before': str(page[min(len(page), 50) - 1].pk) if page else None})
        response['Cache-Control'] = 'no-store'
        return response


class DeliveryAttempts(ManagementView):
    def get(self, request, pk):
        rows = DeliveryAttempt.objects.filter(outbox_id=pk, outbox__grant__user=request.user)
        if request.user.role == 'Owner':
            rows = DeliveryAttempt.objects.filter(outbox_id=pk)
        else:
            rows = rows.filter(outbox_id__in=visible_outbox(request.user).values('pk'))
        if not rows.exists():
            return Response({'detail': 'Not found'}, status=404)
        return Response([{
            'id': row.pk, 'generation': row.generation, 'attempt_number': row.attempt_number, 'state': row.state,
            'http_status': row.http_status, 'error_code': row.error_code,
            'started_at': row.started_at, 'finished_at': row.finished_at,
        } for row in rows.order_by('generation', 'attempt_number')])


class ReplayDelivery(ManagementView):
    def post(self, request, pk):
        fields(request.data, ['password'], ['password'])
        reauthenticate(request)
        try:
            row = replay_delivery(pk, request.user)
        except LookupError:
            return Response({'detail': 'Not found'}, status=404)
        except ValueError as error:
            raise ValidationError(str(error)) from None
        return Response({
            'id': row.pk, 'state': row.state, 'attempt_generation': row.attempt_generation,
            'warning': 'Replay may deliver the event more than once; consumers must deduplicate.',
        }, status=202)


class ApiCalls(ManagementView):
    def get(self, request):
        before = request.query_params.get('before', '')
        if before and (not before.isascii() or not before.isdigit() or len(before) > 18):
            raise ValidationError({'before': 'Positive integer required'})
        rows = ApiCallAudit.objects.all()
        if request.user.role != 'Owner':
            rows = rows.filter(user=request.user)
        if before:
            rows = rows.filter(pk__lt=int(before))
        page = list(rows.order_by('-pk')[:51])
        response = Response({
            'calls': [{
                'id': row.pk, 'request_id': row.request_id, 'bot': row.bot_id,
                'api_key': row.api_key_id, 'method': row.method, 'path': row.path,
                'message_type': row.message_type, 'replayed': row.replayed,
                'status_code': row.status_code, 'duration_ms': row.duration_ms,
                'created_at': row.created_at,
            } for row in page[:50]],
            'has_more': len(page) > 50,
            'next_before': str(page[49].pk) if len(page) > 49 else None,
        })
        response['Cache-Control'] = 'no-store'
        return response


class RelayEvents(DataPlaneAuditMixin, Capabilities):
    def get(self, request):
        if 'events:read' not in request.effective_scopes:
            raise PermissionDenied('events:read required')
        cursor = request.query_params.get('after', '0')
        limit = request.query_params.get('limit', '50')
        if not cursor.isascii() or not cursor.isdigit() or len(cursor) > 18:
            raise ValidationError({'after': 'Non-negative integer cursor required'})
        if not limit.isascii() or not limit.isdigit() or len(limit) > 3 or not 1 <= int(limit) <= 100:
            raise ValidationError({'limit': 'Expected integer between 1 and 100'})
        rows = EventOutbox.objects.filter(
            grant__user=request.user, grant__bot_id=request.auth.bot_id,
            grant__is_active=True, grant_revision=request.auth.grant_revision,
            event__bot_id=request.auth.bot_id, id__gt=int(cursor),
        ).select_related('event').order_by('id')
        rows = list(filter_events(filter_events(rows, key_grant(request.auth)), request.auth)[:int(limit) + 1])
        page = rows[:int(limit)]
        response = Response({
            'events': [{'cursor': str(row.pk), 'payload': row.event.payload, 'received_at': row.event.received_at} for row in page],
            'next_cursor': str(page[-1].pk) if page else cursor,
            'has_more': len(rows) > int(limit),
        })
        response['Cache-Control'] = 'no-store'
        return response


class Proxy(DataPlaneAuditMixin, Capabilities):
    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        import re
        from .conversations import check_conversation, unrestricted
        from .models import BotGrant
        path = kwargs.get('path', '')
        match = re.match(r'^v2/(users|groups)/([A-Za-z0-9_-]{1,128})(?:/|$)', path)
        if request.path.startswith('/qq/') and match:
            check_conversation(request.auth, match[1] == 'users', match[2])
        elif request.path.startswith('/qq/') and path != 'users/@me':
            if not unrestricted(request.auth):
                raise PermissionDenied('This operation has no supported conversation target')

    def onebot_http(self, request, path):
        from .onebot import invoke
        if not path.rstrip('/'):
            return Response(status=404)
        if request.method == 'GET':
            params = request.query_params.dict()
        else:
            if len(request.body) > 1048576:
                return Response(status=413)
            if parse_header_parameters(request.content_type)[0] not in {'application/json', 'application/x-www-form-urlencoded'}:
                return Response(status=406)
            if not isinstance(request.data, dict):
                return Response(status=400)
            params = request.data.dict() if hasattr(request.data, 'dict') else request.data
        response = invoke(request.auth.bot, request.effective_scopes, path.rstrip('/'), params, key=request.auth)
        if response.data['retcode'] == 1404:
            response.status_code = 404
        response['Cache-Control'] = 'no-store'
        return response

    def post(self, request, path=''):
        if request.path.startswith('/onebot/'):
            return self.onebot_http(request, path)
        media_upload = bool(MEDIA_PATH.fullmatch(path))
        if not request.path.startswith('/qq/') or not (MESSAGE_PATH.fullmatch(path) or media_upload):
            return self.denied(request, path)
        required_scope = 'media:upload' if media_upload else 'messages:send'
        if required_scope not in request.effective_scopes:
            raise PermissionDenied(required_scope + ' required')
        raw = request.body
        if len(raw) > 1048576:
            return Response({'code': 'body_too_large', 'source': 'platform'}, status=413)
        media_type = parse_header_parameters(request.content_type)[0]
        multipart = media_type == 'multipart/form-data' and path.startswith('channels/')
        content_type = request.META.get('CONTENT_TYPE') if multipart else None
        if multipart:
            try:
                validate_multipart(content_type)
            except ValueError as error:
                raise ValidationError(str(error)) from None
        elif media_type != 'application/json':
            return Response({'code': 'json_required', 'source': 'platform'}, status=415)
        if not multipart and not isinstance(request.data, dict):
            raise ValidationError('JSON object required')
        if not multipart and 'bot_id' in request.data and str(request.data['bot_id']) != str(request.auth.bot_id):
            raise PermissionDenied('Bot mismatch')
        if media_upload and path.endswith('/files'):
            # Official uploads can also send messages; never allow that side effect
            # through an upload-only credential. Require an explicit choice.
            if type(request.data.get('srv_send_msg')) is not bool:
                raise ValidationError({'srv_send_msg': 'Explicit boolean required by this proxy'})
            if request.data['srv_send_msg'] and 'messages:send' not in request.effective_scopes:
                raise PermissionDenied('messages:send required for srv_send_msg=true')
        reservation = None
        cached = None
        if 'Idempotency-Key' in request.headers:
            try:
                reservation, cached = reserve_send(
                    request.auth, request.headers['Idempotency-Key'], path,
                    request.META.get('QUERY_STRING', ''), raw,
                    content_type=content_type,
                )
            except ValueError as error:
                raise ValidationError(str(error)) from None
            except SendConflict as error:
                return Response({'code': error.code, 'source': 'platform'}, status=409)
        try:
            transport = upload_media if media_upload else send_message
            encoding = {'content_type': content_type} if multipart else {}
            result = cached if cached is not None else transport(
                request.auth.bot, path, raw, request.META.get('QUERY_STRING', ''),
                **encoding,
            )
            if reservation is not None and cached is None:
                complete_send(reservation, result)
            status, body, headers = result
        except OfficialCredentialError:
            if reservation is not None:
                unknown_send(reservation)
            return Response({'code': 'official_outcome_unknown', 'source': 'platform', 'detail': 'Send outcome unknown; do not blindly retry'}, status=502)
        response = HttpResponse(body, status=status)
        for name, value in headers.items():
            response[name] = value
        if cached is not None:
            response['Idempotency-Replayed'] = 'true'
        response['Cache-Control'] = 'no-store'
        return response

    def get(self, request, path=''):
        if request.path.startswith('/onebot/'):
            return self.onebot_http(request, path)
        if request.path.startswith('/qq/') and path == 'users/@me':
            if 'query:read' not in request.effective_scopes:
                raise PermissionDenied('query:read required')
            try:
                status, raw, headers = get_self(request.auth.bot, request.META.get('QUERY_STRING', ''))
            except OfficialCredentialError:
                return Response({'code': 'official_unavailable', 'source': 'platform', 'detail': 'Official query failed'}, status=502)
            response = HttpResponse(raw, status=status)
            for name, value in headers.items():
                response[name] = value
            response['Cache-Control'] = 'no-store'
            return response
        return self.denied(request, path)

    def denied(self, request, path=''):
        from .official_routes import required_scope
        from .official import _request
        scope = required_scope(request.method, path) if request.path.startswith('/qq/') else None
        if scope:
            if scope not in request.effective_scopes:
                raise PermissionDenied(scope + ' required')
            body = None
            if request.body:
                if request.method == 'GET' or len(request.body) > 1048576:
                    raise ValidationError('Invalid request body')
                if request.content_type != 'application/json' or not isinstance(request.data, dict):
                    raise ValidationError('JSON object required')
                body = request.body
            try:
                status, raw, headers = _request(request.auth.bot, request.method, path, request.META.get('QUERY_STRING', ''), body)
            except OfficialCredentialError:
                return Response({'code': 'official_outcome_unknown', 'source': 'platform'}, status=502)
            response = HttpResponse(raw, status=status)
            for name, value in headers.items():
                response[name] = value
            response['Cache-Control'] = 'no-store'
            return response
        if isinstance(request.data, dict) and 'bot_id' in request.data and str(request.data['bot_id']) != str(request.auth.bot_id):
            raise PermissionDenied('Bot mismatch')
        return Response({'code': 'proxy_not_available', 'source': 'platform', 'detail': 'This operation is not supported'}, status=501)

    def patch(self, request, path=''):
        return self.denied(request, path)

    def put(self, request, path=''):
        return self.denied(request, path)

    def delete(self, request, path=''):
        if not request.path.startswith('/qq/') or not DELETE_MESSAGE_PATH.fullmatch(path):
            return self.denied(request, path)
        if 'messages:delete' not in request.effective_scopes:
            raise PermissionDenied('messages:delete required')
        if request.body:
            raise ValidationError('DELETE message requests must not contain a body')
        try:
            status, body, headers = delete_message(request.auth.bot, path, request.META.get('QUERY_STRING', ''))
        except OfficialCredentialError:
            return Response({'code': 'official_outcome_unknown', 'source': 'platform'}, status=502)
        response = HttpResponse(body, status=status)
        for name, value in headers.items():
            response[name] = value
        response['Cache-Control'] = 'no-store'
        return response

    put = patch = denied
