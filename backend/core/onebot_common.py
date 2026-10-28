"""Version-independent protocol validation. Never exposes upstream credentials."""
import re


class OneBotError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)


def fields(params, allowed, required=()):
    if not isinstance(params, dict) or any(k not in params for k in required):
        raise OneBotError(10003, 'Missing or invalid parameters')
    if set(params) - set(allowed):
        raise OneBotError(10004, 'Unsupported parameter')


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.=+-]{1,256}', value):
        raise OneBotError(10003, 'Expected a string platform ID')
    return value


def message_identifier(value):
    # QQ message IDs and reference indexes are opaque data, not URL path parts.
    if (not isinstance(value, str) or not 1 <= len(value) <= 256
            or any(ord(char) <= 32 or ord(char) == 127 for char in value)):
        raise OneBotError(10003, 'Expected a nonempty string message ID without whitespace or control characters')
    return value


def integer(value, minimum=0, maximum=2147483647):
    if type(value) is not int or not minimum <= value <= maximum:
        raise OneBotError(10003, 'Invalid integer parameter')
    return value


def segment_fields(data, allowed, required=()):
    try:
        fields(data, allowed, required)
    except OneBotError as exc:
        raise OneBotError(10006 if exc.code == 10003 else 10007, exc.message) from None


def media_segment(data, version):
    # OB11 cache/proxy/timeout/type options affect an implementation's download
    # strategy, not QQ's media payload. Botoize downloads directly, without cache.
    name = 'file' if version == 11 else 'file_id'
    fields(data, set(data), {name})
    return {name: data[name]}
