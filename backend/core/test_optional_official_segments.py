import json
from unittest.mock import patch

import pytest

from .test_companions import setup, add_mapping, slave_message, primary_message
from .companions import shadow_user
from .events import ingest_event
from .models import OneBotMessage
from .onebot import invoke, message_record
from .onebot_ids import virtual_id
from .onebot_upstream_events import receive_event

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize('version', [11, 12])
@pytest.mark.parametrize('missing', ['unknown', 'companion_only', 'no_reference'])
def test_missing_official_reply_and_mention_are_removed_from_send_and_history(setup, version, missing):
    bot, slave, _, _, key, _ = setup
    add_mapping(setup)
    mid = 99999 if version == 11 else 'unknown!message'
    user = 88888 if version == 11 else shadow_user(bot, '88888')
    if missing == 'companion_only':
        receive_event(slave, slave_message(slave))
        row = OneBotMessage.objects.filter(bot=bot).first()
        mid = 40004 if version == 11 else row.message_id
        user = 30003 if version == 11 else row.sender_id
    elif missing == 'no_reference':
        event = primary_message()
        event['d'].pop('ext_info')
        ingest_event(bot, event)
        receive_event(slave, slave_message(slave))
        mid = 40004 if version == 11 else 'official-message'
    message = [
        {'type':'reply','data':{'id':str(mid)} if version == 11 else {'message_id':mid}},
        {'type':'at' if version == 11 else 'mention',
         'data':{'qq':str(user)} if version == 11 else {'user_id':user}},
        {'type':'text','data':{'text':'remaining **plain**'}}]
    params = {'group_id':20002 if version == 11 else 'openid-group','message':message}
    if version == 12:
        params['detail_type'] = 'group'
    with patch('core.onebot.send_message', return_value=(200,b'{"id":"sent!id"}',{})) as send, patch(
            'core.onebot_upstream.call') as remote:
        result = invoke(bot,key.scopes,'send_group_msg' if version == 11 else 'send_message',
            params,key=key,version=version).data
    assert result['retcode'] == 0, result
    assert json.loads(send.call_args.args[2]) == {'content':'remaining **plain**','msg_type':0}
    remote.assert_not_called()
    assert message_record(bot,key,result['data']['message_id'],version).segments == [message[-1]]
    assert len(message) == 3  # Caller input is preserved.


@pytest.mark.parametrize('version', [11, 12])
def test_missing_optional_segments_do_not_hide_cross_group_or_invalid_input(setup, version):
    bot, _, _, _, key, _ = setup
    event = primary_message(group='another-group')
    ingest_event(bot,event)
    from .companions import flush_due
    from .models import CompanionObservation
    from django.utils import timezone
    CompanionObservation.objects.update(due_at=timezone.now())
    flush_due()
    mid = virtual_id(bot,'message','official-message') if version == 11 else 'official-message'
    group = virtual_id(bot,'group','openid-group') if version == 11 else 'openid-group'
    for value, expected in [(mid,1403 if version == 11 else 35003), ('bad id',1400 if version == 11 else 10003)]:
        params = {'group_id':group,'message':[
            {'type':'reply','data':{'id':str(value)} if version == 11 else {'message_id':value}},
            {'type':'text','data':{'text':'not sent'}}]}
        if version == 12:
            params['detail_type'] = 'group'
        with patch('core.onebot.send_message') as send:
            result = invoke(bot,key.scopes,'send_group_msg' if version == 11 else 'send_message',
                params,key=key,version=version).data
        assert result['retcode'] == expected, result
        send.assert_not_called()
