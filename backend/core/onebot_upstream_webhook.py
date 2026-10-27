"""Authenticated upstream HTTP reports, distinct from downstream API Keys."""
import hashlib
import hmac
import json
from types import SimpleNamespace

from django.shortcuts import get_object_or_404
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Bot
from .onebot_upstream import MAX_BODY
from .onebot_upstream_events import receive_event
from .services import decrypt_secret
from .upstreams import onebot_version


class OneBotUpstreamWebhook(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request, pk):
        bot = get_object_or_404(Bot.objects.select_related('channel'), pk=pk, is_active=True,
                               channel__interface_type__in=['onebot_v11', 'onebot_v12'])
        encrypted = bot.channel.encrypted_event_secret
        if not encrypted:
            return Response({'detail': 'OneBot HTTP event reporting is disabled'}, status=403)
        raw = request.body
        if len(raw) > MAX_BODY:
            return Response(status=413)
        secret = decrypt_secret(SimpleNamespace(encrypted_secret=encrypted))
        if onebot_version(bot) == 11:
            expected = 'sha1=' + hmac.new(secret.encode(), raw, hashlib.sha1).hexdigest()
            provided = request.headers.get('X-Signature', '')
        else:
            expected = 'Bearer ' + secret
            provided = request.headers.get('Authorization', '')
        if not hmac.compare_digest(expected.encode(), provided.encode()):
            return Response({'detail': 'Invalid event authentication'}, status=401)
        try:
            receive_event(bot, json.loads(raw), event_secret=encrypted)
        except (ValueError, KeyError, TypeError, RecursionError):
            return Response({'detail': 'Invalid OneBot event'}, status=400)
        return Response(status=204)
