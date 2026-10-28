"""Official quote indexes can differ; NapCat rich text can include alternatives."""
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from .test_companions import setup, primary_message, slave_message, add_mapping
from .events import ingest_event
from .onebot import invoke
from .onebot_ids import virtual_id, original_id
from .onebot_events import visible_segments
from .onebot_upstream_events import receive_event
from .models import OneBotMessage

pytestmark = pytest.mark.django_db


def quoted_payload():
    event = primary_message(text=' /aqt', mid='command')
    event['d']['message_scene'] = {'ext': ['msg_idx=command-index', 'ref_msg_idx=different-quote-index']}
    event['d']['msg_elements'] = [{'message_type': 103, 'msg_idx': 'different-quote-index', 'content': 'unique quote text'}]
    return event


@pytest.mark.parametrize('version', [11, 12])
def test_unresolved_quote_is_preserved_downstream_without_text_guessing(setup, version):
    from .onebot_events import message_event
    bot, _, _, _, key, _ = setup
    ingest_event(bot, primary_message(text='unique quote text', mid='target',
        at=timezone.now() - timedelta(minutes=15)))
    event, _ = ingest_event(bot, quoted_payload())
    result = message_event(bot, event.payload, 123 if version == 11 else 'self', version, key)
    reply = result['message'][0]
    assert reply['type'] == 'reply'
    value = reply['data']['id' if version == 11 else 'message_id']
    original = original_id(bot, 'message', value) if version == 11 else value
    assert original == 'different-quote-index'
    assert result['message'][1] == {'type': 'text', 'data': {'text': ' /aqt'}}


def test_paired_companion_quote_links_a_changed_official_index(setup):
    from .test_message_links import quote, primary_quote, target_primary
    from .onebot import message_record
    bot, slave, _, _, key, _ = setup
    add_mapping(setup)
    ingest_event(bot, target_primary())
    receive_event(slave, slave_message(slave))
    assert virtual_id(bot, 'message', 'target!message') == 40004
    event = primary_quote()
    event['d']['message_scene']['ext'] = ['msg_idx=quoted/index', 'ref_msg_idx=rotated-reference']
    ingest_event(bot, event)
    receive_event(slave, quote(slave))
    row = message_record(bot, key, 'rotated-reference', 12)
    assert row.message_id == 'target!message'
    assert row.reference == 'target/index'  # Keep the original sendable reference.
    assert virtual_id(bot, 'message', 'rotated-reference') == 40004


def test_napcat_markdown_and_plain_fallback_are_one_message_for_quote_and_pairing(setup):
    bot, slave, _, _, key, _ = setup
    add_mapping(setup)
    text = 'same text once'
    event = slave_message(slave, text=text)
    event['message'].insert(0, {'type': 'markdown', 'data': {'content': text}})
    receive_event(slave, event)
    ingest_event(bot, primary_message(text=text))
    row = OneBotMessage.objects.filter(bot=bot, incoming=True).first()
    assert visible_segments(row, key) == [{'type': 'text', 'data': {'text': text}}]
    result = invoke(bot, key.scopes, 'get_msg', {'message_id': 40004}, key=key).data
    assert result['retcode'] == 0, result
    assert result['data']['message'] == [{'type': 'text', 'data': {'text': text}}]
    assert virtual_id(bot, 'message', 'official-message') == 40004
