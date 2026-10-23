from io import StringIO
import json

import pytest
from django.core.management import call_command

from .events import ingest_event
from .models import Bot, BotGrant, EventOutbox, User
from .outbox import scan_outbox

pytestmark = pytest.mark.django_db


def pending():
    bot = Bot.objects.create(name='bot', app_id='1', encrypted_secret='unused')
    user = User.objects.create_user('reader')
    grant = BotGrant.objects.create(user=user, bot=bot, scopes=['events:read'])
    ingest_event(bot, {'op': 0, 'id': 'event', 't': 'C2C_MESSAGE_CREATE', 'd': {}})
    return grant, EventOutbox.objects.get()


@pytest.mark.parametrize('reason', ['revision', 'user', 'bot', 'scope', 'grant'])
def test_scan_cancels_invalid_work_without_revival(reason):
    grant, row = pending()
    if reason == 'revision':
        grant.revision += 1
    elif reason == 'user':
        grant.user.is_active = False
        grant.user.save()
    elif reason == 'bot':
        grant.bot.is_active = False
        grant.bot.save()
    elif reason == 'scope':
        grant.scopes = []
    else:
        grant.is_active = False
    grant.save()
    result = scan_outbox()
    assert result['cancelled'] == 1 and not result['ready']
    row.refresh_from_db()
    assert row.state == 'cancelled'
    grant.is_active = True
    grant.scopes = ['events:read']
    grant.save()
    assert scan_outbox()['scanned'] == 0


def test_scan_leaves_valid_work_pending_and_is_repeatable():
    grant, row = pending()
    assert scan_outbox()['ready'] == [row.pk]
    assert scan_outbox()['ready'] == [row.pk]
    row.refresh_from_db()
    assert row.state == 'pending'
    assert scan_outbox(after=row.pk)['scanned'] == 0
    output = StringIO()
    call_command('scan_outbox', stdout=output)
    assert json.loads(output.getvalue())['ready'] == [row.pk]