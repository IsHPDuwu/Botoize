import json
import time
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from .models import Bot, BotGrant, Event, EventOutbox, User
from .services import encrypt_secret
from .webhook_crypto import private_key

pytestmark = pytest.mark.django_db
SECRET = 'test-webhook-secret'


@pytest.fixture
def bot():
    instance = Bot.objects.create(name='bot', app_id='123', encrypted_secret=encrypt_secret(SECRET))
    user = User.objects.create_user('reader')
    BotGrant.objects.create(user=user, bot=instance, scopes=['events:read'])
    return instance


def send(bot, *, body=None, signature=None, app_id='123'):
    raw = body if body is not None else b'{"op":0,"id":"event1","t":"C2C_MESSAGE_CREATE","d":{}}'
    ts = str(int(time.time()))
    sig = signature if signature is not None else private_key(SECRET).sign(ts.encode() + raw).hex()
    return APIClient().post(f'/webhooks/qq/{bot.pk}/', raw, content_type='application/json', HTTP_X_BOT_APPID=app_id, HTTP_X_SIGNATURE_TIMESTAMP=ts, HTTP_X_SIGNATURE_ED25519=sig)


def test_verified_event_is_durable_and_duplicate_is_acknowledged(bot):
    assert send(bot).json() == {'op': 12}
    assert send(bot).status_code == 200
    assert Event.objects.count() == 1
    assert EventOutbox.objects.count() == 1


def test_rejects_unsigned_tampered_and_wrong_app_events(bot):
    assert send(bot, signature='').status_code == 401
    assert send(bot, signature='ab' * 64).status_code == 401
    assert send(bot, app_id='other').status_code == 403
    assert not Event.objects.exists()


def test_initial_challenge_does_not_create_event(bot):
    raw = json.dumps({'op': 13, 'd': {'plain_token': 'challenge', 'event_ts': '1725442341'}}).encode()
    response = send(bot, body=raw, signature='')
    assert response.status_code == 200
    assert response.json()['plain_token'] == 'challenge'
    assert len(response.json()['signature']) == 128
    assert not Event.objects.exists()


def test_database_failure_never_acknowledges(bot):
    with patch('core.events.EventOutbox.objects.bulk_create', side_effect=RuntimeError('database failed')):
        with pytest.raises(RuntimeError):
            send(bot)
    assert not Event.objects.exists()


def test_invalid_envelopes_and_inactive_bot(bot):
    assert send(bot, body=b'[]').status_code == 400
    assert send(bot, body=b'{"op":0,"t":"event"}').status_code == 400
    bot.is_active = False
    bot.save()
    assert send(bot).status_code == 404