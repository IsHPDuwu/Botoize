"""Persistent virtual IDs, not QQ account numbers. Never reverse a hash."""
import hashlib
import re

from django.db import transaction

from .models import Bot, OneBotIdMapping

MAX_ID = 2 ** 53 - 1
KINDS = {'user', 'group', 'message'}


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
    mappings = OneBotIdMapping.objects.filter(bot=bot, kind=kind)
    existing = mappings.filter(original_id=original).first()
    if existing:
        return existing.virtual_id
    value = candidate(original)
    limit = 2147483647 if kind == 'message' else MAX_ID
    value = (value - 1) % limit + 1
    while mappings.filter(virtual_id=value).exists():
        value = value % limit + 1
    mappings.create(bot=bot, kind=kind, original_id=original, virtual_id=value)
    return value


def original_id(bot, kind, value):
    if isinstance(value, str) and re.fullmatch(r'[1-9][0-9]{0,15}', value):
        value = int(value)
    if kind not in KINDS or type(value) is not int or not 1 <= value <= MAX_ID:
        raise ValueError('Invalid virtual ID')
    original = OneBotIdMapping.objects.filter(bot=bot, kind=kind, virtual_id=value).values_list('original_id', flat=True).first()
    if original is None:
        raise ValueError('Unknown virtual ID')
    return original
