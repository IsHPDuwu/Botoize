"""OneBot HTTP/forward WS client. Endpoints and credentials belong to a Channel."""
import hashlib
import http.client
import ipaddress
import json
import socket
import ssl
import uuid
from urllib.parse import urlsplit

from django.conf import settings
from websockets.sync.client import connect

from .onebot_common import OneBotError
from .services import decrypt_secret
from .upstreams import onebot_version, validate_onebot_url

MAX_BODY = 12 * 1024 * 1024


def configuration_digest(bot):
    return hashlib.sha256((bot.app_id + ':' + bot.encrypted_secret + ':' + bot.channel.base_url
                           + ':' + bot.channel.interface_type).encode()).hexdigest()


def target(bot):
    return urlsplit(validate_onebot_url(bot.channel.base_url))


def address_for(host, port):
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not addresses:
        raise OneBotError(33000, 'OneBot destination is unavailable')
    for _, _, _, _, address in addresses:
        ip = ipaddress.ip_address(address[0])
        ip = getattr(ip, 'ipv4_mapped', None) or ip
        if (ip.is_unspecified or ip.is_multicast or ip.is_link_local or (ip.is_reserved and not ip.is_loopback)
                or (not settings.ONEBOT_UPSTREAM_ALLOW_PRIVATE and not ip.is_global)):
            raise OneBotError(10004, 'OneBot destination is disallowed by server configuration')
    return addresses[0][4][0]


class PinnedConnection(http.client.HTTPConnection):
    def __init__(self, host, port, address, tls=False):
        super().__init__(host, port=port, timeout=10)
        self.address, self.tls = address, tls

    def connect(self):
        raw = socket.create_connection((self.address, self.port), timeout=self.timeout)
        try:
            self.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=self.host) if self.tls else raw
        except BaseException:
            raw.close()
            raise


def auth_headers(bot):
    value = decrypt_secret(bot)
    if len(value) > 8192 or not value.isascii() or any(ord(c) <= 32 or ord(c) == 127 for c in value):
        raise OneBotError(10003, 'Invalid OneBot access token')
    return {'Authorization': 'Bearer ' + value} if value else {}


def parse_response(value, version, echo=None):
    if not isinstance(value, dict) or type(value.get('retcode')) is not int or value.get('status') not in {'ok', 'failed', 'async'}:
        raise OneBotError(33000, 'Invalid OneBot upstream response')
    if echo is not None and value.get('echo') != echo:
        raise OneBotError(33000, 'OneBot response correlation failed')
    if value['retcode'] != 0 or value['status'] != 'ok':
        code = value['retcode'] if version == 12 and 10000 <= value['retcode'] <= 39999 else 34000
        # Upstream error strings may contain credentials, URLs or message bodies.
        raise OneBotError(code, 'OneBot upstream rejected the action')
    return value.get('data')


def socket_connection(bot, url=None):
    url = url or bot.channel.base_url
    endpoint = urlsplit(validate_onebot_url(url))
    port = endpoint.port or (443 if endpoint.scheme == 'wss' else 80)
    raw = socket.create_connection((address_for(endpoint.hostname, port), port), timeout=10)
    try:
        return connect(url, sock=raw, proxy=None, additional_headers=auth_headers(bot),
                       open_timeout=10, close_timeout=3, max_size=MAX_BODY, max_queue=16)
    except BaseException:
        raw.close()
        raise


def call(bot, action, params=None, *, self_info=None):
    """Exactly one action attempt; sends are never retried after unknown outcomes."""
    version = onebot_version(bot)
    if version is None:
        raise OneBotError(10002, 'Channel is not a OneBot upstream')
    echo = uuid.uuid4().hex
    envelope = {'action': action, 'params': params or {}, 'echo': echo}
    if version == 12 and self_info is not None:
        envelope['self'] = self_info
    body = json.dumps(envelope if version == 12 else envelope['params'], ensure_ascii=True).encode()
    if len(body) > MAX_BODY:
        raise OneBotError(10004, 'OneBot action exceeds 12 MiB')
    try:
        endpoint = target(bot)
        if endpoint.scheme in {'ws', 'wss'}:
            import time
            with socket_connection(bot) as ws:
                ws.send(json.dumps(envelope))
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    value = json.loads(ws.recv(timeout=max(0.01, deadline - time.monotonic())))
                    if isinstance(value, dict) and value.get('echo') == echo:
                        return parse_response(value, version, echo)
                raise TimeoutError
        port = endpoint.port or (443 if endpoint.scheme == 'https' else 80)
        connection = PinnedConnection(endpoint.hostname, port, address_for(endpoint.hostname, port), endpoint.scheme == 'https')
        path = endpoint.path.rstrip('/') + ('/' + action if version == 11 else '/')
        try:
            connection.request('POST', path, body, {**auth_headers(bot), 'Content-Type': 'application/json', 'Accept': 'application/json'})
            response = connection.getresponse()
            raw = response.read(MAX_BODY + 1)
            if response.status != 200 or len(raw) > MAX_BODY:
                raise OneBotError(33000, 'OneBot upstream HTTP request failed')
            return parse_response(json.loads(raw), version, echo if version == 12 else None)
        finally:
            connection.close()
    except OneBotError:
        raise
    except Exception:
        raise OneBotError(33000, 'OneBot upstream outcome unknown; do not blindly retry a send') from None


def identity(bot):
    version = onebot_version(bot)
    if version == 11:
        data = call(bot, 'get_login_info')
        if not isinstance(data, dict) or str(data.get('user_id')) != bot.app_id:
            raise OneBotError(10102, 'OneBot upstream Bot ID does not match this Channel')
        return {'platform': 'qq', 'user_id': bot.app_id}, data.get('nickname', '')
    status = call(bot, 'get_status')
    bots = status.get('bots') if isinstance(status, dict) else None
    if not isinstance(bots, list):
        raise OneBotError(33000, 'OneBot 12 status must identify the configured Bot')
    matches = [row['self'] for row in bots if isinstance(row, dict) and isinstance(row.get('self'), dict)
               and row['self'].get('user_id') == bot.app_id and isinstance(row['self'].get('platform'), str)
               and 1 <= len(row['self']['platform']) <= 64]
    if len(matches) != 1:
        raise OneBotError(10102, 'OneBot 12 Bot ID is absent or ambiguous')
    own = {k: matches[0][k] for k in ['platform', 'user_id']}
    data = call(bot, 'get_self_info', self_info=own)
    if not isinstance(data, dict) or data.get('user_id') != bot.app_id:
        raise OneBotError(10102, 'OneBot upstream identity mismatch')
    return own, data.get('user_name', '')


def native_id(value, version, *, kind='id'):
    if version == 11:
        digits = value[1:] if isinstance(value, str) and kind == 'message' and value.startswith('-') else value
        if isinstance(digits, str) and digits.isascii() and digits.isdigit() and len(value) <= 20:
            value = int(value)
        if type(value) is not int or not (-2**63 if kind == 'message' else 0) <= value <= 2**63-1:
            raise OneBotError(10003, 'OneBot 11 requires a numeric ID')
        return value
    if not isinstance(value, str) or not 1 <= len(value) <= 256 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise OneBotError(10003, 'OneBot 12 requires a string ID')
    return value
