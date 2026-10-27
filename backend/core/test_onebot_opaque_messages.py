"""QQ opaque message IDs must round trip through Koishi's OB11 get_msg requests."""
from unittest.mock import patch

import pytest
from django.utils import timezone

from .events import ingest_event
from .models import Bot, BotGrant, User
from .onebot import invoke, resolve_id
from .onebot_common import OneBotError
from .onebot_ids import virtual_id
from .services import issue_key
from .websocket import read_onebot_page

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup():
    bot = Bot.objects.create(name='Opaque IDs', app_id='opaque-ids')
    user = User.objects.create_user('opaque-reader')
    BotGrant.objects.create(user=user, bot=bot, scopes=['events:read'])
    key, token = issue_key(user, bot, 'Koishi', ['events:read'])
    return bot, key, token


def payload(eid, mid, index, **extra):
    return {'op': 0, 'id': eid, 't': 'GROUP_MESSAGE_CREATE', 'd': {
        'id': mid, 'group_openid': 'group', 'author': {'member_openid': 'member'},
        'content': 'synthetic', 'timestamp': timezone.now().isoformat(),
        'message_scene': {'ext': ['msg_idx=' + index]}, **extra}}


@pytest.mark.parametrize('mid', ['ROBOT1.0_opaque!message==', 'opaque/message+id=='])
def test_koishi_get_msg_resolves_incoming_opaque_message_and_reply_index(setup, mid):
    bot, key, token = setup
    index = 'opaque/reference+index=='
    ingest_event(bot, payload('original', mid, index))
    quoted = payload('quoted', 'ROBOT1.0_quoted!id==', 'quoted/index==')
    quoted['d']['message_scene']['ext'].append('ref_msg_idx=' + index)
    ingest_event(bot, quoted)
    events = [item['payload'] for item in read_onebot_page(token, 0, 123)]
    reply = next(s for event in events for s in event['message'] if s['type'] == 'reply')
    with patch('core.onebot.get_self') as remote:
        for value in [virtual_id(bot, 'message', mid), reply['data']['id']]:
            result = invoke(bot, key.scopes, 'get_msg', {'message_id': value}, key=key).data
            assert result['retcode'] == 0, result
            assert result['data']['message_id'] == virtual_id(bot, 'message', mid)
            assert result['data']['message'] == [{'type': 'text', 'data': {'text': 'synthetic'}}]
        remote.assert_not_called()


def test_opaque_ids_still_enforce_account_and_conversation_authorization(setup):
    bot, key, _ = setup
    mid = 'ROBOT!private/message=='
    ingest_event(bot, payload('private-grant', mid, 'ref/index=='))
    other = User.objects.create_user('other-reader')
    BotGrant.objects.create(user=other, bot=bot, scopes=['events:read'])
    other_key, _ = issue_key(other, bot, 'new grant', ['events:read'])
    result = invoke(bot, other_key.scopes, 'get_msg', {'message_id': virtual_id(bot, 'message', mid)}, key=other_key).data
    assert result['retcode'] == 1403


@pytest.mark.parametrize('bad', ['', 123, 'a\nb', 'a\x00b', 'a b', 'x' * 257])
def test_opaque_message_id_bounds_and_target_validation_remain_separate(setup, bad):
    bot = setup[0]
    with pytest.raises(OneBotError):
        resolve_id(bot, 'message', bad, 12)
    with pytest.raises(OneBotError):
        resolve_id(bot, 'group', 'group/unsafe!id', 12)
