"""Request correlation and best-effort data-plane audit utilities."""
import re
import time
from uuid import uuid4

from .models import ApiCallAudit

REQUEST_ID_PATTERN = re.compile(r'^[A-Za-z0-9._:-]{1,64}$')


def request_id_from_header(value):
    if isinstance(value, str) and REQUEST_ID_PATTERN.fullmatch(value):
        return value
    return uuid4().hex


def persist_api_call(request, response, started_at):
    auth = getattr(request, 'auth', None)
    key = auth if getattr(auth, '_meta', None) and auth._meta.model_name == 'apikey' else None
    bot = getattr(auth, 'bot', None) if key is not None else None
    user = key.user if key is not None else None
    duration_ms = max(0, min(2_147_483_647, int((time.monotonic() - started_at) * 1000)))
    try:
        django_request = getattr(request, '_request', request)
        match = getattr(django_request, 'resolver_match', None)
        route = getattr(match, 'route', None) or '<unmatched>'
        ApiCallAudit.objects.create(
            api_key=key,
            user=user,
            bot=bot,
            request_id=getattr(django_request, 'request_id', ''),
            method=request.method[:10],
            path=route[:512],
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
    except Exception:
        # Audit availability must not change the upstream proxy response.
        pass


class DataPlaneAuditMixin:
    def dispatch(self, request, *args, **kwargs):
        started_at = time.monotonic()
        response = super().dispatch(request, *args, **kwargs)
        persist_api_call(request, response, started_at)
        return response