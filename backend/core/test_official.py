import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.error import URLError

import pytest
from django.core.cache import cache

from .official import OfficialCredentialError, access_token, NoRedirect, TOKEN_URL
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