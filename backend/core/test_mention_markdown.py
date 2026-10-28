import json
from unittest.mock import patch

import pytest

from .test_companions import setup, add_mapping, primary_message, slave_message
from .events import ingest_event
from .onebot import invoke, message_record
from .onebot_ids import virtual_id
from .onebot_upstream_events import receive_event
from .official import send_message, OfficialCredentialError

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize('version', [11, 12])
@pytest.mark.parametrize('prefer', [False, True])
def test_mentions_use_official_openid_and_auto_markdown_with_quote(setup, version, prefer):
    master, slave, _, _, key, _ = setup
    add_mapping(setup)
    master.channel.prefer_markdown = prefer; master.channel.save()
    ingest_event(master, primary_message())
    receive_event(slave, slave_message(slave))
    text = '**bold** [link](https://example.com)\n# title & <tag> `code`'
    message = [
        {'type': 'reply', 'data': {'id': '40004'} if version == 11 else {'message_id': 'official-message'}},
        {'type': 'at' if version == 11 else 'mention', 'data': {'qq': '30003'} if version == 11 else {'user_id': 'openid-user'}},
        {'type': 'text', 'data': {'text': text}}]
    params = {'group_id': 20002 if version == 11 else 'openid-group', 'message': message}
    if version == 12:
        params['detail_type'] = 'group'
    with patch('core.official._request', return_value=(200, b'{"id":"sent!id"}', {})) as upstream:
        response = invoke(master, key.scopes, 'send_group_msg' if version == 11 else 'send_message',
            params, key=key, version=version).data
    assert response['retcode'] == 0, response
    body = json.loads(upstream.call_args.args[4])
    content = body['markdown']['content']
    assert body['msg_type'] == 2 and 'content' not in body
    assert body['message_reference'] == {'message_id': 'official-reference'}
    assert content.startswith('<qqbot-at-user id="openid-user" />')
    if prefer:
        assert content.endswith(text)
    else:
        assert r'\*\*bold\*\*' in content and r'\[link\]\(https://example\.com\)' in content
        assert r'\# title &amp; &lt;tag&gt; \`code\`' in content
    stored = message_record(master, key, response['data']['message_id'], version)
    assert stored.segments[1] == {'type': 'mention', 'data': {'user_id': 'openid-user'}}
    assert stored.segments[2]['data']['text'] == text


@pytest.mark.parametrize('failure', ['reject', 'timeout'])
def test_automatic_mention_markdown_falls_back_to_exact_original_request(setup, failure):
    bot = setup[0]
    body = json.dumps({'content': '<qqbot-at-user id="user" /> **literal**',
        'msg_type': 0, 'msg_id': 'passive!id', 'msg_seq': 2}).encode()
    first = (403, b'{}', {}) if failure == 'reject' else OfficialCredentialError()
    good = (200, b'{"id":"ok!id"}', {})
    with patch('core.official._request', side_effect=[first, good]) as upstream:
        assert send_message(bot, 'v2/groups/group/messages', body) == good
    assert upstream.call_count == 2
    assert json.loads(upstream.call_args_list[0].args[4])['markdown']['content'].endswith(r'\*\*literal\*\*')
    assert upstream.call_args_list[1].args[4] == body


@pytest.mark.parametrize('text', ['email@example.com **plain**', '@nickname **plain**', '&lt;@user&gt;'])
def test_plain_at_characters_do_not_change_message_type(setup, text):
    body = json.dumps({'msg_type': 0, 'content': text}).encode()
    with patch('core.official._request', return_value=(200, b'{"id":"ok"}', {})) as upstream:
        send_message(setup[0], 'v2/groups/group/messages', body)
    assert upstream.call_args.args[4] == body


def test_explicit_markdown_is_never_escaped(setup):
    body = json.dumps({'msg_type': 2, 'markdown': {'content': '**keep** <qqbot-at-user id="user" />'}}).encode()
    with patch('core.official._request', return_value=(200, b'{"id":"ok"}', {})) as upstream:
        send_message(setup[0], 'v2/groups/group/messages', body)
    assert upstream.call_args.args[4] == body


def test_mention_all_cq_and_missing_member_mapping(setup):
    bot, _, _, _, key, _ = setup
    group = virtual_id(bot, 'group', 'group')
    with patch('core.official._request', return_value=(200, b'{"id":"ok"}', {})) as upstream:
        response = invoke(bot, key.scopes, 'send_group_msg',
            {'group_id': group, 'message': '[CQ:at,qq=all] **plain**'}, key=key).data
    assert response['retcode'] == 0, response
    assert '<qqbot-at-everyone />' in json.loads(upstream.call_args.args[4])['markdown']['content']
    from .companions import shadow_user
    unknown = virtual_id(bot, 'user', shadow_user(bot, '99999'))
    with patch('core.official._request') as upstream:
        response = invoke(bot, key.scopes, 'send_group_msg', {'group_id': group,
            'message': [{'type': 'at', 'data': {'qq': str(unknown)}}]}, key=key).data
    assert response['retcode'] == 1400
    upstream.assert_not_called()


def test_inbound_new_mention_markup_teaches_real_id_correspondence(setup):
    bot, slave, _, _, key, _ = setup
    add_mapping(setup)
    primary = primary_message(text='<qqbot-at-user id="member-openid" /> same message')
    remote = slave_message(slave, text=' same message')
    remote['message'].insert(0, {'type': 'at', 'data': {'qq': '30006'}} if slave.channel.interface_type == 'onebot_v11'
        else {'type': 'mention', 'data': {'user_id': '30006'}})
    ingest_event(bot, primary)
    receive_event(slave, remote)
    assert virtual_id(bot, 'user', 'member-openid') == 30006
