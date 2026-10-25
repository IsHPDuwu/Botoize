"""Explicit OpenAPI contracts for platform management and relay HTTP APIs."""
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from .services import SCOPES as SCOPE_NAMES
from .official_routes import OPERATIONS
import re
from copy import deepcopy


STRING = {'type': 'string'}
INTEGER = {'type': 'integer', 'minimum': 1}
BOOLEAN = {'type': 'boolean'}
PASSWORD = {'type': 'string', 'format': 'password', 'writeOnly': True}
SCOPES = {'type': 'array', 'items': {'type': 'string', 'enum': sorted(SCOPE_NAMES)}, 'uniqueItems': True}
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
        for parameter in re.findall(r'\{(\w+)\}', path):
            op.setdefault('parameters', []).append({'in': 'path', 'name': parameter, 'required': True, 'schema': INTEGER if parameter == 'id' else STRING})
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
    # Channel=Bot and Models=conversation. The old Bot-as-Model contract is rejected.
    policy = {'all_conversations': BOOLEAN, 'conversations': {'type': 'array', 'items': INTEGER, 'uniqueItems': True}}
    conversation = object_schema({'id': INTEGER, 'name': STRING, 'isDirect': BOOLEAN, 'userid': STRING, 'groupid': STRING}, ['name', 'isDirect'])
    channel = object_schema({'id': INTEGER, 'bot_id': INTEGER, 'name': STRING, 'base_url': {'type': 'string', 'format': 'uri'},
                             'interface_type': {'type': 'string', 'enum': ['qq_official_websocket', 'qq_official_webhook']},
                             'app_id': STRING, 'secret': PASSWORD, 'is_active': BOOLEAN,
                             'models': {'type': 'array', 'items': conversation}}, ['name', 'interface_type', 'app_id', 'is_active', 'models'])
    provider_input = {'name': STRING, 'channels': {'type': 'array', 'items': channel, 'minItems': 1, 'maxItems': 100}}
    add('/api/v1/providers/', 'get', 'listProviders')
    add('/api/v1/providers/{id}/', 'get', 'getProvider')
    add('/api/v1/providers/', 'post', 'createProvider', properties=provider_input, required=['name', 'channels'], status='201')
    add('/api/v1/providers/{id}/', 'patch', 'updateProvider', properties=provider_input, required=['name', 'channels'])
    add('/api/v1/channels/{id}/sync/', 'post', 'backfillConversations', properties={})
    add('/api/v1/upstream-interfaces/', 'get', 'listUpstreamInterfaces')
    add('/api/v1/scopes/', 'get', 'listScopes')
    add('/api/v1/keys/{id}/', 'get', 'getKey')
    add('/api/v1/keys/{id}/', 'patch', 'updateKey', properties={'name': STRING, 'scopes': SCOPES, 'expires_at': DATE, **policy})
    add('/api/v1/keys/{id}/copy/', 'post', 'copyKey', properties={})
    for route in ('/api/v1/grants/', '/api/v1/keys/', '/api/v1/keys/{id}/rotate/'):
        paths[route]['post']['requestBody']['content']['application/json']['schema']['properties'].update(policy)
    # Compatibility accepts ignored legacy password fields, but they are not part
    # of any non-authentication management contract and are never required.
    for path, methods in paths.items():
        if path.startswith('/api/v1/') and '/auth/' not in path and path != '/api/v1/invitations/accept/':
            for op in methods.values():
                body = op.get('requestBody', {}).get('content', {}).get('application/json', {}).get('schema')
                if body:
                    body['properties'].pop('password', None)
                    body['required'] = [name for name in body['required'] if name != 'password']
    for index, (method, path, scope) in enumerate(OPERATIONS):
        add('/qq/' + path, method.lower(), f'officialOperation{index}', bearer=True,
            response={'$ref': '#/components/schemas/OfficialResponse'})
        paths['/qq/' + path][method.lower()]['description'] = f'Raw official response passthrough; requires {scope} and unrestricted conversation grants. QQ permissions still apply.'

    def ref(name):
        return {'$ref': '#/components/schemas/' + name}

    def array(item):
        return {'type': 'array', 'items': item}

    bot = object_schema({'id': INTEGER, 'name': STRING, 'app_id': STRING, 'is_active': BOOLEAN, 'channel_id': INTEGER})
    key = object_schema({'id': INTEGER, 'bot': INTEGER, 'name': STRING, 'prefix': STRING, 'scopes': SCOPES,
                         'expires_at': DATE, 'revoked_at': DATE, 'grant_revision': INTEGER, 'can_copy': BOOLEAN, **policy})
    grant = object_schema({'id': INTEGER, 'user_id': INTEGER, 'bot_id': INTEGER, 'bot': ref('Bot'), 'scopes': SCOPES,
                           'is_active': BOOLEAN, 'revision': INTEGER, 'parent_id': {'type': ['integer', 'null']},
                           'models': array(ref('Conversation')), **policy})
    provider = object_schema({'id': INTEGER, **deepcopy(provider_input)})
    provider['properties']['channels']['items'] = {**channel, 'properties': {k: v for k, v in channel['properties'].items() if k != 'secret'}}
    schemas = {
        'Bot': bot, 'Conversation': conversation, 'Provider': provider, 'Key': key, 'Grant': grant,
        'IssuedKey': {**key, 'properties': {**key['properties'], 'token': STRING, 'rotated_key': INTEGER}},
        'User': object_schema({'id': INTEGER, 'username': STRING, 'role': {'type': 'string', 'enum': ['Owner', 'Admin']}, 'is_active': BOOLEAN, 'csrfToken': STRING}),
        'Event': object_schema({'id': INTEGER, 'bot': INTEGER, 'event_id': STRING, 'event_type': STRING, 'received_at': DATE, 'payload': {'type': 'object', 'additionalProperties': True}}),
        'Delivery': object_schema({'id': INTEGER, 'event_id': STRING, 'bot': INTEGER, 'user': INTEGER, 'state': {'type': 'string', 'enum': ['pending', 'processing', 'failed', 'delivered', 'cancelled']}, 'attempts': {'type': 'integer'}, 'available_at': DATE, 'lease_until': DATE}),
        'Subscription': object_schema({'id': INTEGER, 'bot': INTEGER, 'url': {'type': 'string', 'format': 'uri'}, 'is_active': BOOLEAN, 'is_current': BOOLEAN, 'grant_revision': INTEGER}),
        'Interface': object_schema({'interface_type': STRING, 'label': STRING, 'implemented': BOOLEAN}),
        'Attempt': object_schema({'id': INTEGER, 'generation': INTEGER, 'attempt_number': INTEGER, 'state': STRING, 'http_status': {'type': ['integer', 'null']}, 'error_code': STRING, 'started_at': DATE, 'finished_at': DATE}),
        'ApiCall': object_schema({'id': INTEGER, 'request_id': STRING, 'bot': {'type': ['integer', 'null']}, 'api_key': {'type': ['integer', 'null']}, 'method': STRING, 'path': STRING, 'message_type': STRING, 'replayed': {'type': ['boolean', 'null']}, 'status_code': INTEGER, 'duration_ms': {'type': 'integer'}, 'created_at': DATE}),
        'Invitation': object_schema({'id': INTEGER, 'expires_at': DATE, 'used_at': DATE, 'accepted_by': {'type': ['integer', 'null']}, 'created_at': DATE}),
        'Quota': object_schema({'id': INTEGER, 'scope': STRING, 'subject_id': {'type': 'integer'}, 'window_seconds': INTEGER, 'limit': {'type': 'integer'}, 'is_active': BOOLEAN, 'used': {'type': 'integer'}, 'resets_at': {'type': 'integer'}}),
        'OfficialResponse': {'description': 'QQ-owned raw JSON response; no normalization or guarantee of upstream success.', 'type': ['object', 'array', 'string', 'number', 'boolean', 'null'], 'additionalProperties': True},
    }
    responses = {'health': object_schema({'status': STRING}), 'csrf': object_schema({'csrfToken': STRING}),
                 'currentUser': ref('User'), 'login': ref('User'), 'acceptInvitation': ref('User'),
                 'createBot': ref('Bot'), 'updateBot': ref('Bot'), 'setAdminActive': ref('User'),
                 'setGrant': ref('Grant'), 'createKey': ref('IssuedKey'), 'rotateKey': ref('IssuedKey'),
                 'getKey': ref('Key'), 'updateKey': ref('Key'), 'copyKey': object_schema({'token': STRING}),
                 'getProvider': ref('Provider'), 'createProvider': ref('Provider'), 'updateProvider': ref('Provider'),
                 'setSubscription': object_schema({'id': INTEGER, 'grant_revision': INTEGER}),
                 'setQuota': object_schema({'id': INTEGER}), 'createInvitation': object_schema({'id': INTEGER, 'token': STRING, 'expires_at': DATE}),
                 'replayDelivery': object_schema({'id': INTEGER, 'state': STRING, 'attempt_generation': INTEGER, 'warning': STRING}),
                 'backfillConversations': object_schema({'source': STRING, 'created': {'type': 'integer'}, 'upstream_enumeration_supported': BOOLEAN, 'realtime_discovery': BOOLEAN, 'models': array(ref('Conversation'))}),
                 'listScopes': SCOPES, 'deliveryAttempts': array(ref('Attempt'))}
    for name, model in [('Bots', 'Bot'), ('Users', 'User'), ('Grants', 'Grant'), ('MyGrants', 'Grant'), ('Keys', 'Key'),
                        ('Providers', 'Provider'), ('Subscriptions', 'Subscription'), ('Invitations', 'Invitation'), ('Quotas', 'Quota'), ('UpstreamInterfaces', 'Interface')]:
        responses['list' + name] = array(ref(model))
    for name, field, model in [('Events', 'events', 'Event'), ('Deliveries', 'deliveries', 'Delivery'), ('ApiCalls', 'calls', 'ApiCall')]:
        responses['list' + name] = object_schema({field: array(ref(model)), 'has_more': BOOLEAN, 'next_before': {'type': ['string', 'null']}})
    responses['relayEvents'] = object_schema({'events': array(object_schema({'cursor': STRING, 'payload': {'type': 'object', 'additionalProperties': True}, 'received_at': DATE})), 'next_cursor': STRING, 'has_more': BOOLEAN})
    responses['relayCapabilities'] = object_schema({'bot_id': INTEGER, 'scopes': SCOPES, 'proxy_enabled': BOOLEAN, 'websocket_enabled': BOOLEAN, 'operations': array(STRING), 'unrestricted_conversations': BOOLEAN, **policy})
    responses['dashboardOverview'] = object_schema({**{name: {'type': 'integer'} for name in ['window_hours', 'bot_count', 'active_bot_count', 'event_count', 'delivery_count', 'delivered_count', 'pending_count', 'processing_count', 'failed_count', 'cancelled_count']}, 'window_start': DATE, 'generated_at': DATE})
    for methods in paths.values():
        for op in methods.values():
            if op['operationId'] in responses:
                for status, response in op['responses'].items():
                    if status.startswith('2') and status != '204':
                        response['content'] = {'application/json': {'schema': responses[op['operationId']]}}
    for methods in paths.values():
        for op in methods.values():
            for response in op['responses'].values():
                response.setdefault('headers', {})['X-Request-ID'] = {'schema': STRING}
    return {
        'openapi': '3.1.0',
        'info': {'title': 'QQ Bot Proxy Platform API', 'version': '0.1.0',
                 'description': 'Management and relay request/response contracts. Official management routes share the scope registry and preserve QQ response payloads. Webhook signatures and WebSocket protocols are documented separately.'},
        'paths': paths,
        'components': {'schemas': schemas, 'securitySchemes': {
            'sessionCookie': {'type': 'apiKey', 'in': 'cookie', 'name': 'sessionid'},
            'bearerKey': {'type': 'http', 'scheme': 'bearer'},
        }},
    }


@require_GET
def openapi_schema(request):
    response = JsonResponse(schema())
    response['Cache-Control'] = 'no-store'
    return response
