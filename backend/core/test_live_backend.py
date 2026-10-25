"""Local HTTP transport contract, with no network or real credentials in tests."""
import json
from unittest.mock import MagicMock, patch

from .management.commands.verify_live_backend import LocalHTTP, BASE


def transport_response(status=200, data=None):
    response = MagicMock()
    response.__enter__.return_value = response
    response.status = status
    response.read.return_value = json.dumps(data or {}).encode()
    response.headers = {}
    return response


def test_local_http_bypasses_external_proxy_and_preserves_csrf():
    with patch('core.management.commands.verify_live_backend.build_opener') as build:
        build.return_value.open.return_value = transport_response()
        client = LocalHTTP()
        assert build.call_args.args[0].proxies == {}
        client.csrf = 'csrf-test'
        client.request('/api/v1/providers/', 'POST', {'name':'test'})
        request = build.return_value.open.call_args.args[0]
        assert request.full_url == BASE + '/api/v1/providers/'
        assert request.get_header('X-csrftoken') == 'csrf-test'
        assert request.get_header('Origin') == BASE


def test_real_http_relay_uses_same_bearer_and_idempotency_header():
    with patch('core.management.commands.verify_live_backend.build_opener') as build:
        build.return_value.open.return_value = transport_response(data={'id':'message'})
        client = LocalHTTP()
        client.token, client.idempotency = 'test-token', 'same-send'
        for _ in range(2):
            assert client.request('/qq/v2/groups/allowed/messages', 'POST', {'content':'text'})[0] == 200
        requests = [call.args[0] for call in build.return_value.open.call_args_list]
        assert all(request.get_header('Authorization') == 'Bearer test-token' for request in requests)
        assert all(request.get_header('Idempotency-key') == 'same-send' for request in requests)
        assert all(request.get_header('Origin') is None for request in requests)
        assert requests[0].data == requests[1].data
