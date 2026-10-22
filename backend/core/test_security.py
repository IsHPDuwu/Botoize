from io import StringIO
from unittest.mock import patch
import pytest
from django.core.management import call_command, CommandError
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient
from rest_framework.exceptions import PermissionDenied, AuthenticationFailed
from .models import User, Bot, BotGrant, ApiKey, AuditLog
from .services import issue_key, authorize, encrypt_secret, decrypt_secret, owner_change

pytestmark = pytest.mark.django_db
PASSWORD = 'test-password-very-long'


@pytest.fixture
def setup():
    a = User.objects.create_user('a', password=PASSWORD)
    b = User.objects.create_user('b', password=PASSWORD)
    o = User.objects.create_user('owner', password=PASSWORD, role='Owner')
    bot = Bot.objects.create(name='bot', app_id='123', encrypted_secret=encrypt_secret('official-secret'))
    other = Bot.objects.create(name='other', app_id='456', encrypted_secret=encrypt_secret('other-secret'))
    BotGrant.objects.create(user=a, bot=bot, scopes=['query:read', 'messages:send'])
    BotGrant.objects.create(user=b, bot=other, scopes=['query:read'])
    return a, b, o, bot, other


def client(user):
    c = APIClient()
    c.force_login(user)
    return c


def test_admin_isolation(setup):
    a, b, o, bot, other = setup
    c = client(a)
    assert [x['id'] for x in c.get('/api/v1/bots/').json()] == [bot.pk]
    key, token = issue_key(b, other, 'b key', ['query:read'])
    assert c.get('/api/v1/keys/').json() == []
    assert c.post(f'/api/v1/keys/{key.pk}/revoke/', {'password': PASSWORD}).status_code == 404
    assert c.post(f'/api/v1/owner/keys/{key.pk}/revoke/', {'password': PASSWORD}).status_code == 403
    assert c.get('/api/v1/grants/').status_code == 403
    assert c.post('/api/v1/bots/', {}).status_code == 403
    assert c.post('/api/v1/keys/', {'bot': other.pk, 'name': 'x', 'scopes': [], 'password': PASSWORD}, format='json').status_code == 404


def test_key_single_bot_scopes_and_hash(setup):
    a, b, o, bot, other = setup
    k, token = issue_key(a, bot, 'key', ['query:read'])
    assert token not in k.digest and token not in k.prefix
    assert authorize(token, bot.pk, 'query:read')[0].pk == k.pk
    with pytest.raises(PermissionDenied):
        authorize(token, other.pk)
    with pytest.raises(PermissionDenied):
        authorize(token, scope='messages:send')
    with pytest.raises(PermissionDenied):
        issue_key(a, bot, 'bad', ['media:upload'])
    c = client(a)
    assert c.patch(f'/api/v1/keys/{k.pk}/', {'bot': other.pk}).status_code == 404
    c.credentials(HTTP_AUTHORIZATION='Bearer ' + token)
    assert c.get('/relay/v1/capabilities/').json()['scopes'] == ['query:read']
    assert c.get(f'/relay/v1/capabilities/?bot_id={other.pk}').status_code == 403
    assert c.post('/qq/v2/test', {'bot_id': other.pk}).status_code == 403
    assert c.get('/qq/v2/test').status_code == 501


def test_revoke_and_regrant_do_not_revive(setup):
    a, b, o, bot, other = setup
    k1, t1 = issue_key(a, bot, 'one', ['query:read'])
    k2, t2 = issue_key(a, bot, 'two', ['query:read'])
    assert client(a).post(f'/api/v1/keys/{k1.pk}/revoke/', {'password': PASSWORD}).status_code == 204
    with pytest.raises(AuthenticationFailed):
        authorize(t1)
    authorize(t2)
    c = client(o)
    payload = {'user': a.pk, 'bot': bot.pk, 'scopes': ['query:read'], 'password': PASSWORD, 'is_active': False}
    assert c.post('/api/v1/grants/', payload, format='json').status_code == 200
    with pytest.raises(PermissionDenied):
        authorize(t2)
    payload['is_active'] = True
    assert c.post('/api/v1/grants/', payload, format='json').status_code == 200
    with pytest.raises(PermissionDenied):
        authorize(t2)


@pytest.mark.parametrize('field,value', [('is_active', False), ('role', 'Owner')])
def test_live_user_state(setup, field, value):
    a, b, o, bot, other = setup
    k, token = issue_key(a, bot, 'key', ['query:read'])
    c = client(a)
    User.objects.filter(pk=a.pk).update(**{field: value})
    if field == 'is_active':
        with pytest.raises(AuthenticationFailed):
            authorize(token)
        assert c.get('/api/v1/keys/').status_code == 403
    else:
        assert c.get('/api/v1/auth/me/').json()['role'] == 'Owner'
        with pytest.raises(PermissionDenied):
            authorize(token, scope='messages:send')


def test_owner_console_constraints(setup):
    a, b, o, bot, other = setup
    with pytest.raises(CommandError):
        call_command('owner', 'revoke', 'owner')
    call_command('owner', 'grant', 'a')
    call_command('owner', 'revoke', 'owner')
    with pytest.raises(CommandError):
        call_command('owner', 'revoke', 'a')
    User.objects.filter(pk=b.pk).update(is_active=False)
    with pytest.raises(CommandError):
        call_command('owner', 'grant', 'b')
    with patch('core.management.commands.owner.getpass', return_value=PASSWORD):
        with pytest.raises(CommandError):
            call_command('owner', 'init', 'new')
    out = StringIO()
    call_command('owner', 'list', stdout=out)
    assert 'a active=True' in out.getvalue()
    assert AuditLog.objects.filter(action='owner.grant').exists()


def test_owner_init():
    with patch('core.management.commands.owner.getpass', return_value=PASSWORD):
        call_command('owner', 'init', 'first')
    assert User.objects.get(username='first').role == 'Owner'
    with pytest.raises(ValueError):
        owner_change('first', 'revoke')


def test_csrf_login_logout(setup):
    c = APIClient(enforce_csrf_checks=True)
    assert c.post('/api/v1/auth/login/', {'username': 'a', 'password': PASSWORD}).status_code == 403
    csrf = c.get('/api/v1/auth/csrf/').json()['csrfToken']
    r = c.post('/api/v1/auth/login/', {'username': 'a', 'password': PASSWORD}, HTTP_X_CSRFTOKEN=csrf)
    assert r.status_code == 200
    assert c.get('/api/v1/auth/me/').json()['role'] == 'Admin'
    assert c.post('/api/v1/auth/logout/').status_code == 403
    assert c.post('/api/v1/auth/logout/', HTTP_X_CSRFTOKEN=r.json()['csrfToken']).status_code == 204
    assert c.get('/api/v1/auth/me/').status_code == 403


def test_secret_and_field_injection(setup):
    a, b, o, bot, other = setup
    assert 'official-secret' not in bot.encrypted_secret
    assert decrypt_secret(bot) == 'official-secret'
    c = client(o)
    assert 'secret' not in str(c.get('/api/v1/bots/').json())
    payload = {'name': 'key', 'bot': bot.pk, 'scopes': [], 'password': PASSWORD, 'role': 'Owner'}
    assert client(a).post('/api/v1/keys/', payload, format='json').status_code == 400
    assert c.get('/admin/').status_code == 404
    assert c.post('/api/v1/users/', {'role': 'Owner'}).status_code == 404


def test_key_creation_expiry_and_secret_once(setup):
    a, b, o, bot, other = setup
    c = client(a)
    payload = {'bot': bot.pk, 'name': 'new', 'scopes': ['query:read'], 'password': PASSWORD}
    r = c.post('/api/v1/keys/', payload, format='json')
    assert r.status_code == 201
    token = r.json()['token']
    assert token not in str(c.get('/api/v1/keys/').json())
    ApiKey.objects.filter(pk=r.json()['id']).update(expires_at=timezone.now() - timedelta(seconds=1))
    with pytest.raises(AuthenticationFailed):
        authorize(token)
    payload['scopes'] = ['invalid']
    assert c.post('/api/v1/keys/', payload, format='json').status_code == 400


def test_bearer_not_session_and_health(setup):
    a, *_ = setup
    c = client(a)
    assert c.get('/relay/v1/capabilities/').status_code == 401
    assert APIClient().get('/health/').json() == {'status': 'ok'}


def test_owner_requires_explicit_grant(setup):
    a, b, o, bot, other = setup
    with pytest.raises(PermissionDenied):
        issue_key(o, bot, 'owner key', ['query:read'])
    assert client(o).post('/api/v1/keys/', {'bot': bot.pk, 'name': 'x', 'scopes': [], 'password': PASSWORD}, format='json').status_code == 404


def test_disabled_bot_and_grant_scopes(setup):
    a, b, o, bot, other = setup
    k, token = issue_key(a, bot, 'key', ['query:read', 'messages:send'])
    BotGrant.objects.filter(user=a, bot=bot).update(scopes=['query:read'])
    assert authorize(token)[1] == ['query:read']
    with pytest.raises(PermissionDenied):
        authorize(token, scope='messages:send')
    Bot.objects.filter(pk=bot.pk).update(is_active=False)
    with pytest.raises(AuthenticationFailed):
        authorize(token)


def test_owner_bot_creation_and_reauth(setup):
    a, b, o, bot, other = setup
    c = client(o)
    data = {'name': 'new', 'app_id': 'new-app', 'secret': 'never-return-this', 'password': 'wrong'}
    assert c.post('/api/v1/bots/', data, format='json').status_code == 403
    data['password'] = PASSWORD
    r = c.post('/api/v1/bots/', data, format='json')
    assert r.status_code == 201
    assert 'never-return-this' not in str(r.json())
    assert decrypt_secret(Bot.objects.get(pk=r.json()['id'])) == 'never-return-this'