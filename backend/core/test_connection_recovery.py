import io
import json
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from .test_connections import setup, request_reconnect
from .models import Bot, ChannelConnectionRequest, GatewaySession
from .management.commands.run_connections import Supervisor
from .gateway import claim, consume_connection, Reconnect

pytestmark = pytest.mark.django_db


@pytest.fixture
def supervisor():
    value = Supervisor(intents=33554432, allowed_group='approved', stderr=io.StringIO())
    try:
        yield value
    finally:
        value.close()


@pytest.mark.parametrize('version', [None, 11, 12])
@pytest.mark.parametrize('has_processed_request', [False, True])
def test_startup_recovers_active_channel_without_pending_reconnect(setup, supervisor, version, has_processed_request):
    bot = setup[0]
    if version:
        bot.channel.interface_type = f'onebot_v{version}'; bot.channel.save()
    if has_processed_request:
        row = request_reconnect(setup)
        ChannelConnectionRequest.objects.filter(pk=row.pk).update(processed_generation=row.generation)
    process = MagicMock(); process.poll.return_value = None
    with patch('core.management.commands.run_connections.subprocess.Popen', return_value=process) as spawn:
        supervisor.tick()
        supervisor.tick()
    spawn.assert_called_once()
    assert spawn.call_args.args[0][2] == ('run_onebot_upstream' if version else 'run_gateway')
    if version is None:
        assert spawn.call_args.args[0][-2:] == ['--allowed-group','approved']


def test_worker_crash_is_restarted_after_backoff_without_reconnect_click(setup, supervisor):
    bot = setup[0]
    first = MagicMock(); first.poll.return_value = None
    second = MagicMock(); second.poll.return_value = None
    clock = [0]
    with patch('core.management.commands.run_connections.subprocess.Popen', side_effect=[first, second]) as spawn, patch(
            'core.management.commands.run_connections.time.monotonic', side_effect=lambda:clock[0]):
        supervisor.tick()
        first.poll.return_value = 1
        supervisor.tick()
        assert spawn.call_count == 1
        clock[0] = 1
        supervisor.tick()
        assert spawn.call_count == 1
        clock[0] = 3
        supervisor.tick()
        assert spawn.call_count == 2
    assert supervisor.children[bot.pk]['process'] == second


def test_supervisor_restart_waits_for_external_lease_then_recovers(setup, supervisor):
    bot = setup[0]
    _, _, token = claim(bot.pk,33554432)
    process = MagicMock(); process.poll.return_value = None
    with patch('core.management.commands.run_connections.subprocess.Popen',return_value=process) as spawn:
        supervisor.tick()
        spawn.assert_not_called()
        GatewaySession.objects.filter(bot=bot).update(lease_until=timezone.now()-timedelta(seconds=1))
        supervisor.tick()
        spawn.assert_called_once()


def test_hung_worker_is_terminated_after_lease_expiry_and_can_be_replaced(setup, supervisor):
    first = MagicMock(); first.poll.return_value = None
    second = MagicMock(); second.poll.return_value = None
    clock = [0]
    with patch('core.management.commands.run_connections.subprocess.Popen',side_effect=[first,second]) as spawn, patch(
            'core.management.commands.run_connections.time.monotonic',side_effect=lambda:clock[0]):
        supervisor.tick()
        clock[0] = 74; supervisor.tick(); first.terminate.assert_not_called()
        clock[0] = 76; supervisor.tick(); first.terminate.assert_called_once()
        clock[0] = 87; supervisor.tick(); first.kill.assert_called_once()
        first.poll.return_value = -9
        supervisor.tick()
        clock[0] = 90; supervisor.tick()
        assert spawn.call_count == 2


@pytest.mark.parametrize('change',['disabled','webhook','new_credentials'])
def test_config_changes_stop_old_child_and_launch_only_current_active_socket(setup, supervisor, change):
    bot = setup[0]
    process = MagicMock(); process.poll.return_value = None
    with patch('core.management.commands.run_connections.subprocess.Popen',return_value=process) as spawn:
        supervisor.tick()
        if change == 'disabled':
            Bot.objects.filter(pk=bot.pk).update(is_active=False)
        elif change == 'webhook':
            bot.channel.interface_type='qq_official_webhook'; bot.channel.save()
        else:
            Bot.objects.filter(pk=bot.pk).update(encrypted_secret='new-encrypted-value')
        supervisor.tick()
        process.terminate.assert_called_once()
        assert spawn.call_count == 1


def test_launch_failure_does_not_stop_other_channels_and_is_backed_off(setup, supervisor):
    other = Bot.objects.create(name='other',app_id='other-recovery-app')
    process = MagicMock(); process.poll.return_value = None
    clock=[0]
    with patch('core.management.commands.run_connections.subprocess.Popen',side_effect=[OSError(),process]) as spawn, patch(
            'core.management.commands.run_connections.time.monotonic',side_effect=lambda:clock[0]):
        supervisor.tick(); supervisor.tick()
        assert spawn.call_count == 2
    assert other.pk in supervisor.children and setup[0].pk not in supervisor.children


def test_gateway_without_ready_reconnects_even_if_heartbeats_are_acknowledged(setup):
    bot, _, token = claim(setup[0].pk,33554432)
    socket = MagicMock()
    socket.recv.side_effect = [json.dumps({'op':10,'d':{'heartbeat_interval':1000}})] + [json.dumps({'op':11})]*40
    now=[0]
    def tick():
        now[0] += 0.5
        return now[0]
    with patch('core.gateway.gateway_url',return_value='wss://api.bot.qq.com/websocket/'), patch(
            'core.gateway.access_token',return_value='synthetic'), patch('core.gateway.connect') as connect, patch(
            'core.gateway.time.monotonic',side_effect=tick):
        connect.return_value.__enter__.return_value = socket
        with pytest.raises(Reconnect,match='READY/RESUMED'):
            consume_connection(bot,token)
    assert not GatewaySession.objects.get(bot=bot).connected


@pytest.mark.parametrize('version',[11,12])
def test_real_worker_reconnects_after_socket_drop_and_supervisor_restarts_crashed_process(tmp_path,version):
    """Real processes and WS, with a separate synthetic-only database and no QQ calls."""
    import os
    from pathlib import Path
    import subprocess
    import sys
    settings_module = tmp_path / 'recovery_settings.py'
    settings_module.write_text('from config.settings import *\nDATABASES = {"default": {"ENGINE": '
        '"django.db.backends.sqlite3", "NAME": ' + repr(str(tmp_path / 'recovery.sqlite3')) + '}}\n',encoding='utf-8')
    env = {**os.environ,'DJANGO_SETTINGS_MODULE':'recovery_settings','DJANGO_DEBUG':'1',
           'DB_ENGINE':'sqlite','ONEBOT_UPSTREAM_ALLOW_PRIVATE':'1',
           'PYTHONPATH':str(tmp_path),'RECOVERY_VERSION':str(version)}
    source = r'''
import os, io, json, time, threading
import django
django.setup()
from django.core.management import call_command
from django.utils import timezone
from django.db import connection
from websockets.sync.server import serve
from core.models import Bot, Channel, Provider, OneBotUpstreamSession, ChannelConnectionRequest
from core.management.commands.run_connections import Supervisor
from core.onebot_upstream import configuration_digest
from core.services import encrypt_secret
call_command('migrate',verbosity=0)
version=int(os.environ['RECOVERY_VERSION'])
own={'platform':'synthetic','user_id':'10001' if version==11 else 'self:001'}
state={'drop':False,'events':0}
def handler(ws):
    # Identity action connections are separate from the quiet event connection.
    try:
        request=json.loads(ws.recv(timeout=.5))
    except TimeoutError:
        state['events']+=1
        while not state['drop']:
            time.sleep(.05)
        ws.close(code=1012)
        return
    action=request['action']
    data=({'user_id':10001} if action=='get_login_info' else
          {'good':True,'bots':[{'self':own,'online':True}]} if action=='get_status' else
          {'user_id':own['user_id']})
    ws.send(json.dumps({'status':'ok','retcode':0,'echo':request['echo'],'data':data}))
server=serve(handler,'127.0.0.1',0)
thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
p=Provider.objects.create(name='isolated-recovery')
c=Channel.objects.create(provider=p,name='synthetic',interface_type=f'onebot_v{version}',
    base_url=f'ws://127.0.0.1:{server.socket.getsockname()[1]}')
bot=Bot.objects.create(channel=c,name='synthetic',app_id=own['user_id'],encrypted_secret=encrypt_secret(''))
# Reproduce the original bug: there is no outstanding reconnect request.
ChannelConnectionRequest.objects.create(channel=c,generation=1,processed_generation=1,
    configuration=configuration_digest(bot))
supervisor=Supervisor(intents=33554432,allowed_group=None,stderr=io.StringIO())
def until(condition,seconds=25):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        supervisor.tick()
        if condition(): return
        time.sleep(.1)
    raise AssertionError('Timed out waiting for synthetic recovery')
def connected():
    return OneBotUpstreamSession.objects.filter(bot=bot,connected=True,lease_until__gt=timezone.now()).exists()
try:
    until(lambda: connected() and state['events']>=1)
    first=supervisor.children[bot.pk]['process']
    first_token=OneBotUpstreamSession.objects.get(bot=bot).lease_token
    state['drop']=True
    until(lambda: not connected())
    state['drop']=False
    until(lambda: connected() and state['events']>=2)
    assert supervisor.children[bot.pk]['process'].pid==first.pid
    # A hard crash cannot release its lease. Wait for it rather than shortening
    # production fencing; expire only this synthetic test's abandoned lease.
    first.kill();first.wait(timeout=5)
    supervisor.tick()
    OneBotUpstreamSession.objects.filter(bot=bot).update(lease_until=timezone.now())
    until(lambda: connected() and supervisor.children[bot.pk]['process'].pid!=first.pid)
    assert OneBotUpstreamSession.objects.get(bot=bot).lease_token!=first_token
    print(json.dumps({'version':version,'startup_without_pending_request':True,
        'real_ws_drop_recovered':True,'crashed_worker_replaced':True,'real_qq_operations':0}))
finally:
    state['drop']=True
    supervisor.close()
    server.shutdown();thread.join(timeout=5)
    connection.close()
'''
    result = subprocess.run([sys.executable,'-u','-c',source],cwd=Path(__file__).resolve().parents[1],
        env=env,capture_output=True,text=True,timeout=80)
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"crashed_worker_replaced": true' in result.stdout
