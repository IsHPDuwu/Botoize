"""At-least-once HTTPS event delivery with DNS pinning and TLS verification."""
import http.client
import ipaddress
import json
import socket
import ssl
from urllib.parse import urlsplit

from .models import EventOutbox, HttpSubscription
from .outbox import claim_outbox, finish_outbox, validate_lease
from .subscriptions import subscription_is_current, validate_callback


class UnsafeDestination(ValueError):
    pass


def resolve_public(host):
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses:
        raise UnsafeDestination('No destination address')
    for _, _, _, _, address in addresses:
        ip = ipaddress.ip_address(address[0])
        if not ip.is_global or ip.is_multicast or getattr(ip, 'ipv4_mapped', None) is not None:
            raise UnsafeDestination('Non-public destination')
    return addresses[0][4][0]


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, address):
        super().__init__(host, port=443, timeout=10, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        raw = socket.create_connection((self.address, 443), timeout=self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def post_event(url, payload, delivery_id):
    validate_callback(url)
    target = urlsplit(url)
    address = resolve_public(target.hostname)
    connection = PinnedHTTPSConnection(target.hostname, address)
    try:
        path = target.path or '/'
        if target.query:
            path += '?' + target.query
        connection.request('POST', path, body=json.dumps(payload, ensure_ascii=True).encode('utf-8'), headers={
            'Content-Type': 'application/json',
            'X-QQ-Proxy-Delivery-ID': str(delivery_id),
            'User-Agent': 'QQ-Official-Bot-Proxy/1',
        })
        response = connection.getresponse()
        # Never follow redirects or buffer an unbounded response body.
        return 200 <= response.status < 300
    finally:
        connection.close()


def deliver_batch(limit=20):
    # Claim one item immediately before sending so a batch does not age its leases.
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError('Invalid batch limit')
    result = {'claimed': 0, 'delivered': 0, 'retry_or_failed': 0, 'skipped': 0}
    for _ in range(limit):
        claims = claim_outbox(limit=1, subscribed_only=True)
        if not claims:
            break
        pk, token = claims[0]
        result['claimed'] += 1
        row = EventOutbox.objects.select_related('event').filter(pk=pk).first()
        sub = HttpSubscription.objects.select_related('grant__user', 'grant__bot').filter(
            grant_id=row.grant_id,
        ).first() if row else None
        if not sub or not subscription_is_current(sub) or sub.grant_revision != row.grant_revision:
            finish_outbox(pk, token, False)
            result['skipped'] += 1
            continue
        if not validate_lease(pk, token):
            result['skipped'] += 1
            continue
        try:
            success = post_event(sub.url, row.event.payload, pk)
        except (OSError, ValueError, http.client.HTTPException):
            success = False
        acknowledged = finish_outbox(pk, token, success)
        result['delivered' if success and acknowledged else 'retry_or_failed'] += 1
    return result