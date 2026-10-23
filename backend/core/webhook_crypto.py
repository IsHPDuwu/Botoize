"""QQ Webhook cryptography. Does not acknowledge or persist events."""
import re
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def private_key(secret):
    seed = secret.encode('utf-8')
    if not seed:
        raise ValueError('Empty Bot secret')
    seed = (seed * ((32 + len(seed) - 1) // len(seed)))[:32]
    return Ed25519PrivateKey.from_private_bytes(seed)


def verify_signature(secret, timestamp, body, signature, *, now=None, max_age=300):
    """Time window is platform policy, not a guarantee of replay prevention.

    Durable event deduplication is still required. Always pass untouched body bytes.
    """
    if not isinstance(timestamp, str) or not re.fullmatch(r'[0-9]{1,12}', timestamp):
        return False
    if not isinstance(signature, str) or not re.fullmatch(r'[0-9a-fA-F]{128}', signature):
        return False
    if not isinstance(body, bytes) or max_age < 0:
        return False
    current = time.time() if now is None else now
    if abs(current - int(timestamp)) > max_age:
        return False
    try:
        private_key(secret).public_key().verify(bytes.fromhex(signature), timestamp.encode() + body)
        return True
    except (InvalidSignature, ValueError):
        return False


def validation_response(secret, plain_token, event_ts):
    if not isinstance(plain_token, str) or not 1 <= len(plain_token) <= 4096:
        raise ValueError('Invalid validation token')
    if not isinstance(event_ts, str) or not re.fullmatch(r'[0-9]{1,12}', event_ts):
        raise ValueError('Invalid validation timestamp')
    signature = private_key(secret).sign((event_ts + plain_token).encode()).hex()
    return {'plain_token': plain_token, 'signature': signature}