"""Durable reverse-transport cursors and fenced single-worker leases."""
import hashlib
import uuid
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from .models import ApiKey, EventOutbox, OneBotPeer
from .services import authorize


@transaction.atomic
def acquire_peer(token, version, kind, url):
    key, _ = authorize(token, scope='events:read')
    ApiKey.objects.select_for_update().get(pk=key.pk)
    tail = EventOutbox.objects.filter(is_stream=True, grant__user_id=key.user_id,
                                     grant__bot_id=key.bot_id).order_by('-pk').values_list('pk', flat=True).first() or 0
    peer, _ = OneBotPeer.objects.get_or_create(api_key=key, version=version, kind=kind,
        destination_digest=hashlib.sha256(url.encode()).hexdigest(), defaults={'cursor': tail})
    if peer.lease_until and peer.lease_until > timezone.now():
        raise ValueError('This OneBot peer already has an active worker')
    peer.lease_token, peer.lease_until = uuid.uuid4(), timezone.now() + timedelta(seconds=45)
    peer.save(update_fields=['lease_token', 'lease_until'])
    return peer


def renew_peer(peer, token, cursor=None):
    authorize(token, scope='events:read')
    values = {'lease_until': timezone.now() + timedelta(seconds=45)}
    if cursor is not None:
        values['cursor'] = cursor
    if not OneBotPeer.objects.filter(pk=peer.pk, lease_token=peer.lease_token,
                                     lease_until__gt=timezone.now()).update(**values):
        raise PermissionDenied('OneBot worker lease lost')
    if cursor is not None:
        peer.cursor = cursor


def release_peer(peer):
    OneBotPeer.objects.filter(pk=peer.pk, lease_token=peer.lease_token).update(lease_until=timezone.now(), lease_token=None)
