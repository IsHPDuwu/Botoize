"""Official credential transport; never accepts a downstream URL."""
import json
import re
from contextlib import contextmanager
from urllib.parse import urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from cryptography.fernet import Fernet
from django.conf import settings
from django.core.cache import cache

from .services import decrypt_secret

TOKEN_URL = 'https://api.bot.qq.com/app/getAppAccessToken'
MAX_RESPONSE_BYTES = 65536


def base_url(bot):
    from .upstreams import validate_base_url
    return validate_base_url(bot.channel.base_url)


@contextmanager
def open_upstream(request):
    target = urlsplit(request.full_url)
    if target.hostname == 'api.bot.qq.com':
        try:
            handlers = [NoRedirect()]
            if settings.QQ_HTTP_PROXY:
                handlers.append(ProxyHandler({'https': settings.QQ_HTTP_PROXY}))
            response = build_opener(*handlers).open(request, timeout=10)
        except HTTPError as error:
            response = error
        with response as opened:
            yield opened
        return
    from .delivery import resolve_public, PinnedHTTPSConnection
    connection = PinnedHTTPSConnection(target.hostname, resolve_public(target.hostname))
    try:
        path = target.path or '/'
        if target.query:
            path += '?' + target.query
        connection.request(request.get_method(), path, body=request.data, headers=dict(request.header_items()))
        response = connection.getresponse()
        # urllib-compatible response attributes used by this transport.
        response.code = response.status
        yield response
    finally:
        connection.close()


class OfficialCredentialError(Exception):
    """Intentionally contains no upstream response, secret or request body."""

    def __init__(self, message='Official service unavailable', *, status=None, code=None, stage=None, reason=None):
        super().__init__(message)
        self.status = status if type(status) is int else None
        self.code = code if type(code) is int else None
        self.stage = stage
        self.reason = reason


def transport_reason(error):
    import socket
    import ssl
    reason = error.reason if isinstance(error, URLError) else error
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return 'timeout'
    if isinstance(reason, socket.gaierror):
        return 'dns'
    if isinstance(reason, ssl.SSLError):
        return 'tls'
    if isinstance(reason, ConnectionRefusedError):
        return 'connection_refused'
    return 'network'


def response_code(raw):
    try:
        data = json.loads(raw)
        value = data.get('code', data.get('errcode')) if isinstance(data, dict) else None
        return value if type(value) is int and abs(value) < 2**63 else None
    except (ValueError, TypeError, RecursionError):
        return None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def access_token(bot):
    # Bind the cache to encrypted credentials, so credential rotation cannot reuse it.
    import hashlib
    endpoint = base_url(bot)
    digest = hashlib.sha256(bot.app_id.encode() + b':' + bot.encrypted_secret.encode() + b':' + endpoint.encode()).hexdigest()
    cache_key = f'official-token:{bot.pk}:{digest}'
    cipher = Fernet(settings.BOT_ENCRYPTION_KEY.encode())
    cached = cache.get(cache_key)
    if cached:
        return cipher.decrypt(cached).decode()
    body = json.dumps({'appId': bot.app_id, 'clientSecret': decrypt_secret(bot)}).encode()
    request = Request(endpoint + '/app/getAppAccessToken', data=body, headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with open_upstream(request) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if response.status != 200 or len(raw) > MAX_RESPONSE_BYTES:
                raise OfficialCredentialError('Official credential response rejected', status=response.status,
                    code=response_code(raw) if len(raw) <= MAX_RESPONSE_BYTES else None, stage='token', reason='upstream_rejected')
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get('code') not in (None, 0):
            raise OfficialCredentialError('Official credential request denied', status=200,
                                          code=data.get('code') if isinstance(data, dict) else None, stage='token', reason='upstream_rejected')
        token = data.get('access_token')
        ttl = data.get('expires_in')
        if isinstance(ttl, bool) or not isinstance(ttl, (str, int)):
            raise ValueError('Invalid lifetime')
        ttl = int(ttl)
        if not isinstance(token, str) or not token or len(token) > 8192 or not token.isascii() or any(char.isspace() or ord(char) < 33 or ord(char) == 127 for char in token) or not 0 < ttl <= 7200:
            raise ValueError('Invalid credential')
    except (HTTPError, URLError, OSError) as error:
        raise OfficialCredentialError('Official credential service unavailable', stage='token', reason=transport_reason(error)) from None
    except (ValueError, TypeError):
        raise OfficialCredentialError('Official credential service unavailable', stage='token', reason='invalid_response') from None
    if ttl > 60:
        cache.set(cache_key, cipher.encrypt(token.encode()), timeout=ttl - 60)
    return token


def get_self(bot, query=''):
    """Only the documented /users/@me operation; URL is not caller-controlled."""
    return _request(bot, 'GET', 'users/@me', query)


def get_gateway(bot):
    return _request(bot, 'GET', 'gateway/bot')


MESSAGE_PATH = re.compile(r'(?:v2/(?:users|groups)/[A-Za-z0-9_-]{1,128}/messages|(?:channels|dms)/[A-Za-z0-9_-]{1,128}/messages|users/@me/dms)')
MEDIA_PATH = re.compile(r'v2/(?:users|groups)/[A-Za-z0-9_-]{1,128}/(?:files|upload_prepare|upload_part_finish)')
DELETE_MESSAGE_PATH = re.compile(r'(?:v2/(?:users|groups)|channels|dms)/[A-Za-z0-9_-]{1,128}/messages/[A-Za-z0-9_.=+-]{1,256}')


def delete_message(bot, path, query=''):
    if not DELETE_MESSAGE_PATH.fullmatch(path):
        raise ValueError('Unregistered official delete path')
    return _request(bot, 'DELETE', path, query)


def upload_media(bot, path, body, query=''):
    if not MEDIA_PATH.fullmatch(path):
        raise ValueError('Unregistered official media path')
    result = _request(bot, 'POST', path, query, body)
    from .markdown import remember_upload
    remember_upload(bot, path, body, result)
    return result


def send_message(bot, path, body, query='', *, content_type=None):
    if not MESSAGE_PATH.fullmatch(path):
        raise ValueError('Unregistered official path')
    if content_type is not None:
        if not re.fullmatch(r'channels/[A-Za-z0-9_-]{1,128}/messages', path):
            raise ValueError('Multipart is only registered for channel messages')
        validate_multipart(content_type)
        return _request(bot, 'POST', path, query, body, content_type=content_type)
    from .markdown import markdown_body, accepted, uploaded_type
    converted = markdown_body(path, body, media_type=uploaded_type(bot, path, body)) if getattr(getattr(bot, 'channel', None), 'prefer_markdown', False) else None
    # Internal media hint must never be forwarded to QQ.
    try:
        original = json.loads(body)
        if isinstance(original, dict) and 'botoize_media_type' in original:
            original.pop('botoize_media_type')
            body = json.dumps(original, ensure_ascii=False).encode()
    except (ValueError, TypeError):
        pass
    if converted is not None:
        try:
            result = _request(bot, 'POST', path, query, converted)
            if accepted(result):
                return result
        except OfficialCredentialError:
            # Explicit user choice: unknown outcomes also fall back, accepting duplicates.
            pass
    return _request(bot, 'POST', path, query, body)


def validate_multipart(content_type):
    from django.utils.http import parse_header_parameters
    if (not isinstance(content_type, str) or len(content_type) > 512
            or not content_type.isascii() or any(ord(c) < 32 or ord(c) == 127 for c in content_type)):
        raise ValueError('Invalid multipart Content-Type')
    media_type, parameters = parse_header_parameters(content_type)
    boundary = parameters.get('boundary', '')
    if (media_type != 'multipart/form-data'
            or not re.fullmatch(r"[0-9A-Za-z'()+_,./:=? -]{1,70}", boundary)
            or boundary.endswith(' ')):
        raise ValueError('Invalid multipart boundary')


def _request(bot, method, path, query='', body=None, *, content_type=None):
    from .upstreams import onebot_version
    if onebot_version(bot):
        raise OfficialCredentialError('This Channel uses OneBot, not QQ official HTTP')
    url = base_url(bot) + '/' + path
    if query:
        url += '?' + query
    headers = {'Authorization': 'QQBot ' + access_token(bot)}
    if body is not None:
        headers['Content-Type'] = content_type or 'application/json; charset=utf-8'
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with open_upstream(request) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES or 300 <= response.code < 400:
                raise OfficialCredentialError('Official response rejected', status=response.code, stage='identity' if path == 'users/@me' else 'api', reason='invalid_response')
            headers = {name: response.headers[name] for name in ['Content-Type', 'X-Tps-trace-ID', 'Retry-After'] if name in response.headers}
            return response.code, raw, headers
    except (URLError, OSError) as error:
        raise OfficialCredentialError('Official query unavailable', stage='identity' if path == 'users/@me' else 'api', reason=transport_reason(error)) from None
    except ValueError:
        raise OfficialCredentialError('Official query unavailable', stage='identity' if path == 'users/@me' else 'api', reason='invalid_response') from None
