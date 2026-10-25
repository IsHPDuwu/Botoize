import pytest
from django.conf import settings
from django.test import Client

from core.models import User

pytestmark = pytest.mark.django_db


def test_local_vite_origins_are_trusted_when_using_development_settings():
    assert 'http://localhost:5173' in settings.CSRF_TRUSTED_ORIGINS
    assert 'http://127.0.0.1:5173' in settings.CSRF_TRUSTED_ORIGINS


def test_login_accepts_default_local_vite_origin():
    User.objects.create_user(username='owner', password='development-password', role='Owner')
    client = Client(enforce_csrf_checks=True)
    csrf_response = client.get('/api/v1/auth/csrf/')
    token = csrf_response.json()['csrfToken']
    response = client.post(
        '/api/v1/auth/login/',
        data={'username': 'owner', 'password': 'development-password'},
        content_type='application/json',
        HTTP_ORIGIN='http://localhost:5173',
        HTTP_X_CSRFTOKEN=token,
    )
    assert response.status_code == 200
    assert response.json()['role'] == 'Owner'
