"""Opt-in, bidirectional @/recall identity evidence; never replay uncertain sends."""
import json
import re
import time
from datetime import timedelta

from django.db import close_old_connections, connection, transaction
from django.utils import timezone

from .models import Bot, IdentityProbe
from .onebot_common import OneBotError, identifier, message_identifier
from .onebot_ids import canonical_id, learn_real_id, real_for_original
from .upstreams import onebot_version

MARKER = re.compile(r'botoize-id:([0-9a-f]{32})')
LIVE_SECONDS = 60


def context(bot, group):
    from .companions import companion_bot, pairing_digest
    if not bot.is_active or onebot_version(bot) or not bot.channel.identity_probe_enabled:
        return None
    slave = companion_bot(bot.channel)
    if slave is None:
        return None
    match = bot.channel.group_matches.filter(companion_id=slave.channel_id,
        primary_group=group, enabled=True).first()
    return (slave, match, pairing_digest(bot.channel)) if match else None


@transaction.atomic
def request_identity(bot, group, *, original=None, real=None):
    from .companions import lock_cooperation
    from .onebot_upstream import native_id
    available = context(bot, group)
    if available is None:
        return None
    slave, match, digest = available
    if original:
        original = canonical_id(bot, 'user', original)
        known = real_for_original(bot, 'user', original)
        if not original.startswith('companion_') and known:
            return None
        real = known if original.startswith('companion_') else real
    if real is not None:
        real = str(native_id(str(real), onebot_version(slave)))
        from .onebot_ids import original_for_real
        known = original_for_real(bot, 'user', real)
        if known and not known.startswith('companion_'):
            return None
        direction, original = 'companion', ''
    elif original and not original.startswith('companion_'):
        identifier(original)
        direction, real = 'primary', ''
    else:
        return None
    lock_cooperation()
    now = timezone.now()
    rows = IdentityProbe.objects.filter(channel=bot.channel, configuration=digest)
    same = rows.filter(direction=direction, original_user=original or '', real_user=real,
        created_at__gt=now-timedelta(minutes=10)).order_by('-pk').first()
    if same:
        return same  # Coalesce requests and failed attempts; no notification storms.
    if rows.filter(created_at__gt=now-timedelta(minutes=1)).count() >= 5:
        return None
    return IdentityProbe.objects.create(channel=bot.channel, companion=slave.channel,
        configuration=digest, primary_group=group, companion_group=match.companion_group,
        direction=direction, original_user=original or '', real_user=real)


def current_context(row, *, cleanup=False):
    from .companions import pairing_digest
    master = Bot.objects.select_related('channel').filter(channel_id=row.channel_id).first()
    if master is None:
        return None
    if cleanup:
        # Recall belongs to the original emitter, even if the option was disabled.
        slave = Bot.objects.select_related('channel').filter(channel_id=row.companion_id, is_active=True).first()
        if slave is None or pairing_digest(master.channel) != row.configuration:
            return None
        return master, slave
    available = context(master, row.primary_group)
    if available is None:
        return None
    slave, match, digest = available
    if digest != row.configuration or match.companion_group != row.companion_group:
        return None
    return master, slave


def cleanup_probe(row, *, self_info=None):
    from .official import delete_message
    from .onebot import official_json
    from .onebot_upstream import call, identity, native_id
    if not row.cleanup_pending or not row.message_id:
        return
    source = current_context(row, cleanup=True)
    if source is None:
        IdentityProbe.objects.filter(pk=row.pk).update(cleanup_pending=False, error_code='cleanup_configuration_changed')
        return
    master, slave = source
    claimed = IdentityProbe.objects.filter(pk=row.pk, cleanup_pending=True,
        cleanup_attempts=row.cleanup_attempts).update(cleanup_attempts=row.cleanup_attempts+1, updated_at=timezone.now())
    if not claimed:
        return
    try:
        if row.direction == 'primary':
            official_json(delete_message(master, f'v2/groups/{row.primary_group}/messages',
                message_id=row.message_id), empty=True)
        else:
            version = onebot_version(slave)
            own = self_info if self_info is not None else identity(slave)[0]
            call(slave, 'delete_msg' if version == 11 else 'delete_message',
                {'message_id': native_id(row.message_id, version, kind='message')}, self_info=own)
    except Exception:
        IdentityProbe.objects.filter(pk=row.pk).update(error_code='recall_failed')
    else:
        IdentityProbe.objects.filter(pk=row.pk).update(cleanup_pending=False, error_code='')


def process_probe(pk):
    from .companions import lock_cooperation
    from .official import _request
    from .onebot import official_json
    from .onebot_upstream import call, identity, native_id
    with transaction.atomic():
        lock_cooperation()
        row = IdentityProbe.objects.select_for_update().get(pk=pk)
        if row.state != 'queued':
            return
        if row.created_at < timezone.now()-timedelta(seconds=LIVE_SECONDS) or current_context(row) is None:
            row.state = 'cancelled'
            row.save(update_fields=['state', 'updated_at'])
            return
        master, _ = current_context(row)
        from .onebot_ids import original_for_real
        known = (real_for_original(master, 'user', row.original_user) if row.direction == 'primary' else
                 original_for_real(master, 'user', row.real_user))
        if known and (row.direction == 'primary' or not known.startswith('companion_')):
            row.state, row.error_code = 'cancelled', 'already_identified'
            row.save(update_fields=['state', 'error_code', 'updated_at'])
            return
        row.state = 'sending'
        row.save(update_fields=['state', 'updated_at'])
    source = current_context(row)
    if source is None:
        IdentityProbe.objects.filter(pk=pk).update(state='cancelled')
        return
    master, slave = source
    text = 'botoize-id:' + row.marker.hex
    own = None
    try:
        if row.direction == 'primary':
            body = {'markdown': {'content': text + f' <qqbot-at-user id="{identifier(row.original_user)}" />'}, 'msg_type': 2}
            # No normal Markdown -> original fallback: an uncertain probe sends once.
            response = official_json(_request(master, 'POST', f'v2/groups/{row.primary_group}/messages',
                body=json.dumps(body).encode()))
            mid = message_identifier(response.get('id'))
        else:
            version = onebot_version(slave)
            own, _ = identity(slave)
            segments = [{'type': 'text', 'data': {'text': text}},
                {'type': 'at' if version == 11 else 'mention',
                 'data': {'qq' if version == 11 else 'user_id': row.real_user}}]
            params = {'group_id': native_id(row.companion_group, version), 'message': segments}
            if version == 12:
                params['detail_type'] = 'group'
            response = call(slave, 'send_group_msg' if version == 11 else 'send_message', params, self_info=own)
            mid = str(native_id(response.get('message_id'), version, kind='message'))
    except Exception:
        # A timeout can mean it was sent. Persist it and never send it again.
        IdentityProbe.objects.filter(pk=pk).exclude(state='matched').update(state='unknown', error_code='send_unknown')
        return
    IdentityProbe.objects.filter(pk=pk).update(message_id=mid, cleanup_pending=True, updated_at=timezone.now())
    IdentityProbe.objects.filter(pk=pk, state='sending').update(state='waiting')
    row.refresh_from_db()
    cleanup_probe(row, self_info=own)  # Recall is the very next API call after sending.


def consume_probe_event(bot, payload):
    """Return True only for our registered nonce in the expected group/source."""
    from .onebot_events import parsed_message
    if payload.get('t') == 'ONEBOT_EVENT':
        data = payload.get('d', {})
        event = data.get('event', {})
        if data.get('target_type') != 'group' or event.get('post_type', event.get('type')) not in {'message', 'message_sent'}:
            return False
        from .onebot import segments11
        segments = segments11(event['message']) if data['version'] == 11 else event['message']
        if not isinstance(segments, list):
            return False
        segments = [{'type': 'mention', 'data': {'user_id': str(s['data'].get('qq'))}}
            if s.get('type') == 'at' else s for s in segments if isinstance(s, dict) and isinstance(s.get('data'), dict)]
        group = data['target_id']
        side = 'companion'
    else:
        parsed = parsed_message(payload)
        if not parsed or parsed[0] or parsed[6]:
            return False
        group, segments, side = parsed[1], parsed[5], 'primary'
    texts = [s['data'].get('text', '') for s in segments if s['type'] == 'text']
    if any(not isinstance(value, str) for value in texts):
        return False  # Leave malformed messages to the normal strict adapter parser.
    text = ''.join(texts)
    if not text:
        texts = [s['data'].get('content', '') for s in segments if s['type'] in {'markdown', 'qq.markdown'}]
        if any(not isinstance(value, str) for value in texts):
            return False
        text = ''.join(texts)
    marker = MARKER.search(text)
    if marker is None:
        return False
    probes = IdentityProbe.objects.filter(marker=marker[1])
    row = probes.filter(channel=bot.channel, primary_group=group).first() if side == 'primary' else probes.filter(
        companion=bot.channel, companion_group=group).first()
    if row is None:
        return False
    # Recognize late/disabled probes for suppression, but never learn stale evidence.
    if row.state not in {'sending', 'waiting', 'unknown', 'matched'} or row.created_at < timezone.now()-timedelta(seconds=LIVE_SECONDS):
        return True
    source = current_context(row)
    if source is None or side == row.direction:
        return True
    master, slave = source
    if side == 'companion':
        from .onebot_upstream import configuration_digest
        if payload['d'].get('source_digest') != configuration_digest(slave):
            return True
        own = master.channel.onebot_self_id
        expected_sender = real_for_original(master, 'user', own) if own else None
        if expected_sender and str(event.get('user_id')) != expected_sender:
            return True
    else:
        from .onebot_ids import original_for_real
        expected_sender = original_for_real(master, 'user', slave.app_id)
        if expected_sender and parsed[2] != expected_sender:
            return True
    mentions = [s['data']['user_id'] for s in segments if s['type'] == 'mention']
    if len(mentions) != 1:
        return True
    original = mentions[0] if side == 'primary' else row.original_user
    real = row.real_user if side == 'primary' else mentions[0]
    try:
        from .onebot_upstream import native_id
        identifier(original)
        real = str(native_id(real, onebot_version(slave)))
    except (ValueError, TypeError, OneBotError):
        return True
    if original.startswith('companion_'):
        return True
    if learn_real_id(master, 'user', original, real):
        probes.update(state='matched', original_user=original, real_user=real, updated_at=timezone.now())
    return True


def ensure_identity(bot, group, *, original=None, real=None, wait=True):
    """Best effort for a current authorized operation; unresolved segments still skip."""
    try:
        row = request_identity(bot, group, original=original, real=real)
        if row is None or not wait or connection.in_atomic_block:
            return
        process_probe(row.pk)
        deadline = time.monotonic() + 2
        row.refresh_from_db(fields=['state'])
        while row.state in {'queued', 'sending', 'waiting'} and time.monotonic() < deadline:
            time.sleep(0.05)
            row.refresh_from_db(fields=['state'])
    except Exception:
        return  # Optional identification never aborts the user's normal message.


def process_pending():
    close_old_connections()
    try:
        now = timezone.now()
        for pk in IdentityProbe.objects.filter(state='queued').order_by('pk').values_list('pk', flat=True)[:10]:
            process_probe(pk)
        for row in IdentityProbe.objects.filter(cleanup_pending=True, cleanup_attempts__lt=3,
                updated_at__lt=now-timedelta(seconds=15)).order_by('pk')[:10]:
            cleanup_probe(row)
        IdentityProbe.objects.filter(state__in=['sending', 'waiting'],
            created_at__lt=now-timedelta(seconds=LIVE_SECONDS)).update(state='unknown')
    finally:
        close_old_connections()
