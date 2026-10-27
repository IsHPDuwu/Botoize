"""Configured connection snapshots and queued Owner reconnect controls; never probe in status reads."""
from django.utils import timezone
from .models import ApiCallAudit, GatewaySession, OneBotUpstreamSession, ChannelConnectionRequest


def channel_status(bots, *, user):
    now = timezone.now()
    rows = []
    for bot in bots.select_related('channel__provider').order_by('pk'):
        from .upstreams import onebot_version
        native = bool(onebot_version(bot))
        session = (OneBotUpstreamSession if native else GatewaySession).objects.filter(bot=bot).first()
        if native and session:
            from .onebot_upstream import configuration_digest
            if session.credential_digest != configuration_digest(bot):
                session = None
        elif session:
            from .gateway import credential_digest
            if session.credential_digest != credential_digest(bot):
                session = None
        lease_live = bool(session and session.lease_token and session.lease_until and session.lease_until > now)
        control = ChannelConnectionRequest.objects.filter(channel=bot.channel).first()
        from .onebot_upstream import configuration_digest
        if control and control.configuration != configuration_digest(bot):
            control = None
        pending = bool(control and control.generation > control.processed_generation)
        connected = bool(lease_live and session.connected)
        state = ('disabled' if not bot.is_active else 'reconnect_pending' if pending else
                 'webhook' if bot.channel.interface_type == 'qq_official_webhook' else
                 'connected' if connected else 'connecting' if lease_live else 'disconnected')
        calls = ApiCallAudit.objects.filter(bot=bot)
        if user.role != 'Owner':
            calls = calls.filter(user=user)
        latest = calls.order_by('-pk').first()
        rows.append({'bot': bot.pk, 'name': bot.name, 'channel': bot.channel_id,
                     'channel_name': bot.channel.name, 'provider_name': bot.channel.provider.name,
                     'interface_type': bot.channel.interface_type, 'enabled': bot.is_active,
                     'worker_lease_live': lease_live, 'session_recorded': bool(session and (session.connected if native else session.session_id)),
                     'upstream_connected': connected,
                     'connection_state': state,
                     'reconnect_requested_at': control.requested_at if control else None,
                     'reconnect_processed_at': control.processed_at if control else None,
                     'last_check_at': control.checked_at if control else None,
                     'last_check_ok': control.reachable if control else None,
                     'connection_error': control.error_code if control else '',
                     'lease_until': session.lease_until if lease_live else None,
                     'last_call_at': latest.created_at if latest else None,
                     'last_http_status': latest.status_code if latest else None})
    return rows


from .views import ManagementView, owner, fields


class ChannelConnections(ManagementView):
    def get(self, request, pk=None):
        from rest_framework.response import Response
        from .models import Bot
        from .conversations import active_grants
        if pk is not None:
            return Response(status=405)
        bots = Bot.objects.all()
        if request.user.role != 'Owner':
            bots = bots.filter(pk__in=[grant.bot_id for grant in active_grants(request.user)])
        return Response(channel_status(bots, user=request.user), headers={'Cache-Control': 'no-store'})

    def post(self, request, pk=None):
        from django.db import transaction
        from django.db.models import F
        from django.shortcuts import get_object_or_404
        from rest_framework.exceptions import ValidationError
        from rest_framework.response import Response
        from .models import Bot, AuditLog
        from .onebot_upstream import configuration_digest
        owner(request)
        if pk is None:
            return Response(status=405)
        fields(request.data, [])
        with transaction.atomic():
            bot = get_object_or_404(Bot.objects.select_for_update().select_related('channel'), channel_id=pk)
            if not bot.is_active:
                raise ValidationError('Enable this Channel before reconnecting')
            row, _ = ChannelConnectionRequest.objects.get_or_create(channel=bot.channel)
            # Repeated clicks share the outstanding request; do not create reconnect storms.
            digest = configuration_digest(bot)
            if row.generation == row.processed_generation or row.configuration != digest:
                ChannelConnectionRequest.objects.filter(pk=row.pk).update(generation=F('generation') + 1,
                    requested_at=timezone.now(), error_code='', configuration=digest)
            AuditLog.objects.create(actor=request.user.username, action='channel.reconnect', target=str(pk))
        return Response({'state': 'queued', 'channel': pk,
            'detail': 'Connection worker will check webhook HTTP access' if bot.channel.interface_type == 'qq_official_webhook'
                      else 'Connection worker will reconnect this Channel'}, status=202, headers={'Cache-Control':'no-store'})
