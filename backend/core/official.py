"""Official credential transport; never accepts a downstream URL."""
import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from cryptography.fernet import Fernet
from django.conf import settings
from django.core.cache import cache

from .services import decrypt_secret

TOKEN_URL = 'https://api.bot.qq.com/app/getAppAccessToken'
MAX_RESPONSE_BYTES = 65536


class OfficialCredentialError(Exception):
    """Intentionally contains no upstream response, secret or request body."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def access_token(bot):
    # Bind the cache to encrypted credentials, so credential rotation cannot reuse it.
    import hashlib
    digest = hashlib.sha256(bot.app_id.encode() + b':' + bot.encrypted_secret.encode()).hexdigest()
    cache_key = f'official-token:{bot.pk}:{digest}'
    cipher = Fernet(settings.BOT_ENCRYPTION_KEY.encode())
    cached = cache.get(cache_key)
    if cached:
        return cipher.decrypt(cached).decode()
    body = json.dumps({'appId': bot.app_id, 'clientSecret': decrypt_secret(bot)}).encode()
    request = Request(TOKEN_URL, data=body, headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with build_opener(NoRedirect()).open(request, timeout=10) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if response.status != 200 or len(raw) > MAX_RESPONSE_BYTES:
                raise OfficialCredentialError('Official credential response rejected')
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get('code') not in (None, 0):
            raise OfficialCredentialError('Official credential request denied')
        token = data.get('access_token')
        ttl = data.get('expires_in')
        if isinstance(ttl, bool) or not isinstance(ttl, (str, int)):
            raise ValueError('Invalid lifetime')
        ttl = int(ttl)
        if not isinstance(token, str) or not token or len(token) > 8192 or not token.isascii() or any(char.isspace() or ord(char) < 33 or ord(char) == 127 for char in token) or not 0 < ttl <= 7200:
            raise ValueError('Invalid credential')
    except (HTTPError, URLError, OSError, ValueError, TypeError):
        raise OfficialCredentialError('Official credential service unavailable') from None
    if ttl > 60:
        cache.set(cache_key, cipher.encrypt(token.encode()), timeout=ttl - 60)
    return token


def get_self(bot, query=''):
    """Only the documented /users/@me operation; URL is not caller-controlled."""
    return _request(bot, 'GET', 'users/@me', query)


MESSAGE_PATH = re.compile(r'v2/(?:users|groups)/[A-Za-z0-9_-]{1,128}/messages')
MEDIA_PATH = re.compile(r'v2/(?:users|groups)/[A-Za-z0-9_-]{1,128}/files')


def upload_media(bot, path, body, query=''):
    if not MEDIA_PATH.fullmatch(path):
        raise ValueError('Unregistered official media path')
    return _request(bot, 'POST', path, query, body)


def send_message(bot, path, body, query=''):
    if not MESSAGE_PATH.fullmatch(path):
        raise ValueError('Unregistered official path')
    return _request(bot, 'POST', path, query, body)


def _request(bot, method, path, query='', body=None):
    url = 'https://api.bot.qq.com/' + path
    if query:
        url += '?' + query
    headers = {'Authorization': 'QQBot ' + access_token(bot)}
    if body is not None:
        headers['Content-Type'] = 'application/json; charset=utf-8'
    request = Request(url, data=body, headers=headers, method=method)
    try:
        try:
            response = build_opener(NoRedirect()).open(request, timeout=10)
        except HTTPError as error:
            response = error
        with response as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES or 300 <= response.code < 400:
                raise OfficialCredentialError('Official response rejected')
            headers = {name: response.headers[name] for name in ['Content-Type', 'X-Tps-trace-ID', 'Retry-After'] if name in response.headers}
            return response.code, raw, headers
    except (URLError, OSError, ValueError):
        raise OfficialCredentialError('Official query unavailable') from None