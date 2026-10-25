from unittest.mock import patch

import pytest
from django.core.management.base import CommandError

from .management.commands.verify_live_qq import credentials


@pytest.mark.parametrize('reference', [False, True])
def test_local_credentials_and_explicit_secret_file_are_read_without_logging(reference):
    config = "id: '123456'\nsecret: " + ('[在 SECRET.txt 中读取]' if reference else 'test-secret')
    with patch('pathlib.Path.read_text', side_effect=[config, 'test-secret\n'] if reference else [config]):
        from pathlib import Path
        assert credentials(Path('config.txt')) == ('123456', 'test-secret')


def test_description_is_never_sent_as_credential():
    from pathlib import Path
    with patch('pathlib.Path.read_text', return_value='id: 123\nsecret: 这里是说明文字'):
        with pytest.raises(CommandError, match='whitespace or non-ASCII'):
            credentials(Path('config.txt'))


def test_missing_credentials_are_redacted():
    from pathlib import Path
    with patch('pathlib.Path.read_text', return_value='id: 123'):
        with pytest.raises(CommandError, match='values were not logged'):
            credentials(Path('config.txt'))


@pytest.mark.django_db
def test_ip_allowlist_failure_is_redacted_revokes_key_and_cleans_fixtures():
    from io import StringIO
    import json
    from django.core.management import call_command
    from .models import User, Provider, Channel, Bot, ApiKey, Conversation
    output = StringIO()
    models = (User, Provider, Channel, Bot, ApiKey, Conversation)
    before = {model: set(model.objects.values_list('pk', flat=True)) for model in models}
    with patch('core.management.commands.verify_live_qq.credentials', return_value=('123456', 'test-secret')), \
         patch('core.management.commands.verify_live_qq.get_self', return_value=(401, b'{"code":11298,"err_code":40023002}', {})), \
         patch('core.management.commands.verify_live_qq.gateway_url') as gateway:
        call_command('verify_live_qq', send=True, stdout=output)
    report = json.loads(output.getvalue())
    assert report['official_identity_reason'] == 'source_ip_not_allowlisted'
    assert report['same_token_copy'] and report['revoked_key_rejected']
    assert report['temporary_resources_cleaned'] and 'send_http' not in report
    assert 'test-secret' not in output.getvalue()
    gateway.assert_not_called()
    for model in models:
        assert set(model.objects.values_list('pk', flat=True)) == before[model]
