"""Explicit identity discovery for freshly configured Channels."""
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from .models import Bot, AuditLog
from .onebot import identity, public_id
from .views import ManagementView, owner, fields


def identity_failure(error):
    from cryptography.fernet import InvalidToken
    from .official import OfficialCredentialError
    from .onebot_common import OneBotError
    result = {'detail': '无法获取上游身份，请检查 Channel 配置与服务器网络。', 'error': 'identity_unavailable'}
    if isinstance(error, InvalidToken):
        result.update(error='credential_decryption_failed', detail='服务器无法解密 Channel 凭据。迁移数据库时须保留原 BOT_ENCRYPTION_KEY；若已丢失，请重新保存该 Channel 的凭据。')
    elif isinstance(error, OfficialCredentialError):
        stage = error.stage if error.stage in {'token', 'identity'} else 'identity'
        reasons = {'timeout': '请求超时', 'dns': '域名解析失败', 'tls': 'TLS 校验失败',
            'connection_refused': '连接被拒绝', 'network': '网络或代理连接失败',
            'invalid_response': '上游响应格式不合法', 'upstream_rejected': '上游拒绝请求'}
        reason = error.reason if error.reason in reasons else 'network'
        result.update(error=f'official_{stage}_{reason}', stage=stage,
            detail=f"{'获取 QQ access token' if stage == 'token' else '查询 QQ 机器人身份'}失败：{reasons[reason]}。请检查服务器代理、出口 IP 白名单及 Channel 凭据。")
        if type(error.status) is int and 100 <= error.status <= 599:
            result['upstream_http_status'] = error.status
        if type(error.code) is int and abs(error.code) < 2**63:
            result['upstream_code'] = error.code
        codes = []
        if 'upstream_http_status' in result:
            codes.append(f"HTTP {result['upstream_http_status']}")
        if 'upstream_code' in result:
            codes.append(f"code {result['upstream_code']}")
        if codes:
            result['detail'] += '（' + '，'.join(codes) + '）'
    elif isinstance(error, OneBotError):
        result.update(error='onebot_identity_unavailable', detail='OneBot 身份查询失败，请检查服务器可达的 endpoint、Access Token、Bot ID 及上游身份接口支持。')
    return result


class ChannelIdentity(ManagementView):
    def post(self, request, pk):
        owner(request)
        fields(request.data, [])
        bot = get_object_or_404(Bot.objects.select_related('channel'), channel_id=pk)
        if not bot.is_active:
            raise ValidationError('Enable this Channel before querying its identity')
        try:
            own, _ = identity(bot)
        except Exception as error:
            import logging
            failure = identity_failure(error)
            logging.getLogger(__name__).warning('Channel identity failed channel=%s error=%s status=%s code=%s',
                pk, failure['error'], failure.get('upstream_http_status'), failure.get('upstream_code'))
            return Response(failure, status=502, headers={'Cache-Control': 'no-store'})
        AuditLog.objects.create(actor=request.user.username, action='channel.identity', target=str(pk))
        return Response({'onebot11': public_id(bot, 'user', own['user_id'], 11), 'onebot12': own['user_id']},
                        headers={'Cache-Control': 'no-store'})
