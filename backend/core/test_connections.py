import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from .models import Bot, BotGrant, ChannelConnectionRequest, GatewaySession, User
from .services import encrypt_secret
from .connection_control import ManualReconnect, probe_webhook
from .gateway import claim, dispatch, release, renew, LeaseLost

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup():
    bot = Bot.objects.create(name='Connection test', app_id='connection-app', encrypted_secret=encrypt_secret('synthetic'))
    owner = User.objects.create_user('connection-owner', role='Owner')
    client = APIClient(); client.force_login(owner)
    return bot, owner, client


def request_reconnect(setup):
    bot, _, client = setup
    response = client.post(f'/api/v1/channels/{bot.channel_id}/reconnect/', {}, format='json')
    assert response.status_code == 202, response.content
    return ChannelConnectionRequest.objects.get(channel=bot.channel)


def status(setup):
    return setup[2].get('/api/v1/channels/status/').json()[0]


def test_reconnect_queue_owner_only_idempotent_and_no_remote_call(setup):
    bot, _, client = setup
    with patch('core.official.open_upstream') as remote:
        first = request_reconnect(setup)
        assert first.generation == 1 and first.processed_generation == 0
        assert request_reconnect(setup).generation == 1
        assert status(setup)['connection_state'] == 'reconnect_pending'
    remote.assert_not_called()
    user = User.objects.create_user('connection-admin')
    client.force_login(user)
    assert client.post(f'/api/v1/channels/{bot.channel_id}/reconnect/', {}, format='json').status_code == 403
    assert client.get('/api/v1/channels/status/').json() == []
    grant=BotGrant.objects.create(bot=bot,user=user,scopes=['query:read'])
    assert status(setup)['channel'] == bot.channel_id
    grant.is_active=False; grant.save()
    assert client.get('/api/v1/channels/status/').json() == []


def test_disabled_channel_and_invalid_reconnect_payload_are_rejected(setup):
    bot, _, client=setup
    path=f'/api/v1/channels/{bot.channel_id}/reconnect/'
    assert client.post(path, {'base_url':'https://evil.example'}, format='json').status_code==400
    bot.is_active=False;bot.save()
    assert client.post(path, {},format='json').status_code==400
    assert not ChannelConnectionRequest.objects.exists()
    assert status(setup)['connection_state']=='disabled'


def test_cookie_reconnect_requires_csrf_and_does_not_accept_data_plane_keys(setup):
    bot, owner, _=setup
    strict=APIClient(enforce_csrf_checks=True);strict.force_login(owner)
    path=f'/api/v1/channels/{bot.channel_id}/reconnect/'
    assert strict.post(path,{},format='json').status_code==403
    anonymous=APIClient()
    assert anonymous.post(path,{},format='json').status_code in (401,403)


def test_gateway_reconnect_acknowledges_once_and_preserves_resume_and_lease(setup):
    bot, _, _=setup
    bot, row, token=claim(bot.pk,33554432)
    dispatch(bot,token,{'op':0,'s':1,'t':'READY','d':{'session_id':'test-session'}})
    assert status(setup)['connection_state']=='connected'
    request_reconnect(setup)
    with pytest.raises(ManualReconnect):
        renew(bot,token)
    control=ChannelConnectionRequest.objects.get(channel=bot.channel)
    assert control.generation==control.processed_generation==1
    row.refresh_from_db();assert row.lease_token==token and row.session_id=='test-session'
    renew(bot,token)
    release(bot,token)
    assert status(setup)['connection_state']=='disconnected'
    assert request_reconnect(setup).generation==2


@pytest.mark.parametrize('version',[11,12])
def test_onebot_reconnect_is_not_rolled_back_and_stale_worker_cannot_ack(setup,version):
    from .onebot_upstream_worker import claim as ob_claim, renew as ob_renew, release as ob_release, LeaseLost as OBLost
    bot=setup[0]
    bot.app_id='10001';bot.save()
    bot.channel.interface_type=f'onebot_v{version}';bot.channel.base_url='http://127.0.0.1:3000';bot.channel.save()
    bot,token=ob_claim(bot.pk)
    ob_renew(bot,token,connected=True)
    assert status(setup)['connection_state']=='connected'
    request_reconnect(setup)
    with pytest.raises(OBLost):
        ob_renew(bot,uuid.uuid4())
    assert ChannelConnectionRequest.objects.get(channel=bot.channel).processed_generation==0
    with pytest.raises(ManualReconnect):
        ob_renew(bot,token)
    assert ChannelConnectionRequest.objects.get(channel=bot.channel).processed_generation==1
    ob_renew(bot,token,connected=False)
    assert status(setup)['connection_state']=='connecting'
    ob_release(bot,token)
    assert status(setup)['connection_state']=='disconnected'


def test_status_rejects_expired_or_previous_configuration_snapshot(setup):
    bot=setup[0]
    current, _, token=claim(bot.pk,33554432)
    dispatch(current,token,{'op':0,'s':1,'t':'READY','d':{'session_id':'test-session'}})
    GatewaySession.objects.filter(bot=bot).update(lease_until=timezone.now()-timedelta(seconds=1))
    assert status(setup)['connection_state']=='disconnected'
    GatewaySession.objects.filter(bot=bot).update(lease_until=timezone.now()+timedelta(seconds=60))
    bot.encrypted_secret=encrypt_secret('rotated');bot.save()
    assert status(setup)['connection_state']=='disconnected'


@pytest.mark.parametrize('success',[True,False])
def test_webhook_probe_never_claims_websocket_online(setup,success):
    bot=setup[0];bot.channel.interface_type='qq_official_webhook';bot.channel.save()
    row=request_reconnect(setup)
    with patch('core.onebot.identity',side_effect=None if success else ValueError('secret response'),return_value=({'platform':'qq','user_id':'original'},'')):
        probe_webhook(bot,row.generation)
    row.refresh_from_db()
    assert row.reachable is success and row.checked_at and row.processed_generation==row.generation
    assert 'secret' not in row.error_code
    assert status(setup)['connection_state']=='webhook'
    assert not status(setup)['upstream_connected']
    assert status(setup)['last_check_ok'] is success


def test_supervisor_preserves_gateway_intents_and_allowlist(setup):
    from .management.commands.run_connections import worker_arguments
    bot=setup[0]
    GatewaySession.objects.create(bot=bot,intents=123)
    args=worker_arguments(bot,intents=33554432,allowed_group='approved-group')
    assert args[-4:]==['--intents','123','--allowed-group','approved-group']
    assert args[1].endswith('manage.py') and args[2]=='run_gateway'
    assert 'synthetic' not in ' '.join(args)


def test_existing_snapshot_without_ready_is_connecting_not_online(setup):
    bot,_,token=claim(setup[0].pk,33554432)
    assert status(setup)['connection_state']=='connecting'
    release(bot,token)
    assert status(setup)['connection_state']=='disconnected'
