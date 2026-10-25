"""Assign a validated request ID and expose it on every HTTP response."""
from .request_context import request_id_from_header


class RequestIdMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = request_id_from_header(request.headers.get('X-Request-ID'))
        response = self.get_response(request)
        response['X-Request-ID'] = request.request_id
        return response