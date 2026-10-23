import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.error import URLError

import pytest
from django.core.cache import cache

from .official import OfficialCredentialError, access_token, get_self, send_message, NoRedirect, TOKEN_URL, MAX_RESPONSE_BYTES
from .services import encrypt_secret


@pytest.fixture(autouse=True)
def clean_cache():
    cache.clear()
    yield
    cache.clear()


def bot():
    return SimpleNamespace(pk=1, app_id='123', encrypted_secret=encrypt_secret('private-secret'))


def transport(data):
    opener = MagicMock()
    response = opener.open.return_value.__enter__.return_value
    response.status = 200
    response.read.return_value = json.dumps(data).encode()
    return opener


def test_token_uses_fixed_origin_and_cached_encrypted_credentials():
    instance = bot()
    opener = transport({'access_token': 'private-token', 'expires_in': '7200'})
    with patch('core.official.build_opener', return_value=opener):
        assert access_token(instance) == 'private-token'
        assert access_token(instance) == 'private-token'
        assert opener.open.call_count == 1
        request = opener.open.call_args.args[0]
        assert request.full_url == TOKEN_URL
        assert json.loads(request.data) == {'appId': '123', 'clientSecret': 'private-secret'}
        instance.encrypted_secret = encrypt_secret('rotated')
        access_token(instance)
        assert opener.open.call_count == 2


@pytest.mark.parametrize('data', [
    {'code': 100016, 'message': 'private-secret'},
    {'access_token': 'bad\r\nheader', 'expires_in': 7200},
    {'access_token': 'token', 'expires_in': True},
    {'access_token': 'token', 'expires_in': 0},
    {'access_token': 'token', 'expires_in': 7201},
    [],
])
def test_bad_response_never_leaks_official_secrets(data):
    with patch('core.official.build_opener', return_value=transport(data)):
        with pytest.raises(OfficialCredentialError) as error:
            access_token(bot())
        assert 'private-secret' not in str(error.value)


def test_network_failure_is_redacted_and_redirects_are_disabled():
    opener = MagicMock()
    opener.open.side_effect = URLError('private-secret')
    with patch('core.official.build_opener', return_value=opener):
        with pytest.raises(OfficialCredentialError, match='unavailable'):
            access_token(bot())
    assert NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.test') is None


def test_self_query_uses_only_official_authorization_and_raw_response():
    opener = MagicMock()
    response = opener.open.return_value.__enter__.return_value
    response.code = 200
    response.headers = {'Content-Type': 'application/json', 'Set-Cookie': 'do-not-forward'}
    response.read.return_value = b'{"id":"bot"}'
    with patch('core.official.access_token', return_value='official-token'), patch('core.official.build_opener', return_value=opener):
        status, raw, headers = get_self(bot(), 'a=1&a=2')
    request = opener.open.call_args.args[0]
    assert request.full_url == 'https://api.bot.qq.com/users/@me?a=1&a=2'
    assert request.get_header('Authorization') == 'QQBot official-token'
    assert status == 200 and raw == b'{"id":"bot"}'
    assert 'Set-Cookie' not in headers


def test_send_transport_preserves_body_and_uses_fixed_origin():
    opener = MagicMock()
    response = opener.open.return_value.__enter__.return_value
    response.code = 202
    response.headers = {}
    response.read.return_value = b'{}'
    raw = b'{ "msg_seq": 9 }'
    with patch('core.official.access_token', return_value='token'), patch('core.official.build_opener', return_value=opener):
        assert send_message(bot(), 'v2/groups/openid/messages', raw)[0] == 202
    request = opener.open.call_args.args[0]
    assert request.full_url == 'https://api.bot.qq.com/v2/groups/openid/messages'
    assert request.data == raw and request.method == 'POST'
    assert opener.open.call_count == 1


@pytest.mark.parametrize('path', ['https://evil.test', 'v2/users/../messages', 'v2/users/a%2fb/messages', 'v2/users/a/messages/extra'])
def test_send_transport_rejects_unregistered_path(path):
    with patch('core.official.access_token') as credentials:
        with pytest.raises(ValueError):
            send_message(bot(), path, b'{}')
        credentials.assert_not_called()


@pytest.mark.parametrize('code,size', [(302, 0), (200, MAX_RESPONSE_BYTES + 1)])
def test_self_query_rejects_redirect_and_oversized_response(code, size):
    opener = MagicMock()
    response = opener.open.return_value.__enter__.return_value
    response.code = code
    response.read.return_value = b'x' * size
    with patch('core.official.access_token', return_value='token'), patch('core.official.build_opener', return_value=opener):
        with pytest.raises(OfficialCredentialError):
            get_self(bot())