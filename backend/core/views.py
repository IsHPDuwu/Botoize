from django.contrib.auth import authenticate, login, logout
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.authentication import BaseAuthentication, SessionAuthentication
from rest_framework.permissions import AllowAny
from rest_framework.exceptions import PermissionDenied, ValidationError, AuthenticationFailed
from rest_framework import serializers
from .models import User, Bot, BotGrant, ApiKey, AuditLog
from .services import authorize, encrypt_secret, issue_key, validate_scopes


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
    return {'id': key.pk, 'bot': key.bot_id, 'name': key.name, 'prefix': key.prefix, 'scopes': key.scopes, 'expires_at': key.expires_at, 'revoked_at': key.revoked_at}


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
            fields(request.data, ['username', 'password'], ['username', 'password'])
            user = authenticate(request, username=request.data['username'], password=request.data['password'])
            if user is None:
                raise PermissionDenied('Invalid credentials')
            login(request, user)
            return Response({'id': user.pk, 'username': user.username, 'role': user.role, 'csrfToken': get_token(request)})
        if action == 'logout':
            logout(request)
            return Response(status=204)
        raise ValidationError('Unknown auth action')


class Bots(APIView):
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


class Grants(APIView):
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


class MyGrants(APIView):
    def get(self, request):
        grants = BotGrant.objects.filter(user=request.user, is_active=True, bot__is_active=True).select_related('bot')
        return Response([{'bot': bot_data(grant.bot), 'scopes': grant.scopes, 'revision': grant.revision} for grant in grants])


class Keys(APIView):
    def get(self, request):
        return Response([key_data(k) for k in ApiKey.objects.filter(user=request.user)])

    def post(self, request):
        fields(request.data, ['bot', 'name', 'scopes', 'expires_at', 'password'], ['bot', 'name', 'scopes', 'password'])
        reauthenticate(request)
        bot = get_object_or_404(Bot, pk=request.data['bot'], is_active=True, botgrant__user=request.user, botgrant__is_active=True)
        scopes = validate_scopes(request.data['scopes'])
        name = serializers.CharField(max_length=120).run_validation(request.data['name'])
        expiry = serializers.DateTimeField(allow_null=True).run_validation(request.data.get('expires_at'))
        if expiry and expiry <= timezone.now():
            raise ValidationError({'expires_at': 'Must be in the future'})
        key, token = issue_key(request.user, bot, name, scopes, expiry)
        return Response({**key_data(key), 'token': token}, status=201)


class RevokeKey(APIView):
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


class Bearer(BaseAuthentication):
    def authenticate_header(self, request):
        return 'Bearer'

    def authenticate(self, request):
        header = request.headers.get('Authorization', '').split()
        if len(header) != 2 or header[0].lower() != 'bearer':
            raise AuthenticationFailed('Bearer key required')
        key, scopes = authorize(header[1], request.query_params.get('bot_id'))
        request.effective_scopes = scopes
        return key.user, key


class Capabilities(APIView):
    authentication_classes = [Bearer]

    def get(self, request):
        return Response({'bot_id': request.auth.bot_id, 'scopes': request.effective_scopes, 'proxy_enabled': False, 'websocket_enabled': False, 'operations': []})


class Proxy(Capabilities):
    def denied(self, request, path=''):
        if isinstance(request.data, dict) and 'bot_id' in request.data and str(request.data['bot_id']) != str(request.auth.bot_id):
            raise PermissionDenied('Bot mismatch')
        return Response({'code': 'proxy_not_available', 'source': 'platform', 'detail': 'Official proxy and OneBot are not implemented'}, status=501)

    get = post = put = patch = delete = denied