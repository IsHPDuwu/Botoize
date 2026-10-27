from django.db.models import F
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import ApiKey, BotGrant, ChannelGroupMatch, OneBotIdMapping
from .onebot_ids import learn_real_id
from .onebot_upstream import native_id
from .onebot_common import OneBotError
from .providers import ManagementView, owner


def invalidate_pairing_keys(bot):
    BotGrant.objects.filter(bot=bot).update(revision=F('revision') + 1)
    ApiKey.objects.filter(bot=bot, revoked_at__isnull=True).update(revoked_at=timezone.now())


def save_matches(channel, values):
    if not isinstance(values, list) or len(values) > 10000:
        raise ValidationError('Invalid group matches')
    if not channel.companion_id:
        if values:
            raise ValidationError('Select a companion before adding group matches')
        return
    from .providers import fields, text
    from .upstreams import onebot_version
    master = channel.bots.first()
    slave = channel.companion.bots.first()
    if not slave:
        raise ValidationError('Companion has no Bot')
    seen_primary, seen_remote = set(), set()
    changed = False
    for value in values:
        fields(value, ['id', 'primary_group', 'companion_group', 'name', 'enabled', 'origin'], ['primary_group', 'companion_group'])
        left, right = text(value, 'primary_group', 256), text(value, 'companion_group', 256)
        try:
            right = str(native_id(right, onebot_version(slave)))
            if onebot_version(master):
                left = str(native_id(left, onebot_version(master)))
            else:
                import re
                if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', left):
                    raise ValueError
        except (OneBotError, ValueError):
            raise ValidationError('Invalid primary/companion group IDs') from None
        if left in seen_primary or right in seen_remote:
            raise ValidationError('Each primary/companion group can only appear once')
        seen_primary.add(left); seen_remote.add(right)
        enabled, name = value.get('enabled', True), value.get('name', '')
        if type(enabled) is not bool or not isinstance(name, str) or len(name) > 120:
            raise ValidationError('Invalid group match')
        if 'id' in value:
            if type(value['id']) is not int:
                raise ValidationError('Invalid group match ID')
            row = ChannelGroupMatch.objects.filter(pk=value['id'], channel=channel, companion=channel.companion).first()
            if row is None:
                raise ValidationError('Group match belongs to another Channel')
        else:
            row = ChannelGroupMatch(channel=channel, companion=channel.companion)
        identity_changed = not row.pk or row.primary_group != left or row.companion_group != right
        if row.pk and identity_changed:
            OneBotIdMapping.objects.filter(bot=master, kind='group', original_id=row.primary_group, real_id=row.companion_group).update(real_id='')
        if identity_changed or row.enabled != enabled or row.name != name:
            row.origin = 'manual'
            changed = True
        row.primary_group, row.companion_group, row.name, row.enabled = left, right, name, enabled
        row.save()
        if enabled:
            # Explicit correction replaces the old group binding, never unrelated user identities.
            OneBotIdMapping.objects.filter(bot=master, kind='group', original_id=left).exclude(real_id=right).update(real_id='')
            learn_real_id(master, 'group', left, right)
    if changed:
        invalidate_pairing_keys(master)


class RefreshCompanion(ManagementView):
    def post(self, request, pk):
        from django.shortcuts import get_object_or_404
        from rest_framework.response import Response
        from .models import Channel, AuditLog
        from .providers import fields
        from .companions import refresh_pairing
        owner(request)
        fields(request.data, [])
        channel = get_object_or_404(Channel, pk=pk)
        try:
            result = refresh_pairing(channel)
        except (OneBotError, ValueError):
            raise ValidationError('Companion discovery failed; existing matches were preserved') from None
        AuditLog.objects.create(actor=request.user.username, action='channel.companion.refresh', target=str(pk))
        return Response(result)
