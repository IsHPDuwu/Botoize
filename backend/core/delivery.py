"""At-least-once HTTPS event delivery with DNS pinning and TLS verification."""
import http.client
import hashlib
import hmac
import ipaddress
import json
import socket
import ssl
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from django.utils import timezone

from .models import DeliveryAttempt, EventOutbox, HttpSubscription
from .outbox import claim_outbox, finish_outbox, validate_lease
from .subscriptions import decrypt_callback_secret, subscription_is_current, validate_callback


class UnsafeDestination(ValueError):
    pass


@dataclass(frozen=True)
class DeliveryResult:
    success: bool
    status: int | None = None

    def __bool__(self):
        return self.success


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


def post_event(url, payload, delivery_id, secret=None):
    validate_callback(url)
    target = urlsplit(url)
    address = resolve_public(target.hostname)
    connection = PinnedHTTPSConnection(target.hostname, address)
    try:
        path = target.path or '/'
        if target.query:
            path += '?' + target.query
        body = json.dumps(payload, ensure_ascii=True, separators=(',', ':')).encode('utf-8')
        timestamp = str(int(time.time()))
        signature_input = timestamp.encode('ascii') + b'.' + str(delivery_id).encode('ascii') + b'.' + body
        signature = hmac.new((secret or '').encode('utf-8'), signature_input, hashlib.sha256).hexdigest()
        connection.request('POST', path, body=body, headers={
            'Content-Type': 'application/json',
            'X-QQ-Proxy-Delivery-ID': str(delivery_id),
            'X-QQ-Proxy-Timestamp': timestamp,
            'X-QQ-Proxy-Signature': 'v1=' + signature,
            'User-Agent': 'QQ-Official-Bot-Proxy/1',
        })
        response = connection.getresponse()
        # Never follow redirects or buffer an unbounded response body.
        return DeliveryResult(200 <= response.status < 300, response.status)
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
        DeliveryAttempt.objects.filter(
            outbox=row, state=DeliveryAttempt.State.PROCESSING, finished_at__isnull=True,
        ).update(
            state=DeliveryAttempt.State.RETRY,
            error_code='worker_lost',
            finished_at=timezone.now(),
        )
        attempt = DeliveryAttempt.objects.create(
            outbox=row, generation=row.attempt_generation, attempt_number=row.attempts,
        )
        status = None
        error_code = ''
        try:
            outcome = post_event(sub.url, row.event.payload, pk, decrypt_callback_secret(sub))
            status = getattr(outcome, 'status', None)
            success = bool(outcome)
            if not success:
                error_code = 'http_status' if status is not None else 'network_error'
        except UnsafeDestination:
            success = False
            error_code = 'unsafe_destination'
        except (OSError, ValueError, http.client.HTTPException):
            success = False
            error_code = 'network_error'
        acknowledged = finish_outbox(pk, token, success)
        attempt.state = (
            DeliveryAttempt.State.DELIVERED if success and acknowledged
            else DeliveryAttempt.State.RETRY if not success and acknowledged and EventOutbox.objects.filter(pk=pk, state='pending').exists()
            else DeliveryAttempt.State.FAILED if not success
            else DeliveryAttempt.State.CANCELLED
        )
        attempt.http_status = status
        attempt.error_code = error_code
        attempt.finished_at = timezone.now()
        attempt.save(update_fields=['state', 'http_status', 'error_code', 'finished_at'])
        result['delivered' if success and acknowledged else 'retry_or_failed'] += 1
    return result