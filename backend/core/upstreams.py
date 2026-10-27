"""Configured upstream protocols and URL validation."""
from dataclasses import dataclass
from urllib.parse import urlsplit
import ipaddress


@dataclass(frozen=True)
class UpstreamInterface:
    interface_type: str
    label: str
    implemented: bool


INTERFACES = (
    UpstreamInterface('qq_official_websocket', 'QQ 官方机器人 WebSocket', True),
    UpstreamInterface('qq_official_webhook', 'QQ 官方机器人 Webhook', True),
    UpstreamInterface('onebot_v11', 'OneBot 11', True),
    UpstreamInterface('onebot_v12', 'OneBot 12', True),
)


def onebot_version(bot):
    kind = getattr(getattr(bot, 'channel', None), 'interface_type', '')
    return {'onebot_v11': 11, 'onebot_v12': 12}.get(kind)


def validate_onebot_url(value):
    from django.conf import settings
    if (not isinstance(value, str) or not value or len(value) > 2048 or '\\' in value
            or any(ord(c) <= 32 or ord(c) == 127 for c in value)):
        raise ValueError('Invalid OneBot endpoint')
    try:
        target = urlsplit(value)
        port = target.port
        host = target.hostname
    except (ValueError, UnicodeError):
        raise ValueError('OneBot 地址格式或端口不合法；请使用完整的 http(s):// 或 ws(s):// 地址') from None
    if target.scheme not in {'http', 'https', 'ws', 'wss'} or not host:
        raise ValueError('OneBot 地址必须以 http://、https://、ws:// 或 wss:// 开头，并填写主机地址')
    if target.username is not None or target.password is not None or target.query:
        raise ValueError('OneBot 地址不能包含用户名、密码或 query 参数；请将令牌填入独立的 Access Token 字段')
    if target.fragment or port == 0 or '%' in target.path or any(p in {'.', '..'} for p in target.path.split('/')):
        raise ValueError('OneBot 地址不能包含 fragment、编码路径、相对路径或端口 0')
    if target.scheme in {'http', 'ws'} and not settings.ONEBOT_UPSTREAM_ALLOW_PRIVATE:
        raise ValueError('HTTP/WS 需要后端配置 ONEBOT_UPSTREAM_ALLOW_PRIVATE=1；也可使用 HTTPS/WSS')
    if not settings.ONEBOT_UPSTREAM_ALLOW_PRIVATE:
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if (address and not address.is_global) or host.lower() == 'localhost' or host.lower().endswith('.localhost'):
            raise ValueError('本机或内网 OneBot 地址需要后端配置 ONEBOT_UPSTREAM_ALLOW_PRIVATE=1')
    return value.rstrip('/')


def validate_base_url(value):
    if not isinstance(value, str) or not value or len(value) > 2048 or any(ord(c) < 33 or ord(c) == 127 for c in value) or '\\' in value:
        raise ValueError('Invalid base_url')
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.port not in (None, 443) or parsed.query or parsed.fragment
                or any(part in {'.', '..'} for part in parsed.path.split('/')) or '%' in parsed.path):
            raise ValueError('HTTPS public base_url without credentials, query or fragment required')
        try:
            address = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            address = None
        if address and not address.is_global:
            raise ValueError('Public destination required')
        if parsed.hostname.lower() == 'localhost' or parsed.hostname.lower().endswith('.localhost'):
            raise ValueError('Public destination required')
    except (ValueError, UnicodeError):
        raise ValueError('Invalid or unsafe base_url') from None
    return value.rstrip('/')


def validate_interface(interface_type):
    for interface in INTERFACES:
        if interface.interface_type == interface_type and interface.implemented:
            return interface
    raise ValueError('Unsupported upstream interface; reserved adapters cannot be configured')
