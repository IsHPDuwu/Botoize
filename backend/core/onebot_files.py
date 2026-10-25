"""Bounded, key-owned OneBot files. No server paths, redirects, or private URLs."""
import base64
import hashlib
import http.client
import re
import uuid
from datetime import timedelta
from urllib.parse import urlsplit

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .conversations import check_conversation
from .delivery import PinnedHTTPSConnection, resolve_public
from .models import ApiKey, OneBotFile
from .onebot_common import OneBotError, fields, integer

MAX_FILE = 8 * 1024 * 1024
MAX_TOTAL = 64 * 1024 * 1024


def destination(url):
    if not isinstance(url, str) or len(url) > 2048 or any(ord(c) <= 32 or ord(c) == 127 for c in url):
        raise OneBotError(10003, 'Invalid public HTTP(S) URL')
    try:
        target = urlsplit(url)
        if (target.scheme not in {'https', 'http'} or not target.hostname or target.username is not None
                or target.password is not None or target.fragment
                or target.port not in (None, 443 if target.scheme == 'https' else 80)):
            raise ValueError
        resolve_public(target.hostname)
    except (ValueError, OSError):
        raise OneBotError(10003, 'Only public HTTP(S) destinations are allowed') from None
    return target


def download(url, headers=None):
    target = destination(url)
    headers = headers or {}
    if (not isinstance(headers, dict) or len(headers) > 16
            or any(not isinstance(k, str) or not re.fullmatch(r'[A-Za-z0-9-]{1,64}', k)
                   or k.lower() in {'host', 'connection', 'transfer-encoding', 'content-length', 'proxy-authorization'}
                   or not isinstance(v, str) or len(v) > 4096 or not v.isascii()
                   or any(ord(c) < 32 or ord(c) == 127 for c in v) for k, v in headers.items())):
        raise OneBotError(10003, 'Invalid download headers')
    address = resolve_public(target.hostname)
    connection = (PinnedHTTPSConnection(target.hostname, address) if target.scheme == 'https'
                  else http.client.HTTPConnection(address, port=80, timeout=10))
    try:
        path = target.path or '/'
        if target.query:
            path += '?' + target.query
        connection.request('GET', path, headers={**headers, 'Host': target.hostname, 'Accept-Encoding': 'identity'})
        response = connection.getresponse()
        if response.status != 200:
            raise OneBotError(33000, 'File download failed (redirects are not followed)')
        data = response.read(MAX_FILE + 1)
        if len(data) > MAX_FILE:
            raise OneBotError(10004, 'Maximum file size is 8 MiB')
        return data
    except (OSError, http.client.HTTPException, ValueError):
        raise OneBotError(33000, 'File download failed') from None
    finally:
        connection.close()


def decode_data(value):
    if not isinstance(value, str) or len(value) > (MAX_FILE + 2) // 3 * 4:
        raise OneBotError(10003, 'Invalid or oversized Base64 data')
    try:
        data = base64.b64decode(value, validate=True)
    except ValueError:
        raise OneBotError(10003, 'Invalid Base64 data') from None
    if len(data) > MAX_FILE:
        raise OneBotError(10004, 'Maximum file size is 8 MiB')
    return data


def file_name(value):
    if (not isinstance(value, str) or not 1 <= len(value) <= 255
            or any(ord(c) < 32 or c in '/\\' for c in value) or value in {'.', '..'}):
        raise OneBotError(10003, 'Invalid file name')
    return value


def checksum(data, expected=None):
    digest = hashlib.sha256(data).hexdigest()
    if expected is not None and (not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected)
                                 or expected != digest):
        raise OneBotError(10003, 'SHA256 mismatch')
    return digest


def owned_file(key, value, *, complete=True, lock=False):
    try:
        value = uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise OneBotError(10003, 'Invalid file ID') from None
    rows = OneBotFile.objects.select_for_update() if lock else OneBotFile.objects
    row = rows.filter(pk=value, api_key=key, expires_at__gt=timezone.now()).first()
    if row is None or (complete and not row.complete):
        raise OneBotError(35004, 'File unavailable for this key')
    if row.target_id:
        if row.conversation_type == 'channel':
            from .onebot_guilds import broad
            broad(key)
        else:
            check_conversation(key, row.is_direct, row.target_id)
    return row


@transaction.atomic
def create_file(key, name, data=b'', *, url='', complete=True, total_size=None, **extra):
    ApiKey.objects.select_for_update().get(pk=key.pk)
    OneBotFile.objects.filter(api_key=key, expires_at__lte=timezone.now()).delete()
    rows = OneBotFile.objects.filter(api_key=key)
    size = len(data) if total_size is None else total_size
    if rows.count() >= 1000 or (rows.aggregate(total=Sum('total_size'))['total'] or 0) + size > MAX_TOTAL:
        raise OneBotError(35029, 'File storage limit exceeded')
    return OneBotFile.objects.create(api_key=key, name=file_name(name), data=data, url=url,
                                    total_size=size, complete=complete, sha256=checksum(data) if complete and not url else '',
                                    expires_at=timezone.now() + timedelta(hours=24), **extra)


@transaction.atomic
def file_bytes(row):
    if row.url:
        ApiKey.objects.select_for_update().get(pk=row.api_key_id)
        data = download(row.url)
        total = OneBotFile.objects.filter(api_key_id=row.api_key_id).aggregate(total=Sum('total_size'))['total'] or 0
        if total - row.total_size + len(data) > MAX_TOTAL:
            raise OneBotError(35029, 'File storage limit exceeded')
        # Cache a bounded snapshot; subsequent reads do not fetch a changed remote URL.
        row.data, row.url, row.total_size, row.sha256 = data, '', len(data), checksum(data)
        row.save(update_fields=['data', 'url', 'total_size', 'sha256'])
    return bytes(row.data)


@transaction.atomic
def file_action(key, action, params):
    if action == 'upload_file':
        fields(params, {'type', 'name', 'url', 'headers', 'data', 'path', 'sha256'}, {'type', 'name'})
        kind = params['type']
        if kind == 'path':
            raise OneBotError(10004, 'Server filesystem access is disabled; use data or url')
        if kind not in {'url', 'data'}:
            raise OneBotError(10003, 'Invalid upload type')
        fields(params, {'type', 'name', 'sha256', 'url', 'headers'} if kind == 'url' else {'type', 'name', 'sha256', 'data'},
               {kind})
        file_name(params['name'])
        data = download(params['url'], params.get('headers')) if kind == 'url' else decode_data(params['data'])
        checksum(data, params.get('sha256'))
        return {'file_id': str(create_file(key, params['name'], data).pk)}
    if action == 'upload_file_fragmented':
        stage = params.get('stage')
        if stage == 'prepare':
            fields(params, {'stage', 'name', 'total_size'}, {'name', 'total_size'})
            size = integer(params['total_size'], 0, MAX_FILE)
            return {'file_id': str(create_file(key, params['name'], complete=False, total_size=size).pk)}
        if stage not in {'transfer', 'finish'}:
            raise OneBotError(10003, 'Invalid upload stage')
        fields(params, {'stage', 'file_id', 'offset', 'data'} if stage == 'transfer' else {'stage', 'file_id', 'sha256'},
               {'file_id', 'offset', 'data'} if stage == 'transfer' else {'file_id', 'sha256'})
        row = owned_file(key, params['file_id'], complete=False, lock=True)
        if row.complete:
            raise OneBotError(35000, 'Upload already finished')
        if stage == 'transfer':
            offset = integer(params['offset'], 0, row.total_size)
            data = decode_data(params['data'])
            end = offset + len(data)
            if end > row.total_size:
                raise OneBotError(10003, 'Fragment exceeds total_size')
            current = bytearray(row.data)
            current.extend(b'\0' * max(0, end - len(current)))
            for start, stop in row.ranges:
                left, right = max(start, offset), min(stop, end)
                if left < right and current[left:right] != data[left-offset:right-offset]:
                    raise OneBotError(10003, 'Conflicting fragment overlap')
            current[offset:end] = data
            merged = []
            for start, stop in sorted(row.ranges + ([[offset, end]] if data else [])):
                if merged and start <= merged[-1][1]:
                    merged[-1][1] = max(merged[-1][1], stop)
                else:
                    merged.append([start, stop])
            row.data, row.ranges = bytes(current), merged
            row.save(update_fields=['data', 'ranges'])
            return None
        if row.ranges != ([[0, row.total_size]] if row.total_size else []):
            raise OneBotError(10003, 'Upload incomplete')
        row.sha256, row.complete = checksum(bytes(row.data), params['sha256']), True
        row.save(update_fields=['sha256', 'complete'])
        return {'file_id': str(row.pk)}
    if action == 'get_file':
        fields(params, {'file_id', 'type'}, {'file_id', 'type'})
        row = owned_file(key, params['file_id'])
        if params['type'] == 'url' and row.url:
            return {'name': row.name, 'url': row.url}
        if params['type'] != 'data':
            raise OneBotError(10004, 'This file is available as data, not a public URL or server path')
        data = file_bytes(row)
        return {'name': row.name, 'data': base64.b64encode(data).decode(), 'sha256': checksum(data)}
    fields(params, {'stage', 'file_id', 'offset', 'size'}, {'stage', 'file_id'})
    row = owned_file(key, params['file_id'])
    data = file_bytes(row)
    if params['stage'] == 'prepare':
        fields(params, {'stage', 'file_id'})
        return {'name': row.name, 'total_size': len(data), 'sha256': checksum(data)}
    if params['stage'] != 'transfer':
        raise OneBotError(10003, 'Invalid download stage')
    fields(params, {'stage', 'file_id', 'offset', 'size'}, {'offset', 'size'})
    offset, size = integer(params['offset'], 0, len(data)), integer(params['size'], 0, MAX_FILE)
    if offset + size > len(data):
        raise OneBotError(10003, 'Fragment exceeds file size')
    return {'data': base64.b64encode(data[offset:offset + size]).decode()}
