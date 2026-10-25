import os
from urllib.parse import parse_qsl, urlencode
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
http_application = get_asgi_application()
from core.websocket import event_socket
from core.onebot_socket import api_socket
from core.onebot_connect import universal_socket


async def application(scope, receive, send):
	# OneBot requires URL token fallback. Remove it from the shared ASGI scope
	# before server/access logging, and prefer an explicitly supplied auth header.
	if (scope.get('path') == '/onebot' or scope.get('path', '').startswith('/onebot/')) and scope.get('query_string'):
		try:
			pairs = parse_qsl(scope['query_string'].decode('ascii'), keep_blank_values=True)
			tokens = [value for name, value in pairs if name == 'access_token']
			if tokens:
				scope['query_string'] = urlencode([(k, v) for k, v in pairs if k != 'access_token']).encode('ascii')
				headers = list(scope.get('headers', []))
				if not any(name.lower() == b'authorization' for name, _ in headers) and len(tokens) == 1:
					headers.append((b'authorization', ('Bearer ' + tokens[0]).encode('ascii')))
				scope['headers'] = headers
		except UnicodeError:
			scope['query_string'] = b''
	if scope['type'] == 'websocket':
		if scope['path'].rstrip('/') in {'/onebot', '/onebot/v11', '/onebot/v11/api', '/onebot/v11/event',
		                                  '/onebot/v12', '/onebot/v12/api', '/onebot/v12/event'}:
			return await universal_socket(scope, receive, send)
		if scope['path'] in {'/onebot/api', '/onebot/api/'}:
			return await api_socket(scope, receive, send)
		return await event_socket(scope, receive, send)
	return await http_application(scope, receive, send)
