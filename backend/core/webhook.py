import json

from django.shortcuts import get_object_or_404
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .events import ingest_event
from .models import Bot
from .services import decrypt_secret
from .webhook_crypto import validation_response, verify_signature


class OfficialWebhook(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request, pk):
        bot = get_object_or_404(Bot, pk=pk, is_active=True)
        if request.headers.get('X-Bot-Appid') != bot.app_id:
            return Response({'detail': 'AppID mismatch'}, status=403)
        raw = request.body
        if len(raw) > 1048576:
            return Response({'detail': 'Payload too large'}, status=413)
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeError):
            return Response({'detail': 'Invalid JSON'}, status=400)
        if not isinstance(payload, dict):
            return Response({'detail': 'Envelope required'}, status=400)
        secret = decrypt_secret(bot)
        # Official initial URL verification has AppID but no signature headers.
        # Never route an unsigned verification request into event ingestion.
        if payload.get('op') == 13:
            data = payload.get('d')
            if not isinstance(data, dict):
                return Response({'detail': 'Invalid challenge'}, status=400)
            try:
                result = validation_response(secret, data.get('plain_token'), data.get('event_ts'))
            except ValueError:
                return Response({'detail': 'Invalid challenge'}, status=400)
            response = Response(result)
            response['Cache-Control'] = 'no-store'
            return response
        if not verify_signature(secret, request.headers.get('X-Signature-Timestamp'), raw, request.headers.get('X-Signature-Ed25519')):
            return Response({'detail': 'Invalid signature'}, status=401)
        try:
            ingest_event(bot, payload)
        except ValueError:
            return Response({'detail': 'Invalid dispatch envelope'}, status=400)
        # ingest_event's atomic block has committed before acknowledging.
        return Response({'op': 12})