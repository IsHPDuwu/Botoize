"""Persistent virtual IDs, not QQ account numbers. Never reverse a hash."""
import hashlib
import re

from django.db import transaction

from .models import Bot, OneBotIdMapping, OneBotIdAlias

MAX_ID = 2 ** 53 - 1
KINDS = {'user', 'group', 'message'}


def original_alias(original):
    return 'original:' + hashlib.sha256(original.encode()).hexdigest()


def candidate(original):
    prefix = original[:13]
    if re.fullmatch(r'[0-9a-fA-F]{1,13}', prefix):
        return int(prefix, 16) or 1
    return int.from_bytes(hashlib.sha256(original.encode()).digest()[:7], 'big') % MAX_ID + 1


@transaction.atomic
def virtual_id(bot, kind, original):
    if kind not in KINDS or not isinstance(original, str) or not 1 <= len(original) <= 256:
        raise ValueError('Invalid original ID')
    # Also serializes competing first inserts with an identical candidate.
    Bot.objects.select_for_update().get(pk=bot.pk)
    redirect = OneBotIdAlias.objects.filter(bot=bot, kind=kind, alias=original_alias(original)).first()
    if redirect and redirect.original_id != original:
        return virtual_id(bot, kind, redirect.original_id)
    mappings = OneBotIdMapping.objects.filter(bot=bot, kind=kind)
    existing = mappings.filter(original_id=original).first()
    if existing:
        return real_number(existing.real_id, kind) if real_number(existing.real_id, kind) is not None else existing.virtual_id
    value = candidate(original)
    limit = 2147483647 if kind == 'message' else MAX_ID
    value = (value - 1) % limit + 1
    while (mappings.filter(virtual_id=value).exists() or mappings.filter(real_id=str(value)).exists()
           or OneBotIdAlias.objects.filter(bot=bot, kind=kind, alias=str(value)).exists()):
        value = value % limit + 1
    mappings.create(bot=bot, kind=kind, original_id=original, virtual_id=value)
    return value


def original_id(bot, kind, value):
    if isinstance(value, str) and re.fullmatch(r'-?[0-9]{1,19}', value):
        value = int(value)
    if kind not in KINDS or type(value) is not int or not (-2**63 if kind == 'message' else 0) <= value <= 2**63-1:
        raise ValueError('Invalid virtual ID')
    mappings = OneBotIdMapping.objects.filter(bot=bot, kind=kind)
    original = mappings.filter(real_id=str(value)).values_list('original_id', flat=True).first()
    if original is None:
        original = OneBotIdAlias.objects.filter(bot=bot, kind=kind, alias=str(value)).values_list('original_id', flat=True).first()
    if original is None:
        original = mappings.filter(virtual_id=value).values_list('original_id', flat=True).first()
    if original is None:
        raise ValueError('Unknown virtual ID')
    return original


def real_number(value, kind):
    if isinstance(value, str) and re.fullmatch(r'-?[0-9]{1,19}', value):
        number = int(value)
        if (-2**63 if kind == 'message' else 0) <= number <= 2**63-1:
            return number
    return None


@transaction.atomic
def learn_real_id(bot, kind, original, real):
    """Persist verified identity, replacing virtual bindings; retain resolvable old aliases."""
    if kind not in KINDS or not all(isinstance(v, str) and 1 <= len(v) <= 256 for v in (original, real)):
        raise ValueError('Invalid real ID evidence')
    Bot.objects.select_for_update().get(pk=bot.pk)
    mappings = OneBotIdMapping.objects.filter(bot=bot, kind=kind)
    virtual_id(bot, kind, original)
    row = mappings.get(original_id=original)
    previous = mappings.filter(real_id=real).exclude(pk=row.pk).first()
    if previous and not previous.original_id.startswith('companion_'):
        return False  # Conflicting evidence never silently reassigns an established user.
    if row.real_id and row.real_id != real:
        return False
    if previous:
        OneBotIdAlias.objects.update_or_create(bot=bot, kind=kind, alias=original_alias(previous.original_id), defaults={'original_id': original})
        OneBotIdAlias.objects.filter(bot=bot, kind=kind, original_id=previous.original_id).update(original_id=original)
        OneBotIdAlias.objects.update_or_create(bot=bot, kind=kind, alias=str(previous.virtual_id), defaults={'original_id': original})
        from .models import OneBotMessage
        if kind == 'user':
            OneBotMessage.objects.filter(bot=bot, sender_id=previous.original_id).update(sender_id=original)
        previous.delete()
    number = real_number(real, kind)
    if number is not None and 0 < number <= MAX_ID:
        collision = mappings.filter(virtual_id=number).exclude(pk=row.pk).first()
        if collision:
            replacement = candidate(collision.original_id + ':relocated')
            while (mappings.filter(virtual_id=replacement).exists() or mappings.filter(real_id=str(replacement)).exists()
                   or OneBotIdAlias.objects.filter(bot=bot, kind=kind, alias=str(replacement)).exists()):
                replacement = replacement % MAX_ID + 1
            collision.virtual_id = replacement
            collision.save(update_fields=['virtual_id'])
        if row.virtual_id != number:
            OneBotIdAlias.objects.update_or_create(bot=bot, kind=kind, alias=str(row.virtual_id), defaults={'original_id': original})
            row.virtual_id = number
    row.real_id = real
    row.save(update_fields=['real_id', 'virtual_id'])
    return True


def original_for_real(bot, kind, real):
    return OneBotIdMapping.objects.filter(bot=bot, kind=kind, real_id=str(real)).values_list('original_id', flat=True).first()


def real_for_original(bot, kind, original):
    return OneBotIdMapping.objects.filter(bot=bot, kind=kind, original_id=original).exclude(real_id='').values_list('real_id', flat=True).first()
