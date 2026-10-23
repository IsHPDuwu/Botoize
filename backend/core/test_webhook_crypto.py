import pytest

from .webhook_crypto import private_key, validation_response, verify_signature

SECRET = 'naOC0ocQE3shWLAfffVLB1rhYPG7'
BODY = b'{ "op": 0,"d": {}, "t": "GATEWAY_EVENT_NAME"}'
TIMESTAMP = '1725442341'
SIGNATURE = '865ad13a61752ca65e26bde6676459cd36cf1be609375b37bd62af366e1dc25a8dc789ba7f14e017ada3d554c671a911bfdf075ba54835b23391d509579ed002'


def test_official_public_key_vector_and_exact_body():
    public = private_key(SECRET).public_key().public_bytes_raw()
    assert list(public) == [215, 195, 98, 254, 120, 174, 248, 31, 242, 50, 135, 180, 147, 98, 139, 93, 176, 42, 60, 79, 227, 11, 33, 94, 77, 25, 96, 155, 93, 118, 103, 58]
    signature = private_key(SECRET).sign(TIMESTAMP.encode() + BODY).hex()
    assert verify_signature(SECRET, TIMESTAMP, BODY, signature, now=int(TIMESTAMP))
    assert not verify_signature(SECRET, TIMESTAMP, BODY + b' ', signature, now=int(TIMESTAMP))
    assert not verify_signature('wrong', TIMESTAMP, BODY, signature, now=int(TIMESTAMP))


def test_official_validation_vector():
    result = validation_response('DG5g3B4j9X2KOErG', 'Arq0D5A61EgUu4OxUvOp', TIMESTAMP)
    assert result['signature'] == '87befc99c42c651b3aac0278e71ada338433ae26fcb24307bdc5ad38c1adc2d01bcfcadc0842edac85e85205028a1132afe09280305f13aa6909ffc2d652c706'


@pytest.mark.parametrize('offset', [-301, 301])
def test_rejects_old_and_future_timestamps(offset):
    assert not verify_signature(SECRET, TIMESTAMP, BODY, SIGNATURE, now=int(TIMESTAMP) + offset)


@pytest.mark.parametrize('signature', ['', 'zz' * 64, 'ab' * 63, 'ab ' * 64])
def test_rejects_malformed_signature(signature):
    assert not verify_signature(SECRET, TIMESTAMP, BODY, signature, now=int(TIMESTAMP))


def test_empty_secret_and_invalid_challenge_are_rejected():
    with pytest.raises(ValueError):
        private_key('')
    with pytest.raises(ValueError):
        validation_response(SECRET, '', TIMESTAMP)
    with pytest.raises(ValueError):
        validation_response(SECRET, 'token', 'not-a-timestamp')