from datetime import datetime, timedelta
from typing import cast

from django.contrib.auth import authenticate, login, logout
from django.middleware.csrf import get_token
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.db.models import Count, F
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.authentication import BaseAuthentication, SessionAuthentication
from rest_framework.permissions import AllowAny
from rest_framework.exceptions import PermissionDenied, ValidationError, AuthenticationFailed
from rest_framework import serializers
from .models import User, Bot, BotGrant, ApiKey, ApiCallAudit, AuditLog, DeliveryAttempt, Event, EventOutbox, Invitation
from .services import authorize, encrypt_secret, issue_key, rotate_key, update_bot, validate_scopes
from .official import get_self, send_message, MESSAGE_PATH, OfficialCredentialError
from .models import HttpSubscription
from .subscriptions import disable_subscription, set_subscription, subscription_is_current
from .request_context import DataPlaneAuditMixin
from .invitations import accept_invitation, create_invitation
from .replay import replay_delivery
from .throttle import LIMITS, RateLimitExceeded, bearer_throttle, limit_response, request_ip, throttle


def fields(data, allowed, required=()):
    if not isinstance(data, dict) or set(data) - set(allowed) or set(required) - set(data):
        raise ValidationError('Unexpected or missing fields')


def owner(request):
    if request.user.role != 'Owner':
        raise PermissionDenied('Owner required')


def reauthenticate(request):
    if not request.user.check_password(request.data.get('password', '')):
        raise PermissionDenied('Password confirmation required')


def bot_data(bot):
    return {'id': bot.pk, 'name': bot.name, 'app_id': bot.app_id, 'is_active': bot.is_active}


def key_data(key):
    return {'id': key.pk, 'bot': key.bot_id, 'name': key.name, 'prefix': key.prefix, 'scopes': key.scopes, 'expires_at': key.expires_at, 'revoked_at': key.revoked_at, 'grant_revision': key.grant_revision}


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
    def get(self, request):
        bots = Bot.objects.all()
        if request.user.role != 'Owner':
            bots = bots.filter(is_active=True, botgrant__user=request.user, botgrant__is_active=True)
        return Response([bot_data(b) for b in bots])

    def post(self, request):
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
        if len(request.data) == 1:
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
        owner(request)
        return Response(list(User.objects.order_by('username').values('id', 'username', 'role', 'is_active')))


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
        owner(request)
        return Response(list(BotGrant.objects.values('id', 'user_id', 'bot_id', 'scopes', 'is_active', 'revision')))

    @transaction.atomic
    def post(self, request):
        owner(request)
        fields(request.data, ['user', 'bot', 'scopes', 'is_active', 'password'], ['user', 'bot', 'scopes', 'password'])
        reauthenticate(request)
        user = get_object_or_404(User, pk=request.data['user'], is_active=True)
        bot = get_object_or_404(Bot, pk=request.data['bot'])
        scopes = validate_scopes(request.data['scopes'])
        active = request.data.get('is_active', True)
        if not isinstance(active, bool):
            raise ValidationError({'is_active': 'Boolean required'})
        # Lock parent to serialize even the first grant creation.
        User.objects.select_for_update().get(pk=user.pk)
        grant, created = BotGrant.objects.select_for_update().get_or_create(user=user, bot=bot)
        grant.scopes, grant.is_active = scopes, active
        if not created:
            grant.revision += 1
        grant.save()
        AuditLog.objects.create(actor=request.user.username, action='grant.update', target=str(grant.pk))
        return Response({'id': grant.pk, 'revision': grant.revision, 'is_active': active})


class MyGrants(ManagementView):
    def get(self, request):
        grants = BotGrant.objects.filter(user=request.user, is_active=True, bot__is_active=True).select_related('bot')
        return Response([{'bot': bot_data(grant.bot), 'scopes': grant.scopes, 'revision': grant.revision} for grant in grants])


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
            user_grants = list(BotGrant.objects.filter(
                user=request.user, is_active=True, user__is_active=True, bot__is_active=True,
            ))
            visible_grants = [grant for grant in user_grants if 'events:read' in grant.scopes]
            bots = bots.filter(botgrant__user=request.user, botgrant__is_active=True, botgrant__user__is_active=True)
            outbox = outbox.filter(
                grant_id__in=[grant.pk for grant in visible_grants],
                grant_revision=F('grant__revision'),
            )
            visible_bot_ids = {grant.bot_id for grant in visible_grants}
            event_count = Event.objects.filter(bot_id__in=visible_bot_ids, received_at__gte=start, received_at__lt=now).count()
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
        fields(request.data, ['bot', 'url', 'is_active', 'password'], ['bot', 'is_active', 'password'])
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
            sub = set_subscription(grant.pk, request.data.get('url'), actor=request.user.username)
        except ValueError as error:
            raise ValidationError(str(error)) from None
        return Response({'id': sub.pk, 'bot': bot_id, 'url': sub.url, 'grant_revision': sub.grant_revision}, status=201)


class Keys(ManagementView):
    def get(self, request):
        return Response([key_data(k) for k in ApiKey.objects.filter(user=request.user)])

    def post(self, request):
        fields(request.data, ['bot', 'name', 'scopes', 'expires_at', 'password'], ['bot', 'name', 'scopes', 'password'])
        reauthenticate(request)
        bot = get_object_or_404(Bot, pk=request.data['bot'], is_active=True, botgrant__user=request.user, botgrant__is_active=True)
        scopes = validate_scopes(request.data['scopes'])
        name = serializers.CharField(max_length=120).run_validation(request.data['name'])
        expiry = serializers.DateTimeField(allow_null=True).run_validation(request.data.get('expires_at'))
        if isinstance(expiry, datetime) and expiry <= timezone.now():
            raise ValidationError({'expires_at': 'Must be in the future'})
        key, token = issue_key(request.user, bot, name, scopes, expiry)
        return Response({**key_data(key), 'token': token}, status=201)


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
        fields(request.data, ['name', 'scopes', 'expires_at', 'password'], ['password'])
        reauthenticate(request)
        values = {}
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
        return Response({**key_data(key), 'token': token, 'rotated_key': old_key.pk}, status=201)


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
        return key.user, key


class Capabilities(APIView):
    authentication_classes = [Bearer]

    def get(self, request):
        operations = ['GET /users/@me'] if 'query:read' in request.effective_scopes else []
        if 'messages:send' in request.effective_scopes:
            operations += ['POST /v2/users/{user_openid}/messages', 'POST /v2/groups/{group_openid}/messages']
        return Response({'bot_id': request.auth.bot_id, 'scopes': request.effective_scopes, 'proxy_enabled': bool(operations), 'websocket_enabled': 'events:read' in request.effective_scopes, 'operations': operations})


class ManagementEvents(ManagementView):
    def get(self, request):
        before = request.query_params.get('before', '')
        if before and (not before.isascii() or not before.isdigit() or len(before) > 18):
            raise ValidationError({'before': 'Positive integer required'})
        events = Event.objects.select_related('bot')
        if request.user.role != 'Owner':
            snapshots = EventOutbox.objects.filter(
                grant__user=request.user, grant__is_active=True,
                grant__bot__is_active=True, grant_revision=F('grant__revision'),
            ).select_related('grant')
            # JSON containment is not supported by the SQLite development DB.
            allowed = [row.pk for row in BotGrant.objects.filter(user=request.user, is_active=True) if 'events:read' in row.scopes]
            events = events.filter(pk__in=snapshots.filter(grant_id__in=allowed).values('event_id'))
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
            grants = [g.pk for g in BotGrant.objects.filter(user=request.user, is_active=True, bot__is_active=True) if 'events:read' in g.scopes]
            rows = rows.filter(grant_id__in=grants, grant_revision=F('grant__revision'))
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
        rows = list(EventOutbox.objects.filter(
            grant__user=request.user, grant__bot_id=request.auth.bot_id,
            grant__is_active=True, grant_revision=request.auth.grant_revision,
            event__bot_id=request.auth.bot_id, id__gt=int(cursor),
        ).select_related('event').order_by('id')[:int(limit) + 1])
        page = rows[:int(limit)]
        response = Response({
            'events': [{'cursor': str(row.pk), 'payload': row.event.payload, 'received_at': row.event.received_at} for row in page],
            'next_cursor': str(page[-1].pk) if page else cursor,
            'has_more': len(rows) > int(limit),
        })
        response['Cache-Control'] = 'no-store'
        return response


class Proxy(DataPlaneAuditMixin, Capabilities):
    def post(self, request, path=''):
        if request.path.startswith('/onebot/'):
            from .onebot import invoke
            if len(request.body) > 1048576:
                return Response({'detail': 'Body too large'}, status=413)
            if not isinstance(request.data, dict):
                raise ValidationError('JSON object required')
            if path == '':
                fields(request.data, ['action', 'params', 'echo'], ['action'])
                action, params = request.data['action'], request.data.get('params', {})
            else:
                action, params = path.rstrip('/'), request.data
            return invoke(request.auth.bot, request.effective_scopes, action, params, request.data.get('echo') if path == '' else None)
        if not request.path.startswith('/qq/') or not MESSAGE_PATH.fullmatch(path):
            return self.denied(request, path)
        if 'messages:send' not in request.effective_scopes:
            raise PermissionDenied('messages:send required')
        raw = request.body
        if len(raw) > 1048576:
            return Response({'code': 'body_too_large', 'source': 'platform'}, status=413)
        if request.content_type != 'application/json':
            return Response({'code': 'json_required', 'source': 'platform'}, status=415)
        if not isinstance(request.data, dict):
            raise ValidationError('JSON object required')
        if 'bot_id' in request.data and str(request.data['bot_id']) != str(request.auth.bot_id):
            raise PermissionDenied('Bot mismatch')
        try:
            status, body, headers = send_message(request.auth.bot, path, raw, request.META.get('QUERY_STRING', ''))
        except OfficialCredentialError:
            return Response({'code': 'official_outcome_unknown', 'source': 'platform', 'detail': 'Send outcome unknown; do not blindly retry'}, status=502)
        response = HttpResponse(body, status=status)
        for name, value in headers.items():
            response[name] = value
        response['Cache-Control'] = 'no-store'
        return response

    def get(self, request, path=''):
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
        if isinstance(request.data, dict) and 'bot_id' in request.data and str(request.data['bot_id']) != str(request.auth.bot_id):
            raise PermissionDenied('Bot mismatch')
        return Response({'code': 'proxy_not_available', 'source': 'platform', 'detail': 'Official proxy and OneBot are not implemented'}, status=501)

    put = patch = delete = denied