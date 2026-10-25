"""Upstream adapter catalogue. Reserved protocols are never operational."""
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
    UpstreamInterface('onebot_v11', 'OneBot 11（预留，暂未实现）', False),
)


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