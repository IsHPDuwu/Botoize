"""Explicit identity discovery for freshly configured Channels."""
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from .models import Bot, AuditLog
from .onebot import identity, public_id
from .views import ManagementView, owner, fields


class ChannelIdentity(ManagementView):
    def post(self, request, pk):
        owner(request)
        fields(request.data, [])
        bot = get_object_or_404(Bot.objects.select_related('channel'), channel_id=pk)
        if not bot.is_active:
            raise ValidationError('Enable this Channel before querying its identity')
        try:
            own, _ = identity(bot)
        except Exception:
            return Response({'detail': '无法获取上游身份，请检查 Channel 凭据、网络及 QQ IP 白名单后重试。'}, status=502)
        AuditLog.objects.create(actor=request.user.username, action='channel.identity', target=str(pk))
        return Response({'onebot11': public_id(bot, 'user', own['user_id'], 11), 'onebot12': own['user_id']},
                        headers={'Cache-Control': 'no-store'})
