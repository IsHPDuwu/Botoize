"""Operator-configured public reverse WS and HTTP event transports."""
import asyncio
import hashlib
import hmac
import json
import socket
from urllib.parse import urlsplit, urlunsplit

from asgiref.sync import sync_to_async
from rest_framework.exceptions import APIException
from websockets.asyncio.client import connect

from .delivery import PinnedHTTPSConnection, resolve_public
from .onebot import VERSION, identity, public_id
from .onebot_common import OneBotError
from .onebot_connect import connection_info, meta, session, status_data
from .onebot_files import destination
from .onebot_http import envelope_error
from .onebot_peer import renew_peer
from .onebot_socket import call_action
from .services import authorize
from .websocket import read_onebot_page


def reverse_destination(url):
    if not isinstance(url, str) or not url.startswith('wss://'):
        raise ValueError('Reverse WebSocket requires a public wss:// URL on port 443')
    target = destination('https://' + url[6:])
    return target


def post_webhook(url, payload, version, token='', secret=''):
    target = destination(url)
    if target.scheme != 'https':
        raise ValueError('Webhook requires HTTPS')
    connection = PinnedHTTPSConnection(target.hostname, resolve_public(target.hostname))
    body = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode()
    headers = {'Content-Type': 'application/json', 'User-Agent': f'OneBot/{version} (qq) Botoize/{VERSION["version"]}',
               'X-OneBot-Version': str(version), 'X-Impl': 'botoize'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    if version == 11:
        headers['X-Self-ID'] = str(payload['self_id'])
        if secret:
            headers['X-Signature'] = 'sha1=' + hmac.new(secret.encode(), body, hashlib.sha1).hexdigest()
    try:
        connection.request('POST', (target.path or '/') + ('?' + target.query if target.query else ''), body, headers)
        response = connection.getresponse()
        raw = response.read(65537)
        if response.status not in {200, 204}:
            raise OneBotError(33000, 'OneBot webhook HTTP failure')
        if response.status == 204 or not raw:
            return None
        if len(raw) > 65536 or response.getheader('Content-Type', '').split(';')[0] != 'application/json':
            # Delivery succeeded; malformed quick operations must not cause redelivery.
            return {'botoize.invalid_response': True} if version == 11 else []
        try:
            return json.loads(raw)
        except (ValueError, UnicodeError, RecursionError):
            return {'botoize.invalid_response': True} if version == 11 else []
    finally:
        connection.close()


def quick_operations(token, event, response, version):
    if response is None:
        return []
    if version == 12:
        if not isinstance(response, list) or len(response) > 100:
            return [10001]
        codes = []
        for envelope in response:
            error = envelope_error(envelope, 12)
            codes.append(error['retcode'] if error else call_action(token, envelope, version=12)['retcode'])
        return codes
    if not isinstance(response, dict) or set(response) - {'reply', 'auto_escape', 'at_sender'}:
        return [1404]
    if 'reply' not in response:
        return []
    if event.get('post_type') != 'message':
        return [1400]
    group = event.get('message_type') == 'group'
    # QQ official has no arbitrary @ segment for group messages.
    if group and response.get('at_sender', True) is not False:
        return [1404]
    params = {'message': response['reply'], 'auto_escape': response.get('auto_escape', False),
              'qq.reply_to': event['message_id'],
              'group_id' if group else 'user_id': event['group_id' if group else 'user_id']}
    return [call_action(token, {'action': 'send_group_msg' if group else 'send_private_msg', 'params': params})['retcode']]


def webhook_batch(peer, token, url, version, remote_token='', secret=''):
    renew_peer(peer, token)
    self_id, _, _ = connection_info(token, version)
    page = read_onebot_page(token, peer.cursor, self_id, version=version)
    delivered, rejected = 0, 0
    for row in page:
        renew_peer(peer, token)
        if row['payload'] is not None:
            response = post_webhook(url, row['payload'], version, remote_token, secret)
            # Acknowledge before executing quick operations: never blindly repeat sends.
            renew_peer(peer, token, int(row['cursor']))
            rejected += sum(code != 0 for code in quick_operations(token, row['payload'], response, version))
            delivered += 1
        else:
            renew_peer(peer, token, int(row['cursor']))
    return delivered, rejected


async def reverse_session(peer, token, url, version, remote_token=''):
    target = reverse_destination(url)
    address = await sync_to_async(resolve_public)(target.hostname)
    self_id, _, _ = await sync_to_async(connection_info)(token, version)
    headers = {}
    if remote_token:
        headers['Authorization'] = 'Bearer ' + remote_token
    if version == 11:
        headers.update({'X-Self-ID': str(self_id), 'X-Client-Role': 'Universal'})
    # Pass an already-connected socket: TLS SNI remains the original hostname;
    # redirects and environment proxies cannot re-resolve or bypass DNS pinning.
    sock = await asyncio.wait_for(asyncio.to_thread(socket.create_connection, (address, 443), 10), timeout=12)
    sock.setblocking(False)
    try:
        async with connect(url, sock=sock, proxy=None, additional_headers=headers,
                           subprotocols=['12.botoize'] if version == 12 else None,
                           user_agent_header=f'OneBot/{version} (qq) Botoize/{VERSION["version"]}',
                           open_timeout=10, max_size=12 * 1024 * 1024, max_queue=4) as ws:
            async def receive():
                try:
                    return await ws.recv()
                except Exception:
                    return None

            async def emit(payload):
                await asyncio.wait_for(ws.send(json.dumps(payload)), timeout=10)

            await session(token, version, receive, emit, cursor_start=peer.cursor,
                          acknowledge=lambda cursor: renew_peer(peer, token, cursor),
                          renew=lambda: renew_peer(peer, token))
    finally:
        sock.close()
