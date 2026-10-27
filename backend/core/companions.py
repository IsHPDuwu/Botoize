"""Primary-only sending, durable companion reception and evidence-based group/ID matching."""
import copy
import hashlib
import json
import re
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import (Bot, Channel, ChannelGroupMatch, CompanionObservation, Conversation,
                     Event, OneBotMessage)
from .onebot_ids import learn_real_id, original_for_real
from .onebot_upstream import configuration_digest
from .upstreams import onebot_version

GRACE_SECONDS = 2
MATCH_SECONDS = 10


def lock_cooperation():
    from .models import OwnerLock
    from django.db.models import F
    OwnerLock.objects.get_or_create(pk=1)
    OwnerLock.objects.filter(pk=1).update(revision=F('revision') + 1)


def companion_bot(channel):
    if not channel.companion_id:
        return None
    return Bot.objects.select_related('channel').filter(channel_id=channel.companion_id, is_active=True,
        channel__interface_type__in=['onebot_v11', 'onebot_v12']).first()


def pairing_digest(channel):
    master = channel.bots.first()
    slave = channel.companion.bots.first() if channel.companion_id else None
    decisions = list(channel.group_matches.filter(companion_id=channel.companion_id, origin='manual')
                     .order_by('pk').values_list('primary_group', 'companion_group', 'enabled'))
    return hashlib.sha256((str(channel.companion_id) + ':' + (configuration_digest(master) if master else '')
        + ':' + (configuration_digest(slave) if slave else '') + ':' + json.dumps(decisions)).encode()).hexdigest()


def shadow_user(bot, real):
    original = original_for_real(bot, 'user', real)
    if original:
        return original
    original = 'companion_' + hashlib.sha256(str(real).encode()).hexdigest()[:40]
    learn_real_id(bot, 'user', original, str(real))
    return original


def matches_data(channel):
    return list(channel.group_matches.filter(companion_id=channel.companion_id).order_by('pk').values(
        'id', 'primary_group', 'companion_group', 'name', 'origin', 'enabled')) if channel.companion_id else []


def add_match(channel, primary_group, remote_group, name='', origin='message'):
    """An existing/manual/disabled decision always wins over automatic evidence."""
    if not channel.companion_id:
        return None
    rows = channel.group_matches.filter(companion_id=channel.companion_id)
    primary = rows.filter(primary_group=primary_group).first()
    remote = rows.filter(companion_group=remote_group).first()
    if primary or remote:
        row = primary or remote
        return row if row.enabled and row.primary_group == primary_group and row.companion_group == remote_group else None
    row = ChannelGroupMatch.objects.create(channel=channel, companion_id=channel.companion_id,
        primary_group=primary_group, companion_group=remote_group, name=name[:120], origin=origin)
    master = channel.bots.first()
    learn_real_id(master, 'group', primary_group, remote_group)
    Conversation.objects.get_or_create(bot=master, is_direct=False, target_id=primary_group, defaults={'name': name[:120]})
    return row


def match_names(channel):
    master, slave = channel.bots.first(), companion_bot(channel)
    if not master or not slave:
        return 0
    def names(bot):
        result = {}
        for target, name in bot.conversations.filter(is_direct=False).exclude(name='').values_list('target_id', 'name'):
            result.setdefault(name, []).append(target)
        return result
    left, right, count = names(master), names(slave), 0
    for name in left.keys() & right.keys():
        if len(left[name]) == len(right[name]) == 1:
            before = channel.group_matches.count()
            add_match(channel, left[name][0], right[name][0], name, 'name')
            count += channel.group_matches.count() - before
    return count


def fingerprint(row):
    if row is None or row.conversation_type != 'group' or not row.incoming:
        return ''
    text = ''.join(s.get('data', {}).get('text', '') for s in row.segments if s.get('type') == 'text')
    text = re.sub(r'<@!?[A-Za-z0-9_-]+>', '', text).strip()
    if not text:
        return ''  # Do not infer equality from two unidentifiable images/empty messages.
    kinds = sorted(s['type'] for s in row.segments if s['type'] not in {'text', 'mention', 'mention_all', 'reply'})
    return hashlib.sha256(json.dumps([text, kinds], ensure_ascii=False).encode()).hexdigest()


def message_for(event):
    # Ingestion saved the source record before invoking cooperation.
    return OneBotMessage.objects.filter(source_event=event).first()


def observe(event, channel, side):
    row = message_for(event)
    if row is None or row.conversation_type != 'group' or not row.incoming:
        return None
    name = event.payload.get('d', {}).get('event', event.payload.get('d', {})).get('group_name')
    if isinstance(name, str) and name.strip() and len(name) <= 120:
        Conversation.objects.filter(bot=event.bot, is_direct=False, target_id=row.target_id).update(name=name)
    from .events import grant_snapshot
    result, _ = CompanionObservation.objects.get_or_create(channel=channel, event=event, side=side, defaults={
        'group_id': row.target_id, 'sender_id': row.sender_id, 'fingerprint': fingerprint(row),
        'sent_at': row.sent_at, 'configuration': pairing_digest(channel),
        'grant_snapshot': grant_snapshot(event) if side == 'primary' else [],
        'due_at': timezone.now() + timedelta(seconds=GRACE_SECONDS) if side == 'primary' else None})
    return result


def counterpart(observation):
    if not observation.fingerprint:
        return None
    rows = CompanionObservation.objects.filter(channel=observation.channel,
        configuration=observation.configuration, fingerprint=observation.fingerprint, paired=False,
        side='companion' if observation.side == 'primary' else 'primary',
        sent_at__gte=observation.sent_at-MATCH_SECONDS, sent_at__lte=observation.sent_at+MATCH_SECONDS)
    mapping = observation.channel.group_matches.filter(companion_id=observation.channel.companion_id, enabled=True)
    field = 'primary_group' if observation.side == 'primary' else 'companion_group'
    match = mapping.filter(**{field: observation.group_id}).first()
    if match:
        rows = rows.filter(group_id=match.companion_group if observation.side == 'primary' else match.primary_group)
    candidates = list(rows.order_by('pk')[:2])
    if len(candidates) != 1:
        return None
    other = candidates[0]
    # Both sides must be unambiguous within the matching window.
    peers = CompanionObservation.objects.filter(channel=observation.channel, configuration=observation.configuration,
        side=observation.side, fingerprint=observation.fingerprint, paired=False,
        sent_at__gte=other.sent_at-MATCH_SECONDS, sent_at__lte=other.sent_at+MATCH_SECONDS)
    if match:
        peers = peers.filter(group_id=observation.group_id)
    return other if peers.count() == 1 else None


def bridge_payload(master, slave_event, group, primary_event=None):
    slave = slave_event.bot
    row = message_for(slave_event)
    primary_row = message_for(primary_event) if primary_event else None
    mid = primary_row.message_id if primary_row else 'companion_' + hashlib.sha256(slave_event.event_id.encode()).hexdigest()[:40]
    sender = primary_row.sender_id if primary_row else shadow_user(master, row.sender_id)
    learn_real_id(master, 'message', mid, row.message_id)
    segments = copy.deepcopy(row.segments)
    for segment in segments:
        if segment['type'] == 'mention':
            segment['data']['user_id'] = shadow_user(master, str(segment['data']['user_id']))
        elif segment['type'] == 'reply':
            real = str(segment['data']['message_id'])
            original = original_for_real(master, 'message', real)
            if original is None:
                original = 'companion_' + hashlib.sha256(('reply:' + real).encode()).hexdigest()[:40]
                learn_real_id(master, 'message', original, real)
            segment['data']['message_id'] = original
    return {'op': 0, 'id': 'companion:' + hashlib.sha256((str(master.pk)+':'+slave_event.event_id).encode()).hexdigest(),
        't': 'COMPANION_MESSAGE_CREATE', 'd': {'group_openid': group, 'sender_id': sender, 'message_id': mid,
        'time': row.sent_at, 'segments': segments, 'source_bot': slave.pk,
        'source_digest': configuration_digest(slave), 'pairing_digest': pairing_digest(master.channel),
        'primary_message_id': primary_row.message_id if primary_row else '',
        'reference': primary_row.reference if primary_row else '',
        'source_event': slave_event.pk,
        'nickname': slave_event.payload.get('d', {}).get('event', {}).get('sender', {}).get('nickname', '')}}


def remember_bridge(bot, payload):
    data = payload['d']
    values = {
            'is_direct': False, 'target_id': data['group_openid'], 'sender_id': data['sender_id'],
            'segments': data['segments'], 'sent_at': data['time'], 'incoming': True, 'conversation_type': 'group',
            'attachment_bot_id': data['source_bot'], 'attachment_digest': data['source_digest'],
            'primary_message_id': data.get('primary_message_id', ''), 'reference': data.get('reference', ''),
        }
    values['source_event'] = Event.objects.get(bot=bot, event_id=payload['id'])
    row, created = OneBotMessage.objects.get_or_create(bot=bot, source_digest='' if not onebot_version(bot) else configuration_digest(bot),
        message_id=data['message_id'], defaults=values)
    if not created and row.source_event_id != values['source_event'].pk:
        for field, value in values.items():
            setattr(row, field, value)
        row.save()
    return row


def publish_observation(observation, *, slave=None, primary=None):
    from .events import publish_event, ingest_event
    if observation.published:
        return observation.output
    channel = observation.channel
    master = channel.bots.first()
    if not master or not master.is_active or pairing_digest(channel) != observation.configuration:
        # A stored native primary event remains deliverable even after a pairing setting changed.
        if observation.side == 'primary':
            publish_event(observation.event, snapshot=observation.grant_snapshot)
            observation.output = observation.event
        observation.published = True
        observation.save(update_fields=['published', 'output'])
        return observation.output
    if slave is not None:
        mapping = channel.group_matches.filter(companion_id=channel.companion_id,
            companion_group=slave.group_id, enabled=True).first()
        if mapping is None:
            return None
        payload = bridge_payload(master, slave.event, mapping.primary_group, primary.event if primary else None)
        output, _ = ingest_event(master, payload, cooperate=False,
            snapshot=primary.grant_snapshot if primary is not None else None)
    else:
        output = observation.event
        publish_event(output, snapshot=observation.grant_snapshot if observation.side == 'primary' else None)
    observation.output, observation.published = output, True
    observation.save(update_fields=['output', 'published'])
    return output


def reconcile(observation):
    if observation.configuration != pairing_digest(observation.channel):
        return False
    other = counterpart(observation)
    if other is None:
        return False
    primary, slave = (observation, other) if observation.side == 'primary' else (other, observation)
    channel, master = primary.channel, primary.channel.bots.first()
    mapping = add_match(channel, primary.group_id, slave.group_id,
        master.conversations.filter(is_direct=False, target_id=primary.group_id).values_list('name', flat=True).first() or '')
    if mapping is None:
        return False
    learn_real_id(master, 'group', primary.group_id, slave.group_id)
    learn_real_id(master, 'user', primary.sender_id, slave.sender_id)
    p_row, s_row = message_for(primary.event), message_for(slave.event)
    learn_real_id(master, 'message', p_row.message_id, s_row.message_id)
    # Learn mentions only when order/count on the same verified message agrees.
    left = [s['data']['user_id'] for s in p_row.segments if s['type'] == 'mention']
    right = [s['data']['user_id'] for s in s_row.segments if s['type'] == 'mention']
    if len(left) == len(right):
        for original, real in zip(left, right):
            learn_real_id(master, 'user', original, real)
    primary.refresh_from_db(); slave.refresh_from_db()
    if slave.published and slave.output_id:
        output = slave.output
        # Late primary supplies a passive reply context without emitting a second event.
        OneBotMessage.objects.filter(source_event=output).update(primary_message_id=p_row.message_id,
            reference=p_row.reference, sender_id=primary.sender_id)
        bridged = OneBotMessage.objects.filter(source_event=output, attachment_bot__isnull=False).first()
        p_row.source_event = output
        if bridged:
            p_row.segments = bridged.segments
            p_row.attachment_bot_id, p_row.attachment_digest = bridged.attachment_bot_id, bridged.attachment_digest
            p_row.primary_message_id = p_row.message_id
        p_row.save()
    elif primary.published:
        output = primary.output
    else:
        output = publish_observation(primary, slave=slave, primary=primary)
    for row in (primary, slave):
        row.paired, row.published, row.output = True, True, output
        row.save(update_fields=['paired', 'published', 'output'])
    return True


def handle_event(event):
    """Return whether this source event should publish on its own Bot immediately."""
    channel = event.bot.channel
    own = observe(event, channel, 'primary') if channel.companion_id else None
    if own:
        match_names(channel)
        if not reconcile(own):
            # Durable short grace; every consumer and the maintenance worker flushes due events.
            if companion_bot(channel) is None:
                publish_observation(own)
    for primary_channel in Channel.objects.filter(companion=channel).select_related('companion'):
        if not primary_channel.bots.filter(is_active=True).exists():
            continue
        observed = observe(event, primary_channel, 'companion')
        if observed is None:
            continue
        match_names(primary_channel)
        if reconcile(observed):
            continue
        if primary_channel.group_matches.filter(companion=channel, companion_group=observed.group_id, enabled=True).exists():
            publish_observation(observed, slave=observed)
    return own is None


@transaction.atomic
def flush_due(channel_id=None, limit=100):
    rows = CompanionObservation.objects.filter(side='primary', published=False, due_at__lte=timezone.now())
    if channel_id is not None:
        rows = rows.filter(channel_id=channel_id)
    if not rows.exists():
        return 0
    lock_cooperation()
    # Lock order shared with ingestion: serialize cooperative dispatch across all involved Bots.
    ids = sorted(set(rows.values_list('event__bot_id', flat=True)))
    list(Bot.objects.select_for_update().filter(pk__in=ids).order_by('pk'))
    count = 0
    for row in rows.select_for_update().select_related('channel__companion', 'event__bot').order_by('pk')[:limit]:
        if not reconcile(row):
            publish_observation(row)
        count += 1
    return count


def bridge_visible(bot, payload):
    if payload.get('t') != 'COMPANION_MESSAGE_CREATE':
        return True
    # Already accepted primary history remains available if a slave disconnects. A setting change hides old paired history.
    return payload['d'].get('pairing_digest') == pairing_digest(bot.channel)


def backfill_id_evidence(channel, limit=200):
    """Bounded, resumable scan of verified history; never replay old messages."""
    from django.db.models import Exists, OuterRef
    from .models import EventOutbox
    master, slave = channel.bots.first(), companion_bot(channel)
    if not master or not slave:
        return 0
    count, added = 0, []
    with transaction.atomic():
        lock_cooperation()
        for bot, side in ((master, 'primary'), (slave, 'companion')):
            observed = CompanionObservation.objects.filter(channel=channel, event_id=OuterRef('pk'), side=side)
            messages = OneBotMessage.objects.filter(source_event_id=OuterRef('pk'), incoming=True, conversation_type='group')
            rows = Event.objects.filter(bot=bot).exclude(event_type='COMPANION_MESSAGE_CREATE').annotate(
                seen=Exists(observed), message_exists=Exists(messages)).filter(seen=False, message_exists=True).order_by('pk')[:limit]
            for event in rows:
                observation = observe(event, channel, side)
                if observation is None:
                    continue
                if side == 'primary':
                    # Old events belong to their original authorization snapshot, including no recipients.
                    observation.published = True
                    observation.output = event if EventOutbox.objects.filter(event=event).exists() else None
                    observation.save(update_fields=['published', 'output'])
                count += 1
                added.append(observation.pk)
        for observation in CompanionObservation.objects.filter(pk__in=added, paired=False):
            reconcile(observation)
    return count


def refresh_pairing(channel):
    """Read-only upstream discovery, explicitly requested by Owner/maintenance worker."""
    from .onebot_upstream import call, identity, native_id
    from .official import _request
    from .onebot import official_json
    master, slave = channel.bots.first(), companion_bot(channel)
    if not master or not slave:
        raise ValueError('An active OneBot companion is required')
    digest = pairing_digest(channel)
    own, _ = identity(slave)
    groups = call(slave, 'get_group_list', self_info=own)
    if not isinstance(groups, list) or len(groups) > 10000:
        raise ValueError('Invalid companion group list')
    master_groups = list(master.conversations.filter(is_direct=False).values_list('target_id', flat=True))
    named = []
    for group in master_groups[:200]:
        try:
            info = (call(master, 'get_group_info', {'group_id': native_id(group, onebot_version(master))}, self_info=identity(master)[0])
                    if onebot_version(master) else official_json(_request(master, 'GET', f'v2/groups/{group}/info')))
            if isinstance(info, dict) and isinstance(info.get('group_name'), str) and 1 <= len(info['group_name']) <= 120:
                named.append((group, info['group_name']))
        except Exception:
            continue
    with transaction.atomic():
        lock_cooperation()
        list(Bot.objects.select_for_update().filter(pk__in=sorted([master.pk, slave.pk])).order_by('pk'))
        channel.refresh_from_db()
        if pairing_digest(channel) != digest:
            raise ValueError('Pairing configuration changed')
        for row in groups:
            if not isinstance(row, dict):
                continue
            group = str(native_id(row.get('group_id'), onebot_version(slave)))
            name = row.get('group_name', '')
            if isinstance(name, str) and len(name) <= 120:
                Conversation.objects.update_or_create(bot=slave, is_direct=False, target_id=group, defaults={'name': name})
        for group, name in named:
            Conversation.objects.filter(bot=master, is_direct=False, target_id=group).update(name=name)
        created = match_names(channel)
        # Reconcile historical/unpaired observations too: outages don't discard identity evidence.
        for observation in CompanionObservation.objects.filter(channel=channel, paired=False, configuration=digest).order_by('pk')[:1000]:
            reconcile(observation)
    scanned = backfill_id_evidence(channel)
    return {'created': created, 'matches': matches_data(channel), 'master_groups_checked': len(named),
            'companion_groups': len(groups), 'history_scanned': scanned}
