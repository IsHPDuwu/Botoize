import copy
import json
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from .companions import match_names, flush_due, refresh_pairing, matches_data
from .events import ingest_event
from .models import (Bot, BotGrant, Channel, ChannelGroupMatch, CompanionObservation, Conversation,
                     EventOutbox, OneBotIdMapping, OneBotMessage, Provider, User)
from .onebot import invoke, public_id, message_record
from .onebot_ids import learn_real_id, original_id, virtual_id
from .onebot_upstream_events import receive_event
from .services import SCOPES, encrypt_secret, issue_key
from .websocket import read_onebot_page

pytestmark = pytest.mark.django_db


@pytest.fixture(params=[11, 12])
def setup(request):
    primary_provider = Provider.objects.create(name='primary')
    slave_provider = Provider.objects.create(name='companion')
    slave_channel = Channel.objects.create(provider=slave_provider, name='slave', interface_type=f'onebot_v{request.param}', base_url='http://127.0.0.1:3000')
    slave = Bot.objects.create(channel=slave_channel, name='slave', app_id='10001', encrypted_secret=encrypt_secret('slave-token'))
    channel = Channel.objects.create(provider=primary_provider, name='primary', companion=slave_channel)
    master = Bot.objects.create(channel=channel, name='primary', app_id='official-app', encrypted_secret=encrypt_secret('official-secret'))
    user = User.objects.create_user('paired-owner', role='Owner')
    grant = BotGrant.objects.create(user=user, bot=master, scopes=sorted(SCOPES))
    key, token = issue_key(user, master, 'primary', sorted(SCOPES))
    return master, slave, user, grant, key, token


def primary_message(text='same exact message', group='openid-group', user='openid-user', mid='official-message', at=None):
    return {'op': 0, 'id': 'event-' + mid, 't': 'GROUP_AT_MESSAGE_CREATE', 'd': {
        'id': mid, 'group_openid': group, 'content': text,
        'author': {'member_openid': user, 'username': 'user'},
        'timestamp': (at or timezone.now()).isoformat(), 'ext_info': {'ref_idx': 'official-reference'}}}


def slave_message(slave, text='same exact message', group=20002, user=30003, mid=40004, at=None):
    stamp = (at or timezone.now()).timestamp()
    if slave.channel.interface_type == 'onebot_v11':
        return {'self_id': 10001, 'time': int(stamp), 'post_type': 'message', 'message_type': 'group',
                'sub_type': 'normal', 'group_id': group, 'user_id': user, 'message_id': mid,
                'message': [{'type': 'text', 'data': {'text': text}}], 'sender': {'nickname': 'user'}}
    return {'self': {'platform': 'qq', 'user_id': '10001'}, 'id': 'event:' + str(mid), 'time': stamp,
            'type': 'message', 'detail_type': 'group', 'sub_type': '', 'group_id': str(group),
            'user_id': str(user), 'message_id': str(mid), 'message': [{'type': 'text', 'data': {'text': text}}]}


def add_mapping(setup, name='Matched'):
    master, slave = setup[:2]
    Conversation.objects.get_or_create(bot=master, is_direct=False, target_id='openid-group', defaults={'name': name})
    Conversation.objects.get_or_create(bot=slave, is_direct=False, target_id='20002', defaults={'name': name})
    assert match_names(master.channel) == 1
    return master.channel.group_matches.get()


@pytest.mark.parametrize('slave_first', [True, False])
def test_receives_companion_once_and_learns_real_ids(setup, slave_first):
    master, slave, _, _, key, token = setup
    add_mapping(setup)
    old_user = virtual_id(master, 'user', 'openid-user')
    old_group = virtual_id(master, 'group', 'openid-group')
    old_message = virtual_id(master, 'message', 'official-message')
    primary = primary_message()
    remote = slave_message(slave)
    if slave_first:
        receive_event(slave, remote)
        first = read_onebot_page(token, 0, 10001)[0]['payload']
        assert first['user_id'] == 30003 and first['message_id'] == 40004
        ingest_event(master, primary)
    else:
        ingest_event(master, primary)
        assert not EventOutbox.objects.filter(grant__bot=master).exists()
        receive_event(slave, remote)
    output = read_onebot_page(token, 0, 10001)
    assert len(output) == 1
    event = output[0]['payload']
    assert event['group_id'] == 20002 and event['user_id'] == 30003 and event['message_id'] == 40004
    assert event['message'][0]['data']['text'] == 'same exact message'
    assert virtual_id(master, 'user', 'openid-user') == 30003
    assert original_id(master, 'user', old_user) == 'openid-user'
    assert original_id(master, 'message', old_message) == 'official-message'
    assert OneBotIdMapping.objects.get(bot=master, kind='user', original_id='openid-user').virtual_id == 30003
    assert original_id(master, 'group', old_group) == 'openid-group'
    record = message_record(master, key, 40004, 11)
    assert record.target_id == 'openid-group'
    # Repeated ingestion never emits another primary event.
    receive_event(slave, remote); ingest_event(master, primary)
    assert len(read_onebot_page(token, 0, 10001)) == 1


def test_primary_fallback_when_missing_from_group_and_when_slave_down(setup):
    master, slave, _, _, _, token = setup
    add_mapping(setup)
    ingest_event(master, primary_message())
    # Worker/socket liveness never suppresses an individual primary message forever.
    CompanionObservation.objects.filter(channel=master.channel).update(due_at=timezone.now()-timedelta(seconds=1))
    assert flush_due() == 1
    result = read_onebot_page(token, 0, 10001)
    assert len(result) == 1 and result[0]['payload']['message'][0]['data']['text'] == 'same exact message'
    # A late recovered slave upgrades all IDs, without a duplicate event.
    receive_event(slave, slave_message(slave))
    assert len(read_onebot_page(token, 0, 10001)) == 1
    assert virtual_id(master, 'user', 'openid-user') == 30003
    slave.is_active = False; slave.save(update_fields=['is_active'])
    ingest_event(master, primary_message(text='after outage', mid='later'))
    output = read_onebot_page(token, 0, 10001)
    assert len(output) == 2 and output[1]['payload']['user_id'] == 30003
    ingest_event(master, primary_message(text='unknown during outage', user='new-openid', mid='unknown'))
    unknown_virtual = virtual_id(master, 'user', 'new-openid')
    assert unknown_virtual != 30003
    slave.is_active = True; slave.save(update_fields=['is_active'])
    receive_event(slave, slave_message(slave, text='unknown during outage', user=30005, mid=40005))
    assert virtual_id(master, 'user', 'new-openid') == 30005
    assert original_id(master, 'user', unknown_virtual) == 'new-openid'


def test_auto_match_unique_names_or_unambiguous_message_content(setup):
    master, slave = setup[:2]
    for group in ['a', 'b']:
        Conversation.objects.create(bot=master, is_direct=False, target_id=group, name='Duplicate name')
    for group in ['20002', '20003']:
        Conversation.objects.create(bot=slave, is_direct=False, target_id=group, name='Duplicate name')
    assert match_names(master.channel) == 0
    # Distinct time/content evidence resolves a duplicated name.
    ingest_event(master, primary_message(group='a'))
    receive_event(slave, slave_message(slave, group=20003))
    match = master.channel.group_matches.get()
    assert match.primary_group == 'a' and match.companion_group == '20003' and match.origin == 'message'


def test_ambiguous_messages_do_not_create_false_group_matches(setup):
    master, slave = setup[:2]
    at = timezone.now()
    ingest_event(master, primary_message(group='a', mid='a', at=at))
    ingest_event(master, primary_message(group='b', mid='b', at=at))
    receive_event(slave, slave_message(slave, at=at))
    assert not master.channel.group_matches.exists()
    CompanionObservation.objects.filter(side='primary').update(due_at=timezone.now()-timedelta(seconds=1))
    flush_due()
    assert EventOutbox.objects.filter(grant__bot=master).count() == 2


def test_companion_events_respect_primary_conversation_and_revision(setup):
    master, slave, _, grant, key, token = setup
    add_mapping(setup)
    grant.all_conversations = key.all_conversations = False
    grant.save(); key.save()
    receive_event(slave, slave_message(slave))
    assert read_onebot_page(token, 0, 10001) == []
    conv = master.conversations.get(target_id='openid-group')
    grant.conversations.add(conv); key.conversations.add(conv)
    receive_event(slave, slave_message(slave, mid=50005, text='visible'))
    assert len(read_onebot_page(token, 0, 10001)) == 1


def test_management_primary_first_fallback_uses_mapped_group(setup):
    master, slave, _, _, key, _ = setup
    add_mapping(setup)
    with patch('core.onebot_groups._request', return_value=(200,b'{"group_name":"primary"}',{})), patch('core.companion_actions.call') as remote:
        response = invoke(master, key.scopes, 'get_group_info', {'group_id': 20002}, key=key)
        assert response.data['retcode'] == 0 and response.data['data']['group_name'] == 'primary'
        remote.assert_not_called()
    with patch('core.onebot_groups._request', return_value=(403,b'{}',{})), patch('core.companion_actions.identity', return_value=({'platform':'qq','user_id':'10001'},'slave')), patch('core.companion_actions.call', return_value={'group_id': 20002,'group_name':'companion'}) as remote:
        response = invoke(master, key.scopes, 'get_group_info', {'group_id': 20002}, key=key)
        assert response.data['retcode'] == 0 and response.data['data']['group_id'] == 20002
        assert remote.call_args.args[1] == 'get_group_info'
        assert str(remote.call_args.args[2]['group_id']) == '20002'
    with patch('core.companion_actions.call') as remote:
        assert invoke(master, [], 'get_group_info', {'group_id':20002}, key=key).data['retcode'] == 1403
        remote.assert_not_called()


def test_send_only_uses_primary_even_if_primary_fails(setup):
    master, _, _, _, key, _ = setup
    add_mapping(setup)
    with patch('core.onebot.send_message', return_value=(403,b'{}',{})) as primary, patch('core.companion_actions.call') as remote:
        result = invoke(master, key.scopes, 'send_group_msg', {'group_id':20002,'message':'outgoing'}, key=key)
        assert result.data['retcode'] == 1500
        assert primary.call_args.args[1] == 'v2/groups/openid-group/messages'
        remote.assert_not_called()


def test_mapping_configuration_owner_only_cross_provider_no_cycles(setup):
    master, slave, owner, _, key, _ = setup
    client = APIClient(); client.force_login(owner)
    data = client.get(f'/api/v1/providers/{master.channel.provider_id}/').json()
    data.pop('id')
    data['channels'][0]['prefer_markdown'] = True
    data['channels'][0]['group_matches'] = [{'primary_group':'openid-group','companion_group':'20002','name':'Manual','enabled':True}]
    response = client.patch(f'/api/v1/providers/{master.channel.provider_id}/', data, format='json')
    assert response.status_code == 200, response.content
    key.refresh_from_db(); assert key.revoked_at
    result = response.json()['channels'][0]
    assert result['prefer_markdown'] and result['group_matches'][0]['origin'] == 'manual'
    data['channels'][0]['companion_channel'] = master.channel_id
    assert client.patch(f'/api/v1/providers/{master.channel.provider_id}/', data, format='json').status_code == 400
    data['channels'][0]['companion_channel'] = slave.channel_id
    data['channels'][0]['group_matches'][0]['id'] = 999999
    assert client.patch(f'/api/v1/providers/{master.channel.provider_id}/', data, format='json').status_code == 400
    admin = User.objects.create_user('not-owner')
    client.force_login(admin)
    assert client.patch(f'/api/v1/providers/{master.channel.provider_id}/', data, format='json').status_code == 403


def test_manual_disabled_match_prevents_automatic_recreation(setup):
    master, slave = setup[:2]
    mapping = add_mapping(setup)
    mapping.enabled=False; mapping.save(update_fields=['enabled'])
    assert match_names(master.channel) == 0
    ingest_event(master, primary_message())
    receive_event(slave, slave_message(slave))
    CompanionObservation.objects.filter(side='primary').update(due_at=timezone.now()-timedelta(seconds=1))
    flush_due()
    assert EventOutbox.objects.filter(grant__bot=master).count() == 1
    assert not master.channel.group_matches.get().enabled


def test_true_id_replaces_virtual_binding_and_survives_collision(setup):
    bot = setup[0]
    old = virtual_id(bot,'user','original')
    other = OneBotIdMapping.objects.create(bot=bot,kind='user',original_id='other',virtual_id=12345)
    assert learn_real_id(bot,'user','original','12345')
    assert virtual_id(bot,'user','original') == 12345
    assert original_id(bot,'user',old) == 'original'
    assert original_id(bot,'user',12345) == 'original'
    other.refresh_from_db(); assert other.virtual_id != 12345
    assert not learn_real_id(bot,'user','other','12345')
    assert learn_real_id(bot,'message','negative-mid','-123')
    assert virtual_id(bot,'message','negative-mid') == -123


@pytest.mark.parametrize('outcome', ['success','reject','timeout'])
def test_markdown_preserves_raw_text_and_falls_back_even_on_timeout(setup, outcome):
    from .official import send_message, OfficialCredentialError
    bot = setup[0]
    bot.channel.prefer_markdown=True; bot.channel.save(update_fields=['prefer_markdown'])
    text = 'raw **text**\n![already](https://example.com/image.png) & <tag>'
    body = json.dumps({'msg_type':0,'content':text,'msg_id':'passive-id','msg_seq':2}).encode()
    good = (200,b'{"id":"sent"}',{})
    first = good if outcome == 'success' else (403,b'{"code":1}',{}) if outcome == 'reject' else OfficialCredentialError()
    with patch('core.official._request', side_effect=[first, good]) as remote:
        assert send_message(bot,'v2/groups/openid-group/messages',body) == good
    assert json.loads(remote.call_args_list[0].args[4]) == {'msg_type':2,'markdown':{'content':text},'msg_id':'passive-id','msg_seq':2}
    assert remote.call_count == (1 if outcome == 'success' else 2)
    if outcome != 'success':
        assert remote.call_args_list[1].args[4] == body
    assert json.loads(body)['content'] == text


def test_history_gradually_upgrades_ids_without_replaying_messages(setup):
    from .companions import backfill_id_evidence
    master, slave, _, _, _, token = setup
    master.channel.companion = None; master.channel.save()
    ingest_event(master, primary_message())
    old = virtual_id(master, 'user', 'openid-user')
    receive_event(slave, slave_message(slave))
    master.channel.companion = slave.channel; master.channel.save()
    assert backfill_id_evidence(master.channel, limit=1) == 2
    assert virtual_id(master, 'user', 'openid-user') == 30003
    assert original_id(master, 'user', old) == 'openid-user'
    assert backfill_id_evidence(master.channel, limit=1) == 0
    assert len(read_onebot_page(token, 0, 10001)) == 1
    assert master.channel.group_matches.get().origin == 'message'


def test_primary_http_management_fallback_and_scope_rejection(setup):
    master, slave, _, _, key, token = setup
    add_mapping(setup)
    client = APIClient(); client.credentials(HTTP_AUTHORIZATION='Bearer ' + token)
    with patch('core.official._request', return_value=(403,b'{}',{})), patch('core.companion_actions.identity', return_value=({'platform':'qq','user_id':'10001'},'')), patch('core.companion_actions.call', return_value={'group_id':20002,'group_name':'remote'}) as remote:
        response = client.get('/qq/v2/groups/openid-group/info')
        assert response.status_code == 200, response.content
        assert response.json()['group_name'] == 'remote'
        assert response['X-Botoize-Source'] == 'companion'
        assert remote.call_count == 1
        key.scopes = ['query:read']; key.save()
        assert client.get('/qq/v2/groups/openid-group/info').status_code == 403
        assert remote.call_count == 1


def test_revocation_during_primary_request_prevents_companion_fallback(setup):
    master, slave, _, _, key, _ = setup
    add_mapping(setup)
    def revoked(*args, **kwargs):
        key.revoked_at=timezone.now(); key.save()
        return 403,b'{}',{}
    with patch('core.onebot_groups._request', side_effect=revoked), patch('core.companion_actions.call') as remote:
        response = invoke(master, key.scopes, 'get_group_info', {'group_id':20002}, key=key)
    assert response.data['retcode'] == 1403
    remote.assert_not_called()


def test_correcting_pairing_hides_previous_bridges_from_all_transports(setup):
    from .conversations import filter_events
    from .companion_config import save_matches
    master, slave, _, _, key, token = setup
    row = add_mapping(setup)
    receive_event(slave, slave_message(slave))
    assert len(read_onebot_page(token, 0, 10001)) == 1
    save_matches(master.channel, [{**matches_data(master.channel)[0], 'enabled':False}])
    assert not filter_events(EventOutbox.objects.filter(grant__bot=master), key).exists()
    with pytest.raises(Exception):
        message_record(master, key, 40004, 11)
    assert not master.channel.group_matches.get(pk=row.pk).enabled


def test_connection_ids_shown_on_channel_and_primary_identity_not_slave_identity(setup):
    from .providers import provider_data
    master, slave, owner = setup[:3]
    with patch('core.onebot.get_self', return_value=(200,b'{"id":"official-self","username":"primary"}',{})):
        response = invoke(master, ['query:read'], 'get_login_info', {}, key=setup[4])
    self_id = response.data['data']['user_id']
    master.channel.refresh_from_db()
    channel = provider_data(master.channel.provider, owner)['channels'][0]
    assert channel['connection_ids'] == {'onebot11':self_id,'onebot12':'official-self'}
    assert self_id != 10001
    remote = provider_data(slave.channel.provider, owner)['channels'][0]
    assert remote['connection_ids']['onebot12'] == '10001'
    assert isinstance(remote['connection_ids']['onebot11'], int)


def test_create_primary_with_companion_and_no_unsaved_model_query(setup):
    slave, owner = setup[1:3]
    client = APIClient(); client.force_login(owner)
    response = client.post('/api/v1/providers/', {'name':'new primary','channels':[{
        'name':'new channel', 'interface_type':'qq_official_websocket', 'app_id':'new-official',
        'secret':'new-secret','is_active':True,'models':[], 'companion_channel':slave.channel_id}]}, format='json')
    assert response.status_code == 201, response.content
    assert response.json()['channels'][0]['companion_channel'] == slave.channel_id


@pytest.mark.parametrize('kind', [1,2,3,4,None])
def test_markdown_only_converts_verified_image_handles_and_preserves_original_on_failure(setup, kind):
    from .official import upload_media, send_message
    bot = setup[0]; bot.channel.prefer_markdown=True; bot.channel.save()
    if kind:
        with patch('core.official._request', return_value=(200,b'{"file_info":"opaque-handle","ttl":300}',{})):
            upload_media(bot, 'v2/groups/openid-group/files', json.dumps({'file_type':kind}).encode())
    body=json.dumps({'msg_type':7,'content':'exact raw text','media':{'file_info':'opaque-handle'}}).encode()
    with patch('core.official._request', side_effect=[(400,b'{}',{}),(200,b'{"id":"ok"}',{})]) as remote:
        send_message(bot,'v2/groups/openid-group/messages',body)
    assert remote.call_count == (2 if kind == 1 else 1)
    if kind == 1:
        attempt=json.loads(remote.call_args_list[0].args[4])
        assert attempt['markdown']['content'] == 'exact raw text' and attempt['msg_type'] == 2
        assert remote.call_args_list[1].args[4] == body
    else:
        assert remote.call_args_list[0].args[4] == body


def test_real_id_larger_than_virtual_storage_range_remains_persistent(setup):
    master = setup[0]
    assert learn_real_id(master,'user','large','9007199254740992')
    assert virtual_id(master,'user','large') == 9007199254740992
    assert original_id(master,'user',9007199254740992) == 'large'


@pytest.mark.parametrize('preferred', [True,False])
def test_grace_keeps_arrival_authorization_snapshot(setup, preferred):
    from .models import HttpSubscription
    master, slave, _, grant, key, token = setup
    add_mapping(setup)
    ingest_event(master, primary_message())
    later = User.objects.create_user('later')
    BotGrant.objects.create(user=later, bot=master, scopes=['events:read'])
    subscription = HttpSubscription.objects.create(grant=grant, url='https://example.com/events', grant_revision=grant.revision)
    if preferred:
        receive_event(slave,slave_message(slave))
    else:
        CompanionObservation.objects.filter(side='primary').update(due_at=timezone.now()-timedelta(seconds=1))
        flush_due()
    assert len(read_onebot_page(token,0,10001)) == 1
    assert not EventOutbox.objects.filter(grant__user=later).exists()
    assert not EventOutbox.objects.filter(subscription=subscription).exists()


@pytest.mark.parametrize('primary_version',[11,12])
def test_onebot_primary_uses_companion_ids_but_sends_to_primary_native_group(setup, primary_version):
    master, slave, _, _, key, token = setup
    master.app_id='50001'; master.save()
    master.channel.interface_type=f'onebot_v{primary_version}'
    master.channel.base_url='http://127.0.0.1:3001'; master.channel.save()
    Conversation.objects.create(bot=master,is_direct=False,target_id='60002',name='Matched')
    Conversation.objects.create(bot=slave,is_direct=False,target_id='20002',name='Matched')
    match_names(master.channel)
    receive_event(slave,slave_message(slave))
    native=slave_message(master,group=60002,user=70003,mid=80004)
    if primary_version == 11:
        native['self_id']=50001
    else:
        native['self']['user_id']='50001'
    receive_event(master,native)
    rows=read_onebot_page(token,0,50001)
    assert len(rows)==1 and rows[0]['payload']['user_id']==30003
    assert message_record(master,key,40004,11).message_id=='80004'
    with patch('core.onebot_upstream_actions.identity', return_value=({'platform':'qq','user_id':'50001'},'')), patch('core.onebot_upstream_actions.call',return_value={'message_id':90005 if primary_version == 11 else '90005'}) as remote:
        response=invoke(master,key.scopes,'send_group_msg',{'group_id':20002,'message':'only primary'},key=key)
    assert response.data['retcode']==0, response.data
    assert remote.call_args.args[0].pk==master.pk
    assert str(remote.call_args.args[2]['group_id'])=='60002'


def test_companion_mentions_and_files_use_real_ids_and_primary_upload(setup):
    import base64
    master, slave, _, _, key, token = setup
    add_mapping(setup)
    message=slave_message(slave)
    if slave.channel.interface_type=='onebot_v11':
        message['message'] += [{'type':'at','data':{'qq':'30006'}},{'type':'image','data':{'file':'remote-handle'}}]
    else:
        message['message'] += [{'type':'mention','data':{'user_id':'30006'}},{'type':'image','data':{'file_id':'remote-handle'}}]
    receive_event(slave,message)
    event=read_onebot_page(token,0,10001)[0]['payload']
    assert {'type':'at','data':{'qq':'30006'}} in event['message']
    file_id=event['message'][-1]['data']['file']
    from .models import OneBotFile
    assert OneBotFile.objects.get(pk=file_id).upstream_bot_id==slave.pk
    with patch('core.onebot_upstream_actions.download_upstream_file',return_value=b'image bytes') as download, patch('core.onebot.upload_media',return_value=(200,b'{"file_info":"primary-handle"}',{})) as upload, patch('core.onebot.send_message',return_value=(200,b'{"id":"primary-sent"}',{})) as send:
        result=invoke(master,key.scopes,'send_group_msg',{'group_id':20002,'message':[{'type':'image','data':{'file':file_id}}]},key=key)
    assert result.data['retcode']==0,result.data
    download.assert_called_once()
    assert upload.call_args.args[0].pk==master.pk and send.call_args.args[0].pk==master.pk
    assert base64.b64decode(json.loads(upload.call_args.args[2])['file_data'])==b'image bytes'


def test_forwarding_borrowed_file_between_onebot_channels_reuploads_to_primary(setup):
    from .onebot_files import create_file
    from .onebot_upstream import configuration_digest
    from .onebot_upstream_actions import wire_message
    master, slave, _, _, key, _ = setup
    master.channel.interface_type='onebot_v12'; master.channel.base_url='http://127.0.0.1:3001'; master.channel.save()
    row=create_file(key,'image.bin',upstream_file_id='slave-handle',upstream_bot=slave,upstream_digest=configuration_digest(slave))
    with patch('core.onebot_upstream_actions.download_upstream_file',return_value=b'data') as download, patch('core.onebot_upstream_actions.call',return_value={'file_id':'primary-handle'}) as upload:
        wire=wire_message(master,key,[{'type':'image','data':{'file_id':str(row.pk)}}],{'platform':'qq','user_id':master.app_id})
    assert wire==[{'type':'image','data':{'file_id':'primary-handle'}}]
    download.assert_called_once()
    assert upload.call_args.args[0].pk==master.pk and upload.call_args.args[1]=='upload_file'
