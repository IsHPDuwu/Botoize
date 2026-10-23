from unittest.mock import patch

import pytest

from .events import ingest_event
from .models import Bot, BotGrant, Event, EventOutbox, User

pytestmark = pytest.mark.django_db


def resources():
    bot = Bot.objects.create(name='test', app_id='1', encrypted_secret='unused')
    user = User.objects.create_user('admin')
    grant = BotGrant.objects.create(bot=bot, user=user, scopes=['events:read'])
    return bot, grant


def envelope(event_id='event-1'):
    return {'op': 0, 'id': event_id, 't': 'C2C_MESSAGE_CREATE', 'd': {'id': 'message'}}


def test_ingestion_is_idempotent_and_does_not_expand_old_recipients():
    bot, grant = resources()
    event, created = ingest_event(bot, envelope())
    assert created and EventOutbox.objects.get().grant_revision == 1
    other = User.objects.create_user('later')
    BotGrant.objects.create(bot=bot, user=other, scopes=['events:read'])
    duplicate, created = ingest_event(bot, envelope())
    assert not created and duplicate.pk == event.pk
    assert EventOutbox.objects.count() == 1
    grant.revision = 2
    grant.save()
    assert EventOutbox.objects.get().grant_revision == 1


def test_outbox_failure_rolls_back_event():
    bot, grant = resources()
    with patch('core.events.EventOutbox.objects.bulk_create', side_effect=RuntimeError('failed')):
        with pytest.raises(RuntimeError):
            ingest_event(bot, envelope())
    assert not Event.objects.exists()


@pytest.mark.parametrize('change', ['inactive_grant', 'inactive_user', 'missing_scope'])
def test_ineligible_grants_are_not_snapshotted(change):
    bot, grant = resources()
    if change == 'inactive_grant':
        grant.is_active = False
    elif change == 'missing_scope':
        grant.scopes = ['query:read']
    else:
        grant.user.is_active = False
        grant.user.save()
    grant.save()
    ingest_event(bot, envelope())
    assert Event.objects.count() == 1
    assert not EventOutbox.objects.exists()


def test_same_event_id_is_isolated_by_bot():
    bot, grant = resources()
    other = Bot.objects.create(name='other', app_id='2', encrypted_secret='unused')
    ingest_event(bot, envelope())
    ingest_event(other, envelope())
    assert Event.objects.count() == 2