from dataclasses import asdict

from django.db import transaction, IntegrityError
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError, PermissionDenied
from rest_framework.response import Response

from .models import Provider, Channel, Bot, AuditLog, Conversation, Event, BotGrant
from .services import encrypt_secret, update_bot
from .upstreams import INTERFACES, validate_interface, validate_base_url, validate_onebot_url, onebot_version
from .views import ManagementView, owner, fields
from .conversations import conversation_data, grant_current, discover


def text(data, key, maximum=120):
    value = data.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValidationError({key: 'Invalid value'})
    return value.strip()


def provider_data(provider, user):
    channels = []
    for channel in provider.channels.all():
        bot = channel.bots.first()
        if bot is None:
            continue
        models = bot.conversations.order_by('pk')
        if user.role != 'Owner':
            grant = BotGrant.objects.filter(user=user, bot=bot).select_related('user', 'bot').first()
            if not grant or not grant_current(grant):
                continue
            if not grant.all_conversations:
                models = models.filter(pk__in=grant.conversations.values('pk'))
        channels.append({'id': channel.pk, 'bot_id': bot.pk, 'name': channel.name,
                         'base_url': channel.base_url, 'interface_type': channel.interface_type,
                         'event_reporting_enabled': bool(channel.encrypted_event_secret),
                         'app_id': bot.app_id, 'is_active': bot.is_active,
                         'models': [conversation_data(model) for model in models]})
    return {'id': provider.pk, 'name': provider.name, 'channels': channels}


def save_model(bot, model):
    fields(model, ['id', 'name', 'isDirect', 'userid', 'groupid'], ['isDirect'])
    direct = model['isDirect']
    if type(direct) is not bool:
        raise ValidationError('isDirect must be boolean')
    target_key = 'userid' if direct else 'groupid'
    if ('groupid' if direct else 'userid') in model:
        raise ValidationError('Select exactly one conversation target')
    target = text(model, target_key, 256 if onebot_version(bot) else 128)
    import re
    if onebot_version(bot):
        from .onebot_upstream import native_id
        from .onebot_common import OneBotError
        try:
            target = str(native_id(target, onebot_version(bot)))
        except OneBotError:
            raise ValidationError('Invalid OneBot conversation ID') from None
    elif not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', target):
        raise ValidationError('Invalid upstream OpenID')
    name = model.get('name', '')
    if not isinstance(name, str) or len(name) > 120:
        raise ValidationError('Invalid conversation name')
    if 'id' in model:
        if type(model['id']) is not int:
            raise ValidationError('Invalid conversation ID')
        row = get_object_or_404(Conversation, pk=model['id'], bot=bot)
        if row.is_direct != direct or row.target_id != target:
            raise ValidationError('Existing conversation identity cannot be changed')
    else:
        row, _ = Conversation.objects.get_or_create(bot=bot, is_direct=direct, target_id=target)
    row.name = name.strip()
    row.save(update_fields=['name'])
    return row.pk


@transaction.atomic
def save_provider(request, pk=None):
    fields(request.data, ['name', 'channels', 'password'], ['name', 'channels'])
    name = text(request.data, 'name')
    channels = request.data['channels']
    if not isinstance(channels, list) or not 1 <= len(channels) <= 100:
        raise ValidationError({'channels': '1 to 100 channels required'})
    provider = get_object_or_404(Provider.objects.select_for_update(), pk=pk) if pk else Provider()
    provider.name = name
    provider.save()
    seen_channels = set()
    for item in channels:
        fields(item, ['id', 'bot_id', 'name', 'interface_type', 'base_url', 'app_id', 'secret', 'clear_secret', 'event_secret', 'event_reporting_enabled', 'is_active', 'models'],
               ['name', 'interface_type', 'app_id', 'is_active', 'models'])
        try:
            validate_interface(item['interface_type'])
            is_onebot = item['interface_type'] in {'onebot_v11', 'onebot_v12'}
            base_url = (validate_onebot_url(item.get('base_url')) if is_onebot else
                        validate_base_url(item.get('base_url', 'https://api.bot.qq.com')))
        except ValueError as exc:
            raise ValidationError(str(exc)) from None
        channel_id = item.get('id')
        if channel_id is not None and (type(channel_id) is not int or channel_id in seen_channels):
            raise ValidationError('Invalid or duplicate channel ID')
        channel = get_object_or_404(Channel.objects.select_for_update(), provider=provider, pk=channel_id) if channel_id is not None else Channel(provider=provider)
        old_interface = channel.interface_type if channel.pk else None
        protocol_changed = old_interface is not None and old_interface != item['interface_type'] and not (
            old_interface.startswith('qq_official_') and item['interface_type'].startswith('qq_official_'))
        if protocol_changed and not item.get('secret') and item.get('clear_secret') is not True:
            raise ValidationError('Protocol changes require a new secret or explicit clear_secret for OneBot')
        if protocol_changed:
            channel.encrypted_event_secret = ''
        transport_changed = channel.pk and (channel.base_url != base_url or channel.interface_type != item['interface_type'])
        channel.name = text(item, 'name')
        channel.base_url, channel.interface_type = base_url, item['interface_type']
        if 'event_secret' in item:
            value = item['event_secret']
            if not is_onebot or not isinstance(value, str) or len(value) > 4096:
                raise ValidationError('Invalid OneBot event secret')
            # Omit to retain, non-empty to rotate, empty to disable HTTP reporting.
            channel.encrypted_event_secret = encrypt_secret(value) if value else ''
        channel.save()
        seen_channels.add(channel.pk)
        if type(item['is_active']) is not bool:
            raise ValidationError('is_active must be boolean')
        app_id = text(item, 'app_id', 256 if is_onebot else 100)
        if is_onebot:
            from .onebot_upstream import native_id
            from .onebot_common import OneBotError
            try:
                if str(native_id(app_id, 11 if item['interface_type'] == 'onebot_v11' else 12)) != app_id:
                    raise ValidationError('Use canonical numeric Bot ID for OneBot 11')
            except OneBotError:
                raise ValidationError('Invalid OneBot Bot ID') from None
        values = {'name': channel.name, 'app_id': app_id, 'is_active': item['is_active']}
        if item.get('secret'):
            values['secret'] = text(item, 'secret', 4096)
            if is_onebot and (not values['secret'].isascii() or any(ord(c) <= 32 or ord(c) == 127 for c in values['secret'])):
                raise ValidationError('OneBot access token must be a visible ASCII string')
        elif 'secret' in item and not isinstance(item['secret'], str):
            raise ValidationError('Invalid secret')
        if 'clear_secret' in item:
            if not is_onebot or type(item['clear_secret']) is not bool:
                raise ValidationError('clear_secret is only supported for OneBot')
            if item['clear_secret']:
                values['secret'] = ''
        bot = channel.bots.first()
        if 'bot_id' in item and (type(item['bot_id']) is not int or not bot or item['bot_id'] != bot.pk):
            raise ValidationError('Bot does not belong to this channel')
        if bot:
            try:
                bot, _ = update_bot(bot.pk, request.user, **values)
            except ValueError:
                raise ValidationError('AppID / Bot ID already exists') from None
            if transport_changed:
                from django.db.models import F
                from django.utils import timezone
                from .models import ApiKey, GatewaySession, OneBotUpstreamSession
                BotGrant.objects.filter(bot=bot).update(revision=F('revision') + 1)
                ApiKey.objects.filter(bot=bot, revoked_at__isnull=True).update(revoked_at=timezone.now())
                GatewaySession.objects.filter(bot=bot).delete()
                OneBotUpstreamSession.objects.filter(bot=bot).delete()
        else:
            if 'secret' not in values:
                if is_onebot:
                    values['secret'] = ''
                else:
                    raise ValidationError('AppSecret required for a new Channel')
            bot = Bot.objects.create(channel=channel, encrypted_secret=encrypt_secret(values.pop('secret')), **values)
        models = item['models']
        if not isinstance(models, list) or len(models) > 10000:
            raise ValidationError('Invalid conversation models')
        seen_models = [save_model(bot, model) for model in models]
        if len(seen_models) != len(set(seen_models)):
            raise ValidationError('Duplicate conversation')
        # Models may be discovered while the editor is open; omissions never delete them.
    if provider.channels.exclude(pk__in=seen_channels).exists():
        raise ValidationError('Existing channels cannot be silently removed; disable them instead')
    AuditLog.objects.create(actor=request.user.username, action='provider.update' if pk else 'provider.create', target=str(provider.pk))
    return provider


class Providers(ManagementView):
    def get(self, request, pk=None):
        providers = Provider.objects.prefetch_related('channels__bots__conversations').order_by('pk')
        if pk is not None:
            data = provider_data(get_object_or_404(providers, pk=pk), request.user)
            if request.user.role != 'Owner' and not data['channels']:
                return Response(status=404)
            return Response(data)
        result = [provider_data(provider, request.user) for provider in providers]
        return Response([item for item in result if request.user.role == 'Owner' or item['channels']])

    def post(self, request, pk=None):
        if pk is not None:
            return Response(status=405)
        return self.save(request, None)

    def patch(self, request, pk=None):
        if pk is None:
            return Response(status=405)
        return self.save(request, pk)

    def save(self, request, pk):
        owner(request)
        try:
            provider = save_provider(request, pk)
        except IntegrityError:
            raise ValidationError('Provider/channel name or AppID already exists') from None
        return Response(provider_data(provider, request.user), status=200 if pk else 201)


class SyncConversations(ManagementView):
    @transaction.atomic
    def post(self, request, pk):
        owner(request)
        fields(request.data, [])
        channel = get_object_or_404(Channel, pk=pk)
        bot = get_object_or_404(Bot.objects.select_for_update(), channel=channel)
        before = bot.conversations.count()
        for event in Event.objects.filter(bot=bot).order_by('pk').iterator():
            discover(bot, event.payload)
        AuditLog.objects.create(actor=request.user.username, action='conversation.backfill', target=str(channel.pk))
        return Response({'source': 'historical_events', 'created': bot.conversations.count() - before,
                         'upstream_enumeration_supported': False, 'realtime_discovery': True,
                         'models': [conversation_data(row) for row in bot.conversations.order_by('pk')]})


class UpstreamInterfaces(ManagementView):
    def get(self, request):
        from .services import SCOPES
        return Response([asdict(interface) for interface in INTERFACES])


class ScopeCatalog(ManagementView):
    def get(self, request):
        from .services import SCOPES
        return Response(sorted(SCOPES))


class CopyToken(ManagementView):
    def post(self, request, pk):
        from .models import ApiKey
        from .services import authorize
        key = get_object_or_404(ApiKey, pk=pk, user=request.user, revoked_at__isnull=True)
        if not key.token:
            return Response({'detail': 'Original token was not stored and cannot be recovered from its digest'}, status=409,
                            headers={'Cache-Control': 'no-store'})
        authorize(key.token)
        AuditLog.objects.create(actor=request.user.username, action='key.copy', target=str(key.pk))
        return Response({'token': key.token}, headers={'Cache-Control': 'no-store'})
