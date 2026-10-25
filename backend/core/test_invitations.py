from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from .invitations import accept_invitation, create_invitation
from .models import AuditLog, Invitation, User

pytestmark = pytest.mark.django_db
PASSWORD = 'invitation-password'


@pytest.fixture
def owner():
    return User.objects.create_user('invite-owner', password=PASSWORD, role=User.Role.OWNER)


def test_invitation_is_one_time_and_creates_only_admin(owner):
    invitation, token = create_invitation(owner, 24)
    assert token.startswith('qqi_')
    assert token not in invitation.token_digest
    user = accept_invitation(token, 'new-admin', 'new-admin-password')
    assert user.role == User.Role.ADMIN and user.is_active
    invitation.refresh_from_db()
    assert invitation.used_at and invitation.accepted_by_id == user.pk
    with pytest.raises(ValueError, match='invalid or expired'):
        accept_invitation(token, 'second-admin', 'second-admin-password')
    assert not User.objects.filter(username='second-admin').exists()
    assert AuditLog.objects.filter(action='invitation.create').count() == 1
    assert AuditLog.objects.filter(action='invitation.accept').count() == 1


def test_expired_invitation_does_not_create_user(owner):
    invitation, token = create_invitation(owner, 1)
    Invitation.objects.filter(pk=invitation.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    with pytest.raises(ValueError, match='invalid or expired'):
        accept_invitation(token, 'expired-admin', 'expired-password')
    assert not User.objects.filter(username='expired-admin').exists()


def test_invitation_endpoint_is_owner_only_and_does_not_allow_role(owner):
    admin = User.objects.create_user('regular-admin', password=PASSWORD)
    owner_client = APIClient()
    owner_client.force_login(owner)
    response = owner_client.post('/api/v1/invitations/', {'password': PASSWORD, 'expires_hours': 48}, format='json')
    assert response.status_code == 201
    assert set(response.json()) == {'id', 'token', 'expires_at'}
    assert Invitation.objects.get(pk=response.json()['id']).accepted_by_id is None
    assert owner_client.get('/api/v1/invitations/').status_code == 200
    admin_client = APIClient()
    admin_client.force_login(admin)
    assert admin_client.post('/api/v1/invitations/', {'password': PASSWORD}).status_code == 403
    assert admin_client.get('/api/v1/invitations/').status_code == 403
    assert owner_client.post('/api/v1/invitations/', {'password': PASSWORD, 'role': 'Owner'}, format='json').status_code == 400


def test_accept_endpoint_is_public_and_rejects_unknown_fields(owner):
    _, token = create_invitation(owner)
    client = APIClient()
    response = client.post('/api/v1/invitations/accept/', {
        'token': token, 'username': 'accepted-admin', 'password': 'accepted-password', 'role': 'Owner',
    }, format='json')
    assert response.status_code == 400
    assert not User.objects.filter(username='accepted-admin').exists()
    response = client.post('/api/v1/invitations/accept/', {
        'token': token, 'username': 'accepted-admin', 'password': 'accepted-password',
    }, format='json')
    assert response.status_code == 201
    assert response.json()['role'] == 'Admin'