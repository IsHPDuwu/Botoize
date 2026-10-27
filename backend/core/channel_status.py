"""Read-only configured channel and worker snapshots; never probe QQ."""
from django.utils import timezone
from .models import ApiCallAudit, GatewaySession, OneBotUpstreamSession


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
        lease_live = bool(session and session.lease_token and session.lease_until and session.lease_until > now)
        calls = ApiCallAudit.objects.filter(bot=bot)
        if user.role != 'Owner':
            calls = calls.filter(user=user)
        latest = calls.order_by('-pk').first()
        rows.append({'bot': bot.pk, 'name': bot.name, 'channel': bot.channel_id,
                     'channel_name': bot.channel.name, 'provider_name': bot.channel.provider.name,
                     'interface_type': bot.channel.interface_type, 'enabled': bot.is_active,
                     'worker_lease_live': lease_live, 'session_recorded': bool(session and (session.connected if native else session.session_id)),
                     'upstream_connected': bool(native and lease_live and session.connected),
                     'lease_until': session.lease_until if lease_live else None,
                     'last_call_at': latest.created_at if latest else None,
                     'last_http_status': latest.status_code if latest else None})
    return rows
