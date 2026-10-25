"""OneBot 12 JSON HTTP endpoint; all post-auth protocol errors use HTTP 200."""
import json

from rest_framework.response import Response

from .onebot import invoke, protocol_result
from .views import Bearer, Capabilities, DataPlaneAuditMixin


def envelope_error(envelope, version):
    invalid = not isinstance(envelope, dict)
    if not invalid:
        invalid = (not isinstance(envelope.get('action'), str) or not isinstance(envelope.get('params', {}), dict)
                   or bool(set(envelope) - {'action', 'params', 'echo', 'self'}))
        if version == 12:
            invalid = invalid or 'params' not in envelope or ('echo' in envelope and not isinstance(envelope['echo'], str))
            if 'self' in envelope:
                own = envelope['self']
                invalid = invalid or (not isinstance(own, dict) or set(own) != {'platform', 'user_id'}
                                      or any(not isinstance(v, str) for v in own.values()))
    if invalid:
        return protocol_result(version, code=10001, message='Invalid action request',
                               echo=envelope.get('echo') if isinstance(envelope, dict) and isinstance(envelope.get('echo'), str) else None).data
    return None


class OneBot12HTTP(DataPlaneAuditMixin, Capabilities):
    authentication_classes = [Bearer]

    def get(self, request):
        return Response(status=405)

    def post(self, request):
        if request.content_type.split(';', 1)[0] != 'application/json':
            return Response(status=415)
        if len(request.body) > 12 * 1024 * 1024:
            return Response(status=413)
        try:
            envelope = json.loads(request.body)
        except (ValueError, UnicodeError, RecursionError):
            response = protocol_result(12, code=10001, message='Invalid JSON action request')
        else:
            error = envelope_error(envelope, 12)
            if error:
                response = Response(error)
            else:
                request.onebot_action = envelope['action']
                request.onebot_envelope = envelope
                response = invoke(request.auth.bot, request.effective_scopes, envelope['action'], envelope['params'],
                                  envelope.get('echo'), key=request.auth, version=12, self_info=envelope.get('self'))
        response['Cache-Control'] = 'no-store'
        return response
