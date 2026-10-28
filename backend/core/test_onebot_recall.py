"""Recall opaque QQ IDs through the real adapter/transport; no live deletes."""
from unittest.mock import patch

import pytest

from .test_onebot_v12 import setup, action
from .models import OneBotMessage
from .onebot_ids import virtual_id
from .official import OfficialCredentialError, delete_message

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize('version', [11, 12])
@pytest.mark.parametrize('mid,encoded', [
    ('ROBOT1.0_message!opaque/id==?x#y%', 'ROBOT1.0_message%21opaque%2Fid%3D%3D%3Fx%23y%25'),
    ('..', '%2E%2E'),
])
def test_recall_opaque_id_is_encoded_once_and_repeat_is_local(setup, version, mid, encoded):
    row = OneBotMessage.objects.create(bot=setup[1], message_id=mid, is_direct=False,
        target_id='group', conversation_type='group', created_by=setup[0], sent_at=100)
    value = virtual_id(setup[1], 'message', mid) if version == 11 else mid
    name = 'delete_msg' if version == 11 else 'delete_message'
    with patch('core.official._request', return_value=(204, b'', {})) as remote:
        result = action(setup, name, {'message_id': value}, version=version)
        assert result['retcode'] == 0, result
        remote.assert_called_once_with(setup[1], 'DELETE', 'v2/groups/group/messages/' + encoded, '')
        assert action(setup, name, {'message_id': value}, version=version)['retcode'] == 0
        remote.assert_called_once()
    row.refresh_from_db()
    assert row.deleted


@pytest.mark.parametrize('code,reason', [(40064004, 'two-minute'), (40062003, 'permission'), (50065001, 'recall failed')])
def test_recall_rejection_reports_safe_official_reason_and_keeps_record(setup, code, reason):
    import json
    row = OneBotMessage.objects.create(bot=setup[1], message_id='failed', is_direct=False,
        target_id='group', conversation_type='group', created_by=setup[0], sent_at=100)
    with patch('core.official._request', return_value=(400, json.dumps({'code': code, 'message': 'secret-body'}).encode(), {})):
        result = action(setup, 'delete_message', {'message_id': 'failed'})
    assert result['retcode'] == 34000 and reason in result['message']
    assert str(code) in result['message'] and 'secret-body' not in result['message']
    row.refresh_from_db()
    assert not row.deleted


def test_recall_network_failure_is_not_retried_or_marked_deleted(setup):
    row = OneBotMessage.objects.create(bot=setup[1], message_id='network-failed', is_direct=False,
        target_id='group', conversation_type='group', created_by=setup[0], sent_at=100)
    with patch('core.official._request', side_effect=OfficialCredentialError(reason='timeout')) as remote:
        result = action(setup, 'delete_message', {'message_id': row.message_id})
    assert result['retcode'] == 33000 and 'timeout' in result['message']
    remote.assert_called_once()
    row.refresh_from_db()
    assert not row.deleted


def test_recall_collection_cannot_be_selected_through_id():
    with patch('core.official._request') as remote:
        with pytest.raises(ValueError):
            delete_message(None, 'app/getAppAccessToken', message_id='opaque/id')
        remote.assert_not_called()
