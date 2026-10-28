import copy
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from .test_companions import setup, add_mapping, primary_message, slave_message
from .companions import fingerprint, flush_due, message_for, reconcile
from .events import ingest_event
from .models import CompanionObservation
from .onebot import invoke
from .onebot_ids import virtual_id
from .websocket import read_onebot_page
from .onebot_upstream_events import receive_event

pytestmark = pytest.mark.django_db


def with_metadata(event):
    event = copy.deepcopy(event)
    event['d']['msg_elements'] = [{'text': {'text': ' /aqt'}, 'auth_token': 'redact-me'}]
    event['d']['mentions'] = [{'id': 'member', 'access_token': 'redact-me'}]
    return event


@pytest.mark.parametrize('version', [11, 12])
def test_metadata_does_not_become_command_text_in_events_or_get_msg(setup, version):
    bot, _, _, _, key, token = setup
    event, _ = ingest_event(bot, with_metadata(primary_message(text=' /aqt')))
    CompanionObservation.objects.update(due_at=timezone.now() - timedelta(seconds=1))
    flush_due()
    payload = read_onebot_page(token, 0, 123 if version == 11 else 'self', version=version)[0]['payload']
    assert payload['message'] == [{'type': 'text', 'data': {'text': ' /aqt'}}]
    assert payload['qq.msg_elements'] == [{'text': {'text': ' /aqt'}}]
    assert payload['qq.mentions'] == [{'id': 'member'}]
    assert payload['raw_message' if version == 11 else 'alt_message'] == ' /aqt'
    # Canonical history remains lossless, including for records stored by older versions.
    assert any(s['type'] == 'qq.msg_elements' for s in message_for(event).segments)
    result = invoke(bot, key.scopes, 'get_msg',
        {'message_id': virtual_id(bot, 'message', 'official-message')}, key=key).data
    assert result['retcode'] == 0, result
    assert result['data']['message'] == payload['message']
    assert result['data']['qq.msg_elements'] == payload['qq.msg_elements']


@pytest.mark.parametrize('slave_first', [True, False])
def test_parallel_metadata_does_not_break_primary_companion_quote_pairing(setup, slave_first):
    bot, slave, _, _, _, token = setup
    add_mapping(setup)
    primary = with_metadata(primary_message(text=' /aqt'))
    companion = slave_message(slave, text='/aqt')
    if slave_first:
        receive_event(slave, companion)
        ingest_event(bot, primary)
    else:
        ingest_event(bot, primary)
        receive_event(slave, companion)
    observations = CompanionObservation.objects.filter(channel=bot.channel)
    assert observations.count() == 2 and observations.filter(paired=True).count() == 2
    assert virtual_id(bot, 'message', 'official-message') == 40004
    page = read_onebot_page(token, 0, 123)
    assert len(page) == 1
    assert page[0]['payload']['message'] == [{'type':'text','data':{'text':'/aqt'}}]


def test_reconcile_repairs_fingerprint_from_previous_metadata_representation(setup):
    bot, slave = setup[:2]
    add_mapping(setup)
    def old_fingerprint(row):
        if any(s['type'] == 'qq.msg_elements' for s in row.segments):
            return 'old-metadata-fingerprint'
        return fingerprint(row)
    with patch('core.companions.fingerprint', side_effect=old_fingerprint):
        primary, _ = ingest_event(bot, with_metadata(primary_message(text=' /aqt')))
        receive_event(slave, slave_message(slave, text='/aqt'))
    observation = CompanionObservation.objects.get(event=primary, side='primary')
    assert not observation.paired
    assert reconcile(observation)
    assert virtual_id(bot, 'message', 'official-message') == 40004
