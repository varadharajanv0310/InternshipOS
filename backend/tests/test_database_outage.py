"""The hosted API must explain an outage without exposing driver diagnostics."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from internshipos import auth, main, service


@pytest.mark.parametrize('path', ['/api/health', '/api/dashboard'])
def test_neon_quota_error_is_sanitized(path, monkeypatch, caplog):
    def unavailable(*args):
        raise OperationalError(None, None, RuntimeError(
            'driver host=private.example; Your account or project has exceeded the quota.'
        ))

    monkeypatch.setattr(main.engine, 'connect', unavailable)
    monkeypatch.setattr(service, 'dashboard', unavailable)
    monkeypatch.setattr(auth, 'PASSWORD', 'test-only-password')
    # No startup hooks or actual database calls are needed to simulate this outage.
    client = TestClient(main.app, cookies={auth.COOKIE: auth.sign_token({'scope': 'owner'})})
    try:
        response = client.get(path)
    finally:
        client.close()
    assert response.status_code == 503
    assert response.json()['code'] == 'quota_exceeded'
    assert 'quota' in response.json()['detail']
    assert 'retry-after' not in response.headers
    assert 'private.example' not in response.text + caplog.text


def test_query_failure_is_not_a_connection_outage(monkeypatch):
    def query_failed(*args):
        raise OperationalError('SELECT * FROM missing_table', None, RuntimeError('table not found'))

    monkeypatch.setattr(service, 'dashboard', query_failed)
    client = TestClient(main.app, raise_server_exceptions=False,
                        cookies={auth.COOKIE: auth.sign_token({'scope': 'owner'})})
    assert client.get('/api/dashboard').status_code == 500
