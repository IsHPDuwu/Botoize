"""Learn the official bot's QQ account from its own sends, never the companion's self."""
from django.db import transaction
from django.db.models import Q

from .models import OneBotMessage
from .onebot_ids import learn_real_id, original_for_real, real_for_original
from .upstreams import onebot_version


@transaction.atomic
def learn_from_companion(master, remote):
    from .companions import companion_bot, fingerprint, lock_cooperation, MATCH_SECONDS
    from .onebot_upstream import configuration_digest
    own = master.channel.onebot_self_id
    if onebot_version(master) or not own or remote is None or not remote.sender_id:
        return False
    slave = companion_bot(master.channel)
    if (slave is None or remote.bot_id != slave.pk or not remote.incoming
            or remote.source_digest != configuration_digest(slave)
            or remote.conversation_type != 'group'):
        return False
    match = master.channel.group_matches.filter(companion_id=slave.channel_id,
        companion_group=remote.target_id, enabled=True).first()
    if match is None:
        return False
    lock_cooperation()
    sent = OneBotMessage.objects.filter(bot=master, source_digest='', incoming=False,
        conversation_type='group', target_id=match.primary_group).filter(Q(sender_id='') | Q(sender_id=own))
    # An already verified message mapping is stronger evidence than text/time.
    original = original_for_real(master, 'message', remote.message_id)
    target = sent.filter(message_id=original).first() if original else None
    if target is None:
        signature = fingerprint(remote)
        if not signature:
            return False
        candidates = [row for row in sent.filter(
            sent_at__gte=remote.sent_at-MATCH_SECONDS, sent_at__lte=remote.sent_at+MATCH_SECONDS)
            if fingerprint(row, include_sent=True) == signature]
        if len(candidates) != 1:
            return False
        target = candidates[0]
        peers = OneBotMessage.objects.filter(bot=slave, source_digest=remote.source_digest,
            incoming=True, conversation_type='group', target_id=remote.target_id,
            sent_at__gte=target.sent_at-MATCH_SECONDS, sent_at__lte=target.sent_at+MATCH_SECONDS)
        if sum(fingerprint(row) == signature for row in peers) != 1:
            return False
    known_self = real_for_original(master, 'user', own)
    if known_self and known_self != remote.sender_id:
        return False
    existing = original_for_real(master, 'user', remote.sender_id)
    if existing and existing != own and not existing.startswith('companion_'):
        return False
    if not learn_real_id(master, 'message', target.message_id, remote.message_id):
        return False
    if not learn_real_id(master, 'user', own, remote.sender_id):
        return False
    OneBotMessage.objects.filter(bot=master, source_digest='', incoming=False, sender_id='').update(sender_id=own)
    return True


def repair_self_identity(master, limit=200):
    """Bounded local history repair; no QQ calls or event replay."""
    from .companions import companion_bot
    from .onebot_upstream import configuration_digest
    own = master.channel.onebot_self_id
    if onebot_version(master) or not own or real_for_original(master, 'user', own):
        return False
    slave = companion_bot(master.channel)
    if slave is None:
        return False
    matches = master.channel.group_matches.filter(companion_id=slave.channel_id, enabled=True)
    sent = OneBotMessage.objects.filter(bot=master, source_digest='', incoming=False,
        conversation_type='group', target_id__in=matches.values('primary_group'))
    from .companions import MATCH_SECONDS
    for target in sent.order_by('-pk')[:limit]:
        match = matches.get(primary_group=target.target_id)
        real = real_for_original(master, 'message', target.message_id)
        rows = OneBotMessage.objects.filter(bot=slave, source_digest=configuration_digest(slave),
            incoming=True, conversation_type='group', target_id=match.companion_group)
        if real is not None:
            rows = rows.filter(message_id=real)
        else:
            rows = rows.filter(sent_at__gte=target.sent_at-MATCH_SECONDS,
                               sent_at__lte=target.sent_at+MATCH_SECONDS)
        for row in rows:
            if learn_from_companion(master, row):
                return True
    return False
