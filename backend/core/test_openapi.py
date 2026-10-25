from django.test import Client
from django.urls import resolve
import re

from .openapi import schema


def test_openapi_contains_only_real_routes_and_unique_operations():
    document = schema()
    ids = []
    for path, methods in document['paths'].items():
        match = resolve(re.sub(r'\{\w+\}', '1', path))
        for method, operation in methods.items():
            assert hasattr(match.func.view_class, method)
            ids.append(operation['operationId'])
            assert operation['responses']
    assert len(ids) == len(set(ids))


def test_schema_endpoint_has_no_credentials_or_runtime_dependency():
    response = Client().get('/api/v1/openapi.json')
    assert response.status_code == 200
    assert response.json()['openapi'] == '3.1.0'
    document = response.json()
    assert document['paths']['/relay/v1/events/']['get']['security'] == [{'bearerKey': []}]
    assert document['paths']['/api/v1/invitations/accept/']['post']['security'] == []
    fields = document['paths']['/api/v1/grants/']['post']['requestBody']['content']['application/json']['schema']
    assert fields['additionalProperties'] is False
    assert 'messages:delete' in fields['properties']['scopes']['items']['enum']


def test_current_contract_has_responses_and_no_nonlogin_password_or_stale_scopes():
    from .services import SCOPES
    from .official_routes import OPERATIONS
    document = schema()
    for path, methods in document['paths'].items():
        for operation in methods.values():
            for status, response in operation['responses'].items():
                if status.startswith('2') and status != '204':
                    assert response['content']['application/json']['schema']
            body = operation.get('requestBody', {}).get('content', {}).get('application/json', {}).get('schema')
            if path.startswith('/api/v1/') and '/auth/' not in path and path != '/api/v1/invitations/accept/' and body:
                assert 'password' not in body['properties'] and 'password' not in body['required']
    fields = document['paths']['/api/v1/keys/']['post']['requestBody']['content']['application/json']['schema']['properties']
    assert set(fields['scopes']['items']['enum']) == SCOPES
    assert 'all_conversations' in fields and 'conversations' in fields
    for method, path, _ in OPERATIONS:
        assert method.lower() in document['paths']['/qq/' + path]
    channel = document['paths']['/api/v1/providers/']['post']['requestBody']['content']['application/json']['schema']['properties']['channels']['items']
    assert 'secret' in channel['properties']
