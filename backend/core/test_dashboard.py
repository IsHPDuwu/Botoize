from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from .models import Bot, BotGrant, Event, EventOutbox, HttpSubscription, User


@pytest.mark.django_db
def test_dashboard_overview_scopes_admin_to_current_grants():
    owner = User.objects.create_user(username='owner', password='password')
    admin = User.objects.create_user(username='admin', password='password')
    owner.role = User.Role.OWNER
    owner.save(update_fields=['role'])
    first = Bot.objects.create(name='first', app_id='first', encrypted_secret='secret')
    second = Bot.objects.create(name='second', app_id='second', encrypted_secret='secret')
    grant = BotGrant.objects.create(user=admin, bot=first, scopes=['events:read'])
    old_event = Event.objects.create(bot=first, event_id='old', event_type='old', payload={})
    recent_event = Event.objects.create(bot=first, event_id='recent', event_type='recent', payload={})
    Event.objects.filter(pk=old_event.pk).update(received_at=timezone.now() - timedelta(days=2))
    subscription = HttpSubscription.objects.create(grant=grant, url='https://example.com', grant_revision=grant.revision)
    EventOutbox.objects.create(event=recent_event, grant=grant, grant_revision=grant.revision, state='delivered', subscription=subscription, subscription_revision=subscription.revision)
    Event.objects.create(bot=second, event_id='hidden', event_type='hidden', payload={})

    client = Client()
    assert client.login(username='admin', password='password')
    response = client.get('/api/v1/dashboard/overview/?window_hours=24')
    assert response.status_code == 200
    assert response.json()['bot_count'] == 1
    assert response.json()['event_count'] == 1
    assert response.json()['delivered_count'] == 1

    client.logout()
    assert client.login(username='owner', password='password')
    response = client.get('/api/v1/dashboard/overview/?window_hours=24')
    assert response.status_code == 200
    assert response.json()['bot_count'] == 2
    assert response.json()['event_count'] == 2


@pytest.mark.django_db
def test_dashboard_overview_rejects_unsupported_window():
    User.objects.create_user(username='admin', password='password')
    client = Client()
    assert client.login(username='admin', password='password')
    response = client.get('/api/v1/dashboard/overview/?window_hours=1')
    assert response.status_code == 400


@pytest.mark.django_db
def test_dashboard_overview_hides_event_metrics_without_events_read():
    admin = User.objects.create_user(username='admin', password='password')
    bot = Bot.objects.create(name='bot', app_id='bot', encrypted_secret='secret')
    grant = BotGrant.objects.create(user=admin, bot=bot, scopes=['query:read'])
    event = Event.objects.create(bot=bot, event_id='hidden', event_type='hidden', payload={})
    EventOutbox.objects.create(event=event, grant=grant, grant_revision=grant.revision, state='delivered')

    client = Client()
    assert client.login(username='admin', password='password')
    response = client.get('/api/v1/dashboard/overview/?window_hours=24')

    assert response.status_code == 200
    assert response.json()['bot_count'] == 1
    assert response.json()['event_count'] == 0
    assert response.json()['delivery_count'] == 0
    assert response.json()['delivered_count'] == 0
