import asyncio
import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlsplit

import pytest
from rest_framework.exceptions import PermissionDenied

from .onebot_connect import session, universal_socket, websocket_token
from .onebot_reverse import post_webhook, quick_operations, reverse_session


@pytest.mark.parametrize('version', [11, 12])
def test_webhook_signature_and_version_headers(version):
    connection = MagicMock()
    connection.getresponse.return_value.status = 204
    connection.getresponse.return_value.read.return_value = b''
    with patch('core.onebot_reverse.destination', return_value=urlsplit('https://example.com/event')), patch(
        'core.onebot_reverse.resolve_public', return_value='1.1.1.1'), patch('core.onebot_reverse.PinnedHTTPSConnection', return_value=connection):
        assert post_webhook('https://example.com/event', {'self_id': 123}, version, 'remote-token', 'secret') is None
    args, kwargs = connection.request.call_args
    body, headers = args[2:]
    assert headers['Authorization'] == 'Bearer remote-token'
    assert headers['X-OneBot-Version'] == str(version)
    if version == 11:
        assert headers['X-Signature'] == 'sha1=' + hmac.new(b'secret', body, hashlib.sha1).hexdigest()
        assert headers['X-Self-ID'] == '123'
    else:
        assert headers['X-Impl'] == 'botoize' and 'X-Signature' not in headers
    connection.close.assert_called_once()


def test_quick_actions_validate_and_share_authorization():
    event = {'post_type': 'message', 'message_type': 'group', 'message_id': 1, 'group_id': 2, 'user_id': 3}
    with patch('core.onebot_reverse.call_action', return_value={'retcode': 0}) as call:
        assert quick_operations('key', event, {'reply': 'hi'}, 11) == [1404]  # Cannot silently drop at_sender.
        assert quick_operations('key', event, {'reply': 'hi', 'at_sender': False}, 11) == [0]
        assert call.call_args.args[1]['params']['qq.reply_to'] == 1
        assert quick_operations('key', {}, [{'action': 'get_version', 'params': {}, 'echo': 'a'}], 12) == [0]
        assert call.call_args.kwargs['version'] == 12
        assert quick_operations('key', {}, [{'action': 'get_version', 'params': {}, 'echo': {}}], 12) == [10001]


def test_auth_header_precedence_and_query_support():
    assert websocket_token({'headers': [], 'query_string': b'access_token=test'}) == 'test'
    assert websocket_token({'headers': [(b'authorization', b'Bearer header')], 'query_string': b'access_token=query'}) == 'header'
    for scope in [
        {'headers': [(b'authorization', b'bad')], 'query_string': b'access_token=test'},
        {'headers': [], 'query_string': b'access_token=a&access_token=b'},
        {'headers': [(b'origin', b'https://browser')], 'query_string': b'access_token=a'},
    ]:
        with pytest.raises(ValueError):
            websocket_token(scope)


@pytest.mark.parametrize('path', ['/onebot', '/onebot/v11/', '/onebot/v12/'])
@pytest.mark.parametrize('header, query, expected', [
    (None, b'access_token=query-secret', b'Bearer query-secret'),
    (b'Bearer header-secret', b'access_token=query-secret', b'Bearer header-secret'),
    (None, b'access_token=first&access_token=second', None),
])
def test_asgi_redacts_url_token_before_dispatch(path, header, query, expected):
    from config.asgi import application
    async def run():
        scope = {'type': 'websocket', 'path': path, 'query_string': query,
                 'headers': [(b'authorization', header)] if header else []}
        async def handler(actual, receive, send):
            assert actual['query_string'] == b''
            assert dict(actual['headers']).get(b'authorization') == expected
        with patch('config.asgi.universal_socket', new=handler):
            await application(scope, None, None)
        assert b'secret' not in scope['query_string']
    asyncio.run(run())


def test_universal_live_revocation_closes_without_action():
    async def run():
        messages, queue = [], asyncio.Queue()
        queue.put_nowait({'type': 'websocket.connect'})
        async def send(frame):
            messages.append(frame)
        def revoked(token):
            if len(messages) > 1:
                raise PermissionDenied()
        with patch('core.onebot_connect.check_token', new=revoked), patch('core.onebot_connect.probe_status', return_value={'good': True, 'bots': []}), patch(
                'core.onebot_connect.connection_info', new=lambda *args: ('self', 0, False, 'qq')):
            await asyncio.wait_for(universal_socket({'path': '/onebot/v12/',
                'headers': [(b'authorization', b'Bearer key')], 'query_string': b''}, queue.get, send), 3)
        assert messages[-1] == {'type': 'websocket.close', 'code': 4403}
    asyncio.run(run())


def test_invalid_handshake_is_401_before_upgrade():
    async def run():
        messages = []
        async def send(frame):
            messages.append(frame)
        async def receive():
            raise AssertionError('Unauthenticated connection must not be read/upgraded')
        await universal_socket({'path': '/onebot/v12/', 'headers': [], 'query_string': b'',
                                'extensions': {'websocket.http.response': {}}}, receive, send)
        assert messages[0]['status'] == 401 and all(m['type'] != 'websocket.accept' for m in messages)
    asyncio.run(run())


@pytest.mark.parametrize('version', [11, 12])
def test_reverse_ws_headers_dns_pin_and_resume_cursor(version):
    async def run():
        peer = MagicMock(cursor=42)
        raw = MagicMock()
        ws = MagicMock()
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=ws)
        context.__aexit__ = AsyncMock(return_value=False)
        calls = []
        async def fake_session(token, protocol, receive, emit, **kwargs):
            calls.append(kwargs)
        with patch('core.onebot_reverse.reverse_destination', return_value=urlsplit('https://example.com/ws')), patch(
            'core.onebot_reverse.resolve_public', new=lambda host: '1.1.1.1'), patch(
            'core.onebot_reverse.connection_info', new=lambda *args: ('self' if version == 12 else 123, 999, True, 'qq')), patch(
            'core.onebot_reverse.socket.create_connection', return_value=raw), patch(
            'core.onebot_reverse.connect', return_value=context) as connection, patch('core.onebot_reverse.session', new=fake_session):
            await reverse_session(peer, 'local-key', 'wss://example.com/ws', version, 'remote-token')
        kwargs = connection.call_args.kwargs
        assert kwargs['sock'] is raw and kwargs['proxy'] is None
        assert kwargs['additional_headers']['Authorization'] == 'Bearer remote-token'
        assert 'local-key' not in str(connection.call_args)
        if version == 12:
            assert kwargs['subprotocols'] == ['12.botoize']
        else:
            assert kwargs['additional_headers']['X-Client-Role'] == 'Universal'
            assert kwargs['additional_headers']['X-Self-ID'] == '123'
        assert calls[0]['cursor_start'] == 42
        raw.close.assert_called_once()
    asyncio.run(run())
