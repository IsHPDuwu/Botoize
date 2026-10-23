from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from .models import AuditLog, Bot, BotGrant, HttpSubscription, User
from .subscriptions import set_subscription, subscription_is_current, validate_callback

pytestmark = pytest.mark.django_db


@pytest.fixture
def grant():
    user = User.objects.create_user('subscriber')
    bot = Bot.objects.create(name='bot', app_id='subscription-test', encrypted_secret='unused')
    return BotGrant.objects.create(user=user, bot=bot, scopes=['events:read'])


def test_subscription_commands_and_revision_isolation(grant):
    output = StringIO()
    call_command('subscription', 'set', str(grant.pk), 'https://example.com/events', stdout=output)
    sub = HttpSubscription.objects.select_related('grant__user', 'grant__bot').get()
    assert subscription_is_current(sub)
    grant.revision += 1
    grant.save()
    sub.refresh_from_db()
    assert not subscription_is_current(sub)
    sub = set_subscription(grant.pk, 'https://example.com/new')
    assert sub.grant_revision == grant.revision
    assert HttpSubscription.objects.count() == 1
    assert subscription_is_current(sub)
    call_command('subscription', 'disable', str(grant.pk), stdout=output)
    sub.refresh_from_db()
    assert not subscription_is_current(sub)
    assert AuditLog.objects.filter(action='subscription.set').count() == 2
    assert AuditLog.objects.filter(action='subscription.disable').count() == 1


@pytest.mark.parametrize('reason', ['user', 'bot', 'grant', 'scope'])
def test_inactive_grant_rejected(grant, reason):
    sub = set_subscription(grant.pk, 'https://example.com/events')
    if reason == 'user':
        grant.user.is_active = False
        grant.user.save()
    elif reason == 'bot':
        grant.bot.is_active = False
        grant.bot.save()
    elif reason == 'grant':
        grant.is_active = False
        grant.save()
    else:
        grant.scopes = []
        grant.save()
    sub.refresh_from_db()
    assert not subscription_is_current(sub)
    with pytest.raises(ValueError):
        set_subscription(grant.pk, 'https://example.com/events')


@pytest.mark.parametrize('url', [
    'http://example.com/events', 'https://user:password@example.com/events',
    'https://example.com/#secret', 'https://example.com:8443/events',
    'https://example.com/\nheader', 'not-a-url', None,
])
def test_invalid_callback(url):
    with pytest.raises(ValueError):
        validate_callback(url)


def test_missing_grant_command():
    with pytest.raises(CommandError):
        call_command('subscription', 'set', '99999', 'https://example.com/events')