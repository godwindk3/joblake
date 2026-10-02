"""REST adapters. No SDK automatic retries, tools, or paid-model fallback."""
import json
import os
from dataclasses import dataclass

import requests

from joblake.enrichment.schema import PROMPT, SCHEMA, input_text, batch_contract


class ProviderError(Exception):
    def __init__(self, code, cooldown=60):
        super().__init__(code)
        self.code = code
        self.cooldown = cooldown


@dataclass(frozen=True)
class Result:
    data: dict
    tokens: int | None
    input_tokens: int | None = None
    output_tokens: int | None = None


def request_body(provider, payload, max_output, *, batch=False):
    prompt, schema = PROMPT, SCHEMA
    if batch:
        if provider['name'] != 'gemini':
            raise ValueError('Batch extraction is only enabled for Gemini')
        prompt, schema, payload = batch_contract(payload)
    text = input_text(payload)
    if provider['name'] == 'gemini':
        return {
            'systemInstruction': {'parts': [{'text': prompt}]},
            'contents': [{'role': 'user', 'parts': [{'text': text}]}],
            'generationConfig': {
                'maxOutputTokens': max_output,
                'thinkingConfig': {'thinkingLevel': 'minimal'},
                'responseMimeType': 'application/json', 'responseJsonSchema': schema,
            },
        }
    body = {
        'model': provider['model'],
        'messages': [{'role': 'system', 'content': PROMPT}, {'role': 'user', 'content': text}],
        'response_format': {'type': 'json_schema', 'json_schema': {
            'name': 'job_enrichment', 'strict': True, 'schema': SCHEMA}},
    }
    if provider['name'] == 'groq':
        body.update(max_completion_tokens=max_output, reasoning_effort='low')
    else:
        if not provider['model'].endswith(':free'):
            raise ValueError('OpenRouter enrichment requires an explicit :free model')
        # Some free endpoints only support JSON mode; others enforce a schema.
        # Choose explicitly instead of silently dropping unsupported parameters.
        if provider.get('output_format', 'json_object') == 'json_object':
            body['response_format'] = {'type': 'json_object'}
            body['messages'][0]['content'] += '\nJSON schema to follow:\n' + json.dumps(SCHEMA)
        body.update(max_tokens=max_output, provider={'require_parameters': True,
                    'max_price': {'prompt': 0, 'completion': 0, 'request': 0}})
        if 'reasoning_enabled' in provider:
            body['reasoning'] = {'enabled': provider['reasoning_enabled']}
    return body


def extract(provider, payload, *, max_output=2048, timeout=60, batch=False):
    name, model = provider['name'], provider['model']
    key = os.environ[provider['key_env']]
    body = request_body(provider, payload, max_output, batch=batch)
    headers = {'Content-Type': 'application/json'}
    if name == 'gemini':
        url = f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'
        headers['x-goog-api-key'] = key
    else:
        url = {'groq': 'https://api.groq.com/openai/v1/chat/completions',
               'openrouter': 'https://openrouter.ai/api/v1/chat/completions'}[name]
        headers['Authorization'] = f'Bearer {key}'
    try:
        response = requests.post(url, headers=headers, json=body, timeout=(10, timeout), allow_redirects=False)
    except requests.RequestException:
        raise ProviderError('transport_error', 120) from None
    # Never log response bodies, headers, URLs with secrets, or request exception strings.
    if response.status_code != 200:
        status = response.status_code
        cooldown = 86400 if status in (400, 401, 402, 403, 404) else 120
        if status == 429:
            cooldown = 3600
            try:
                message = str(response.json().get('error', {}).get('message', '')).lower()
                if any(word in message for word in ('per-day', 'per day', 'daily', 'requestsperday', 'tokensperday')):
                    cooldown = 86400
            except (ValueError, AttributeError, TypeError):
                pass
            try:
                cooldown = max(cooldown, min(int(response.headers.get('Retry-After', '0')), 86400))
            except ValueError:
                pass
        raise ProviderError(f'http_{status}', cooldown)
    try:
        raw = response.json()
        # OpenRouter can send HTTP 200 before the upstream provider fails.
        # Classify its error envelope so the worker applies a provider cooldown.
        if name == 'openrouter' and isinstance(raw, dict) and raw.get('error'):
            error = raw['error']
            code = error.get('code') if isinstance(error, dict) else None
            try:
                code = int(code)
            except (TypeError, ValueError):
                code = 502
            if code not in (400, 401, 402, 403, 404, 408, 429, 500, 502, 503, 504):
                code = 502
            cooldown = 86400 if code in (400, 401, 402, 403, 404) else (3600 if code == 429 else 120)
            raise ProviderError(f'http_{code}', cooldown)
        if name == 'gemini':
            candidate = raw['candidates'][0]
            if candidate.get('finishReason') != 'STOP':
                raise ProviderError('incomplete_output', 0)
            content = ''.join(p['text'] for p in candidate['content']['parts']
                              if 'text' in p and not p.get('thought'))
            usage = raw.get('usageMetadata', {})
            tokens = usage.get('totalTokenCount')
            inputs = usage.get('promptTokenCount')
            outputs = usage.get('candidatesTokenCount')
            if type(outputs) is int:
                outputs += usage.get('thoughtsTokenCount', 0) or 0
        else:
            choice = raw['choices'][0]
            if choice.get('finish_reason') != 'stop' or choice['message'].get('refusal'):
                raise ProviderError('incomplete_output', 0)
            content = choice['message']['content']
            usage = raw.get('usage', {})
            tokens = usage.get('total_tokens')
            inputs, outputs = usage.get('prompt_tokens'), usage.get('completion_tokens')
        data = json.loads(content)
        clean = lambda value: value if type(value) is int and value >= 0 else None
        return Result(data, clean(tokens), clean(inputs), clean(outputs))
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        raise ProviderError('invalid_response', 0) from None


def extract_batch(provider, jobs, *, max_output=6144, timeout=60):
    return extract(provider, jobs, max_output=max_output, timeout=timeout, batch=True)
