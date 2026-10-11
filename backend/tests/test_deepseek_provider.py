"""Native DeepSeek integration checks, entirely offline."""
import json

import httpx
import pytest
from fastapi import HTTPException

from internshipos.providers import Provider, get_provider


def configured(monkeypatch):
    monkeypatch.setenv('AI_PROVIDER', 'deepseek')
    monkeypatch.setenv('AI_API_KEY', 'fixture-secret')
    monkeypatch.setenv('AI_STRONG_MODEL', 'deepseek-flash')
    monkeypatch.setenv('AI_CHEAP_MODEL', 'deepseek-flash')
    return get_provider()


def test_native_configuration_and_secret_redaction(monkeypatch):
    provider = configured(monkeypatch)
    assert provider.base_url == 'https://api.deepseek.com'
    assert provider.rates == (.30, 1.20)
    assert provider.max_output_tokens == 8192
    assert 'fixture-secret' not in repr(provider)
    assert get_provider(False).model == 'deepseek-flash'
    monkeypatch.delenv('AI_API_KEY')
    monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)
    with pytest.raises(HTTPException):
        get_provider()


def test_deepseek_json_and_reasoning_contract(monkeypatch):
    provider = configured(monkeypatch)
    original = httpx.Client

    def handle(request):
        payload = json.loads(request.content)
        assert str(request.url) == 'https://api.deepseek.com/chat/completions'
        assert payload['response_format'] == {'type': 'json_object'}
        assert payload['thinking'] == {'type': 'enabled'}
        assert payload['reasoning_effort'] == 'high'
        assert payload['max_tokens'] == 8192
        assert 'JSON' in payload['messages'][0]['content']
        return httpx.Response(200, json={
            'choices': [{'finish_reason': 'stop', 'message': {
                'content': json.dumps({'text': 'Python API project.', 'fact_ids': ['project:one'], 'unknowns': []}),
                'reasoning_content': 'Private model reasoning is not returned to the caller.',
            }}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 180,
                      'completion_tokens_details': {'reasoning_tokens': 150}},
        })

    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs))
    draft, incoming, outgoing = provider.generate('Use supplied facts.', '{}')
    assert draft == {'text': 'Python API project.', 'fact_ids': ['project:one'], 'unknowns': []}
    assert (incoming, outgoing) == (100, 180)  # Reasoning is already included; do not double count.


@pytest.mark.parametrize('content,finish', [
    ('{"text":"partial"}', 'length'),
    ('{"text":"draft","fact_ids":[1],"unknowns":[]}', 'stop'),
    ('{"text":"draft","fact_ids":[],"unknowns":[],"extra":true}', 'stop'),
])
def test_invalid_or_truncated_drafts_are_rejected(monkeypatch, content, finish):
    provider = configured(monkeypatch)
    original = httpx.Client
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={
        'choices': [{'finish_reason': finish, 'message': {'content': content}}], 'usage': {},
    }))
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original(transport=transport, **kwargs))
    with pytest.raises(ValueError):
        provider.generate('Use supplied facts.', '{}')
