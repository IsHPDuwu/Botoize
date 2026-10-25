"""Explicit OpenAPI contracts for platform management and relay HTTP APIs."""
from django.http import JsonResponse
from django.views.decorators.http import require_GET


STRING = {'type': 'string'}
INTEGER = {'type': 'integer', 'minimum': 1}
BOOLEAN = {'type': 'boolean'}
PASSWORD = {'type': 'string', 'format': 'password', 'writeOnly': True}
SCOPES = {'type': 'array', 'items': {'type': 'string', 'enum': [
    'events:read', 'messages:send', 'messages:delete', 'media:upload', 'query:read',
]}, 'uniqueItems': True}
DATE = {'type': ['string', 'null'], 'format': 'date-time'}


def object_schema(properties, required=()):
    return {'type': 'object', 'properties': properties, 'required': list(required), 'additionalProperties': False}


def operation(method, name, properties=None, required=(), public=False, bearer=False, status='200', response=None):
    data = {
        'operationId': name,
        'security': [] if public else [{'bearerKey': []}] if bearer else [{'sessionCookie': []}],
        'responses': {
            status: {'description': 'Success', **({'content': {'application/json': {'schema': response or {}}}} if status != '204' else {})},
            '400': {'description': 'Invalid request'},
            '401' if bearer else '403': {'description': 'Authentication, CSRF or authorization rejected'},
            '404': {'description': 'Not found or not visible'},
            '429': {'description': 'Rate limit or shared quota exhausted', 'headers': {'Retry-After': {'schema': {'type': 'integer'}}}},
        },
    }
    if method != 'get' and not bearer and not public:
        data['parameters'] = [{'in': 'header', 'name': 'X-CSRFToken', 'required': True, 'schema': STRING}]
    if properties is not None:
        data['requestBody'] = {'required': True, 'content': {'application/json': {
            'schema': object_schema(properties, required),
        }}}
    return data


def schema():
    paths = {}

    def add(path, method, name, **kwargs):
        op = operation(method, name, **kwargs)
        if '{id}' in path:
            op.setdefault('parameters', []).append({'in': 'path', 'name': 'id', 'required': True, 'schema': INTEGER})
        paths.setdefault(path, {})[method] = op

    add('/health/', 'get', 'health', public=True)
    add('/api/v1/auth/csrf/', 'get', 'csrf', public=True)
    add('/api/v1/auth/me/', 'get', 'currentUser')
    add('/api/v1/auth/login/', 'post', 'login', public=True,
        properties={'username': STRING, 'password': PASSWORD}, required=['username', 'password'])
    paths['/api/v1/auth/login/']['post']['parameters'] = [
        {'in': 'header', 'name': 'X-CSRFToken', 'required': True, 'schema': STRING},
    ]
    add('/api/v1/auth/logout/', 'post', 'logout', status='204')
    for route, name in [
        ('bots', 'Bots'), ('users', 'Users'), ('grants', 'Grants'), ('my-grants', 'MyGrants'),
        ('keys', 'Keys'), ('subscriptions', 'Subscriptions'), ('invitations', 'Invitations'), ('quotas', 'Quotas'),
    ]:
        add(f'/api/v1/{route}/', 'get', 'list' + name)
    for route, name in [('events', 'Events'), ('deliveries', 'Deliveries'), ('api-calls', 'ApiCalls')]:
        path = f'/api/v1/{route}/'
        add(path, 'get', 'list' + name)
        paths[path]['get']['parameters'] = [{'in': 'query', 'name': 'before', 'schema': {'type': 'string', 'pattern': '^[0-9]{1,18}$'}}]
    add('/api/v1/dashboard/overview/', 'get', 'dashboardOverview')
    paths['/api/v1/dashboard/overview/']['get']['parameters'] = [
        {'in': 'query', 'name': 'window_hours', 'schema': {'type': 'integer', 'enum': [24, 168, 720], 'default': 24}},
    ]
    add('/api/v1/bots/', 'post', 'createBot', status='201', properties={
        'name': STRING, 'app_id': STRING, 'secret': PASSWORD, 'password': PASSWORD,
    }, required=['name', 'app_id', 'secret', 'password'])
    add('/api/v1/bots/{id}/', 'patch', 'updateBot', properties={
        'name': STRING, 'app_id': STRING, 'secret': PASSWORD, 'is_active': BOOLEAN, 'password': PASSWORD,
    }, required=['password'])
    add('/api/v1/users/{id}/', 'patch', 'setAdminActive', properties={
        'is_active': BOOLEAN, 'password': PASSWORD,
    }, required=['is_active', 'password'])
    add('/api/v1/grants/', 'post', 'setGrant', properties={
        'user': INTEGER, 'bot': INTEGER, 'scopes': SCOPES, 'is_active': BOOLEAN, 'password': PASSWORD,
    }, required=['user', 'bot', 'scopes', 'password'])
    add('/api/v1/keys/', 'post', 'createKey', status='201', properties={
        'bot': INTEGER, 'name': STRING, 'scopes': SCOPES, 'expires_at': DATE, 'password': PASSWORD,
    }, required=['bot', 'name', 'scopes', 'password'])
    for path, name in [('/api/v1/keys/{id}/revoke/', 'revokeKey'),
                       ('/api/v1/owner/keys/{id}/revoke/', 'ownerRevokeKey')]:
        add(path, 'post', name, status='204', properties={'password': PASSWORD}, required=['password'])
    add('/api/v1/keys/{id}/rotate/', 'post', 'rotateKey', status='201', properties={
        'name': STRING, 'scopes': SCOPES, 'expires_at': DATE, 'password': PASSWORD,
    }, required=['password'])
    add('/api/v1/subscriptions/', 'post', 'setSubscription', status='201', properties={
        'bot': INTEGER, 'url': {'type': 'string', 'format': 'uri'}, 'is_active': BOOLEAN,
        'callback_secret': {**PASSWORD, 'minLength': 32, 'maxLength': 256}, 'password': PASSWORD,
    }, required=['bot', 'is_active', 'password'])
    paths['/api/v1/subscriptions/']['post']['responses']['204'] = {'description': 'Subscription disabled'}
    add('/api/v1/invitations/', 'post', 'createInvitation', status='201', properties={
        'expires_hours': {'type': 'integer', 'minimum': 1, 'maximum': 720, 'default': 72}, 'password': PASSWORD,
    }, required=['password'])
    add('/api/v1/invitations/accept/', 'post', 'acceptInvitation', public=True, status='201', properties={
        'token': PASSWORD, 'username': STRING, 'password': PASSWORD, 'email': {'type': 'string', 'format': 'email'},
    }, required=['token', 'username', 'password'])
    add('/api/v1/quotas/', 'post', 'setQuota', status='201', properties={
        'scope': {'type': 'string', 'enum': ['platform', 'bot', 'user', 'key']},
        'subject_id': {'type': 'integer', 'minimum': 0}, 'window_seconds': {'type': 'integer', 'enum': [60, 3600, 86400]},
        'limit': {'type': 'integer', 'minimum': 0, 'maximum': 1000000000}, 'is_active': BOOLEAN, 'password': PASSWORD,
    }, required=['scope', 'subject_id', 'window_seconds', 'limit', 'password'])
    paths['/api/v1/quotas/']['post']['responses']['200'] = {'description': 'Existing policy updated'}
    add('/api/v1/deliveries/{id}/attempts/', 'get', 'deliveryAttempts')
    add('/api/v1/deliveries/{id}/replay/', 'post', 'replayDelivery', status='202',
        properties={'password': PASSWORD}, required=['password'])
    add('/relay/v1/capabilities/', 'get', 'relayCapabilities', bearer=True)
    add('/relay/v1/events/', 'get', 'relayEvents', bearer=True)
    paths['/relay/v1/events/']['get']['parameters'] = [
        {'in': 'query', 'name': 'after', 'schema': {'type': 'string', 'pattern': '^[0-9]{1,18}$', 'default': '0'}},
        {'in': 'query', 'name': 'limit', 'schema': {'type': 'integer', 'minimum': 1, 'maximum': 100, 'default': 50}},
    ]
    for path in ('/relay/v1/events/', '/relay/v1/capabilities/'):
        paths[path]['get'].setdefault('parameters', []).append({'in': 'query', 'name': 'bot_id', 'schema': INTEGER})
    for methods in paths.values():
        for op in methods.values():
            for response in op['responses'].values():
                response.setdefault('headers', {})['X-Request-ID'] = {'schema': STRING}
    return {
        'openapi': '3.1.0',
        'info': {'title': 'QQ Bot Proxy Platform API', 'version': '0.1.0',
                 'description': 'Management and relay HTTP request contracts. Response payload schemas remain unconstrained where not yet formalized. Official proxy, Webhook signatures and WebSocket protocols are documented separately.'},
        'paths': paths,
        'components': {'securitySchemes': {
            'sessionCookie': {'type': 'apiKey', 'in': 'cookie', 'name': 'sessionid'},
            'bearerKey': {'type': 'http', 'scheme': 'bearer'},
        }},
    }


@require_GET
def openapi_schema(request):
    response = JsonResponse(schema())
    response['Cache-Control'] = 'no-store'
    return response