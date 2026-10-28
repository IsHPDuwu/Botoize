"""Verified quote correspondence and grant-bound historical message lookup."""
import copy
from rest_framework.exceptions import PermissionDenied

from .models import OneBotMessage
from .onebot_common import OneBotError, message_identifier
from .onebot_ids import (bind_message_alias, canonical_id, learn_real_id,
                         original_for_real, real_for_original)


def register_reference(row):
    if not row.reference or row.reference == row.message_id:
        return
    message_identifier(row.reference)
    # Conflicting/reused indexes never redirect an established message.
    conflict = OneBotMessage.objects.filter(bot=row.bot, source_digest=row.source_digest,
        reference=row.reference, context_event__isnull=True).exclude(pk=row.pk).exclude(
            message_id=row.reference).exclude(message_id__startswith='companion_').exists()
    current = canonical_id(row.bot, 'message', row.reference)
    if not conflict and current in (row.reference, row.message_id):
        bind_message_alias(row.bot, row.reference, row.message_id)


def learn_quotes(master, primary, companion, primary_event=None):
    segments = primary.segments
    if primary_event is not None:
        from .onebot_events import parsed_message
        parsed = parsed_message(primary_event.payload)
        if parsed:
            segments = parsed[5]  # Immutable raw reference, even after bridge segment upgrades.
    left = [s['data']['message_id'] for s in segments if s['type'] == 'reply']
    right = [s['data']['message_id'] for s in companion.segments if s['type'] == 'reply']
    if len(left) != 1 or len(right) != 1:
        return
    reference, real = left[0], right[0]
    target = OneBotMessage.objects.filter(bot=master, source_digest=primary.source_digest,
        reference=reference, target_id=primary.target_id, conversation_type='group',
        context_event__isnull=True).exclude(message_id__startswith='companion_').first()
    original = target.message_id if target else canonical_id(master, 'message', reference)
    established = OneBotMessage.objects.filter(bot=master, source_digest=primary.source_digest,
        message_id=original).first()
    if established and (established.target_id != primary.target_id or established.conversation_type != 'group'):
        return
    # Only paired messages in a verified matched group provide this evidence.
    previous = original_for_real(master, 'message', real)
    if previous and not previous.startswith('companion_') and previous != original:
        if target is not None:
            return
        known = OneBotMessage.objects.filter(bot=master, source_digest=primary.source_digest,
            message_id=previous, target_id=primary.target_id, conversation_type='group').first()
        if known is None or known.reference not in ('', reference):
            return
        if not known.reference:
            known.reference = reference
            known.save(update_fields=['reference'])
        if not bind_message_alias(master, reference, known.message_id):
            return
        original = known.message_id
    if previous and previous.startswith('companion_'):
        OneBotMessage.objects.filter(bot=master, message_id=previous, target_id=primary.target_id,
            attachment_bot__isnull=False, reference='').update(reference=reference)
    learn_real_id(master, 'message', original, real)
    if target:
        register_reference(target)
    # A companion-only cached target gains its official reference when the quote arrives.
    OneBotMessage.objects.filter(bot=master, message_id=original, target_id=primary.target_id,
        attachment_bot__isnull=False).filter(reference='').update(reference=reference)


def bridge_segments(master, segments):
    from .companions import shadow_user
    import hashlib
    result = copy.deepcopy(segments)
    for segment in result:
        if segment['type'] == 'mention':
            segment['data']['user_id'] = shadow_user(master, str(segment['data']['user_id']))
        elif segment['type'] == 'reply':
            real = str(segment['data']['message_id'])
            original = original_for_real(master, 'message', real)
            if original is None:
                original = 'companion_' + hashlib.sha256(('reply:' + real).encode()).hexdigest()[:40]
                learn_real_id(master, 'message', original, real)
            segment['data'] = {'message_id': original}
    return result


def quoted_history(bot, key, mid, *, lookup=False):
    """Fetch only a target explicitly referenced by a currently visible group event.

    No unrestricted upstream get_msg proxy. The quote supplies both conversation and
    authorization evidence; a returned message must independently confirm that group.
    """
    from .companions import companion_bot
    from .onebot import check_message_access
    from .onebot_upstream import configuration_digest, call, native_id
    from .onebot_upstream_events import canonical_message
    from .upstreams import onebot_version
    slave = companion_bot(bot.channel)
    initial_pairing = None
    if slave:
        from .companions import pairing_digest
        initial_pairing = pairing_digest(bot.channel)
    real = real_for_original(bot, 'message', mid)
    if not slave or real is None:
        return None
    for anchor in OneBotMessage.objects.filter(bot=bot, source_digest='', incoming=True,
            conversation_type='group', source_event__isnull=False).order_by('-pk')[:1000]:
        if not any(s['type'] == 'reply' and canonical_id(bot, 'message', s['data']['message_id']) == mid
                   for s in anchor.segments):
            continue
        try:
            if key is not None:
                from .companion_actions import current_authority
                key = current_authority(key, None if lookup else 'events:read')
            check_message_access(bot, key, anchor, lookup=lookup)
        except (OneBotError, PermissionDenied):
            continue
        match = bot.channel.group_matches.filter(companion_id=slave.channel_id,
            primary_group=anchor.target_id, enabled=True).first()
        if match is None:
            continue
        digest = configuration_digest(slave)
        row = OneBotMessage.objects.filter(bot=slave, source_digest=digest, message_id=real,
            target_id=match.companion_group, conversation_type='group').first()
        if row is None and onebot_version(slave) == 11:
            data = call(slave, 'get_msg', {'message_id': native_id(real, 11, kind='message')})
            if (not isinstance(data, dict) or str(data.get('message_id')) != real
                    or data.get('message_type') != 'group'
                    or str(data.get('group_id')) != match.companion_group):
                raise OneBotError(35004, 'Companion quoted message conversation mismatch')
            # Reuse the strict event segment parser without publishing or fabricating an event.
            from .onebot_upstream_events import normalize_event
            event = {**data, 'self_id': int(slave.app_id), 'post_type': 'message',
                'user_id': data.get('sender', {}).get('user_id')}
            payload = normalize_event(slave, event)
            row = canonical_message(slave, payload)
        if row is None:
            continue  # OB12 has no standard historical-message action; use received history.
        from .companions import shadow_user, pairing_digest
        channel = type(bot.channel).objects.select_related('companion').get(pk=bot.channel_id)
        fresh_slave = type(slave).objects.select_related('channel').get(pk=slave.pk)
        if (pairing_digest(channel) != initial_pairing
                or not fresh_slave.is_active or configuration_digest(fresh_slave) != digest):
            raise OneBotError(35003, 'Companion configuration changed')
        if key is not None:
            key = current_authority(key, None if lookup else 'events:read')
        check_message_access(bot, key, anchor, lookup=lookup)
        # QQ quoted indexes are sendable references, never passive-reply msg_id values.
        reference = mid if not mid.startswith('companion_') else ''
        return OneBotMessage.objects.get_or_create(bot=bot, source_digest='', message_id=mid, defaults={
            'is_direct': False, 'target_id': anchor.target_id, 'sender_id': shadow_user(bot, row.sender_id),
            'segments': bridge_segments(bot, row.segments), 'sent_at': row.sent_at, 'incoming': True,
            'conversation_type': 'group', 'reference': reference, 'context_event': anchor.source_event,
            'context_pairing': initial_pairing,
            'attachment_bot': slave, 'attachment_digest': digest,
        })[0]
    return None
