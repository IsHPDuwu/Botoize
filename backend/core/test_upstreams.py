from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

import pytest
from django.core.cache import cache

from .official import access_token, get_self, OfficialCredentialError, open_upstream
from .services import encrypt_secret
from .upstreams import validate_base_url
from .delivery import UnsafeDestination


def test_official_origin_uses_explicit_operator_proxy(settings):
    from urllib.request import Request, ProxyHandler
    settings.QQ_HTTP_PROXY = 'http://127.0.0.1:7890'
    with patch('core.official.build_opener') as build:
        with open_upstream(Request('https://api.bot.qq.com/users/@me')):
            pass
    handlers = build.call_args.args
    proxy = next(handler for handler in handlers if isinstance(handler, ProxyHandler))
    assert proxy.proxies == {'https': 'http://127.0.0.1:7890'}


def test_official_transport_reads_standard_https_proxy_environment(settings, monkeypatch):
    from urllib.request import Request, ProxyHandler, build_opener
    settings.QQ_HTTP_PROXY = None
    monkeypatch.delenv('https_proxy', raising=False)
    monkeypatch.setenv('HTTPS_PROXY', 'http://127.0.0.1:7890')
    observed = []
    def make_opener(*handlers):
        opener = build_opener(*handlers)
        observed.extend(handler for handler in opener.handlers if isinstance(handler, ProxyHandler))
        mock = MagicMock()
        return mock
    with patch('core.official.build_opener', side_effect=make_opener):
        with open_upstream(Request('https://api.bot.qq.com/users/@me')):
            pass
    assert observed[0].proxies['https'] == 'http://127.0.0.1:7890'


def test_custom_origin_does_not_use_operator_proxy(settings):
    from urllib.request import Request
    settings.QQ_HTTP_PROXY = 'http://127.0.0.1:7890'
    with patch('core.delivery.resolve_public', return_value='93.184.216.34'), \
         patch('core.delivery.PinnedHTTPSConnection', return_value=connection()) as tls, \
         patch('core.official.build_opener') as build:
        with open_upstream(Request('https://example.com/users/@me')):
            pass
    build.assert_not_called()
    tls.assert_called_once_with('example.com', '93.184.216.34')


@pytest.mark.parametrize('url', ['http://example.com', 'https://localhost', 'https://127.0.0.1',
    'https://[::1]', 'https://user:password@example.com', 'https://example.com:8443',
    'https://example.com/a/../b', 'https://example.com/%2e%2e', 'https://example.com?token=x',
    'https://example.com#fragment', 'https://example.com\\evil', 'https://example.com/\n'])
def test_base_url_rejects_unsafe_syntax(url):
    with pytest.raises(ValueError):
        validate_base_url(url)


def bot(url='https://example.com/prefix'):
    return SimpleNamespace(pk=1, app_id='app', encrypted_secret=encrypt_secret('private-secret'), channel=SimpleNamespace(base_url=url))


def connection(status=200, body=b'{"access_token":"token","expires_in":7200}'):
    conn = MagicMock()
    conn.getresponse.return_value.status = status
    conn.getresponse.return_value.headers = {}
    conn.getresponse.return_value.read.return_value = body
    return conn


def test_custom_base_uses_pinned_public_dns_and_token_cache_isolated_by_origin_and_prefix():
    cache.clear()
    instance = bot()
    conn = connection()
    with patch('core.delivery.resolve_public', return_value='93.184.216.34') as dns, \
         patch('core.delivery.PinnedHTTPSConnection', return_value=conn) as tls:
        assert access_token(instance) == 'token'
        assert access_token(instance) == 'token'
        assert conn.request.call_count == 1
        assert conn.request.call_args.args[:2] == ('POST', '/prefix/app/getAppAccessToken')
        tls.assert_called_with('example.com', '93.184.216.34')
        instance.channel.base_url = 'https://example.com/other-prefix'
        access_token(instance)
        instance.channel.base_url = 'https://other.example.com/other-prefix'
        access_token(instance)
        assert dns.call_count == 3 and conn.request.call_count == 3
        assert conn.close.call_count == 3


def test_private_dns_blocks_before_credentials_leave_and_redirect_never_followed():
    cache.clear()
    with patch('core.delivery.resolve_public', side_effect=UnsafeDestination), \
         patch('core.delivery.PinnedHTTPSConnection') as tls:
        with pytest.raises(OfficialCredentialError):
            access_token(bot())
        tls.assert_not_called()
    conn = connection(status=302, body=b'')
    conn.getresponse.return_value.headers = {'Location': 'https://evil.example'}
    with patch('core.official.access_token', return_value='cached'), \
         patch('core.delivery.resolve_public', return_value='93.184.216.34'), \
         patch('core.delivery.PinnedHTTPSConnection', return_value=conn):
        with pytest.raises(OfficialCredentialError):
            get_self(bot())
        assert conn.request.call_count == 1
        assert conn.request.call_args.kwargs['headers']['Authorization'] == 'QQBot cached'
        assert conn.close.call_count == 1
