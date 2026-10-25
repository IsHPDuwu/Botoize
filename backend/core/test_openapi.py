from django.test import Client
from django.urls import resolve

from .openapi import schema


def test_openapi_contains_only_real_routes_and_unique_operations():
    document = schema()
    ids = []
    for path, methods in document['paths'].items():
        match = resolve(path.replace('{id}', '1'))
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