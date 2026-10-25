import io
import wave

from .live_message_cases import synthetic_media


def test_media_fixtures_are_small_synthetic_and_use_documented_types():
    samples = synthetic_media()
    assert samples['image'][0] == 1 and samples['image'][2].startswith(b'\x89PNG\r\n\x1a\n')
    assert samples['voice'][0] == 3
    with wave.open(io.BytesIO(samples['voice'][2])) as audio:
        assert audio.getnchannels() == 1 and audio.getframerate() == 16000 and audio.getnframes() == 16000
    assert samples['file'][0] == 4 and b'No user data' in samples['file'][2]
    assert all(len(item[2]) < 500_000 for item in samples.values())


def test_live_matrix_uses_only_approved_group_and_replays_identical_sends():
    from io import StringIO
    from types import SimpleNamespace
    from unittest.mock import patch
    from .management.commands.verify_live_backend import Command
    from .management.commands.verify_live_qq import TARGET
    sends, uploads = {}, []
    relay = SimpleNamespace(idempotency=None)
    def request(path, method='GET', body=None):
        assert path.startswith(f'/qq/v2/groups/{TARGET}/') and method == 'POST'
        if path.endswith('/files'):
            uploads.append(body)
            assert body['srv_send_msg'] is False
            return 200, {'file_info':'opaque-not-printed'}, {}
        replay = relay.idempotency in sends
        if replay:
            assert sends[relay.idempotency] == body
        else:
            sends[relay.idempotency] = body
        return 200, {'id':'test-message','ext_info':{'ref_idx':'test-reference'}}, {'Idempotency-Replayed':'true' if replay else 'false'}
    relay.request = request
    output, report = StringIO(), {}
    with patch('core.live_message_cases.synthetic_video', return_value=(2,'test.mp4',b'test-video')):
        Command(stdout=output).verify_message_types(relay, 'test-run', report)
    rows = [row for row in report['message_types'] if row['stage'] == 'send']
    assert {row['type'] for row in rows} == {'text','markdown','keyboard','reference','image','video','voice','file'}
    assert all(row['accepted'] and row['message_id_returned'] and row['idempotent_replay'] for row in rows)
    assert len(sends) == 8 and len(uploads) == 4
    assert 'opaque-not-printed' not in output.getvalue()
