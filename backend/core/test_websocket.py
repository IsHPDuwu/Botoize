import asyncio
import json
from unittest.mock import patch

from rest_framework.exceptions import PermissionDenied

from .websocket import event_socket


def run_socket(headers=None, query=b'', pages=None):
    async def run():
        messages = []
        queue = asyncio.Queue()
        await queue.put({'type': 'websocket.connect'})
        async def send(message):
            messages.append(message)
        scope = {'type': 'websocket', 'path': '/relay/v1/ws/', 'headers': headers or [], 'query_string': query}
        with patch('core.websocket.read_page', side_effect=pages or PermissionDenied()):
            await asyncio.wait_for(event_socket(scope, queue.get, send), timeout=5)
        return messages
    return asyncio.run(run())


def test_ws_requires_bearer_and_rejects_browser_origin():
    assert run_socket()[0]['code'] == 4403
    assert run_socket([(b'authorization', b'Bearer token'), (b'origin', b'https://evil.test')])[0]['code'] == 4403


def test_ws_rejects_url_credentials():
    assert run_socket([(b'authorization', b'Bearer token')], b'token=secret')[0]['code'] == 4403


def test_ws_stream_and_live_reauthorization():
    event = {'cursor': '12', 'payload': {'id': 'official-id'}}
    messages = run_socket([(b'authorization', b'Bearer token')], b'after=10', [[], [event], PermissionDenied()])
    assert messages[0]['type'] == 'websocket.accept'
    assert json.loads(messages[1]['text']) == event
    assert messages[2] == {'type': 'websocket.close', 'code': 4403}