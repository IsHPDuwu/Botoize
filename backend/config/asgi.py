import os
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
http_application = get_asgi_application()
from core.websocket import event_socket
from core.onebot_socket import api_socket


async def application(scope, receive, send):
	if scope['type'] == 'websocket':
		if scope['path'] in {'/onebot/api', '/onebot/api/'}:
			return await api_socket(scope, receive, send)
		return await event_socket(scope, receive, send)
	return await http_application(scope, receive, send)