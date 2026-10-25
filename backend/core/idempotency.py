"""Opt-in send deduplication. Never reclaim uncertain sends automatically."""
import base64
import hashlib
import json
import re
from datetime import timedelta

from cryptography.fernet import Fernet
from django.conf import settings
from django.utils import timezone

from .models import IdempotentSend


class SendConflict(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def reserve_send(key, token, path, query, body, *, content_type=None):
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}', token):
        raise ValueError('Idempotency-Key must contain 1–128 ASCII identifier characters')
    fingerprint = [path, query, base64.b64encode(body).decode('ascii')]
    if content_type is not None:
        fingerprint.append(content_type)
    digest = hashlib.sha256(json.dumps(
        fingerprint, separators=(',', ':'),
    ).encode()).hexdigest()
    row, created = IdempotentSend.objects.get_or_create(
        user_id=key.user_id, bot_id=key.bot_id,
        key_digest=hashlib.sha256(token.encode()).hexdigest(),
        defaults={'request_digest': digest, 'expires_at': timezone.now() + timedelta(hours=24)},
    )
    if created:
        return row, None
    if row.request_digest != digest:
        raise SendConflict('idempotency_conflict')
    if row.expires_at <= timezone.now():
        raise SendConflict('idempotency_expired')
    if row.state != 'completed':
        raise SendConflict('idempotency_outcome_unknown' if row.state == 'unknown' else 'idempotency_in_progress')
    data = json.loads(Fernet(settings.BOT_ENCRYPTION_KEY.encode()).decrypt(row.encrypted_result.encode()))
    return row, (data['status'], base64.b64decode(data['body']), data['headers'])


def complete_send(row, result):
    status, body, headers = result
    data = json.dumps({'status': status, 'body': base64.b64encode(body).decode('ascii'), 'headers': headers})
    encrypted = Fernet(settings.BOT_ENCRYPTION_KEY.encode()).encrypt(data.encode()).decode()
    IdempotentSend.objects.filter(pk=row.pk, state='processing').update(state='completed', encrypted_result=encrypted)


def unknown_send(row):
    IdempotentSend.objects.filter(pk=row.pk, state='processing').update(state='unknown')