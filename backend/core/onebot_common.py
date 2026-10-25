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


def integer(value, minimum=0, maximum=2147483647):
    if type(value) is not int or not minimum <= value <= maximum:
        raise OneBotError(10003, 'Invalid integer parameter')
    return value


def segment_fields(data, allowed, required=()):
    try:
        fields(data, allowed, required)
    except OneBotError as exc:
        raise OneBotError(10006 if exc.code == 10003 else 10007, exc.message) from None
