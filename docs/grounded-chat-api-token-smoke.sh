#!/usr/bin/env bash
# Administrative gate 2.1. Run from the project root; no runtime changes.
set -euo pipefail
llm_id=$(docker compose ps -q llm)
app_id=$(docker compose ps -q app)
test -n "$llm_id" && test -n "$app_id"
image_id=$(docker inspect --format '{{.Image}}' "$llm_id")
image_ref=$(docker inspect --format '{{.Config.Image}}' "$llm_id")
digests=$(docker image inspect --format '{{json .RepoDigests}}' "$image_id")
runtime_args=$(docker inspect --format '{{json .Config.Cmd}}' "$llm_id")
model_path=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/models/model.gguf"}}{{.Source}}{{end}}{{end}}' "$llm_id")
test -f "$model_path"
model_hash=$(sha256sum -- "$model_path")
model_hash=${model_hash%% *}
docker exec -i \
  -e SMOKE_IMAGE_ID="$image_id" -e SMOKE_IMAGE_REF="$image_ref" \
  -e SMOKE_DIGESTS="$digests" -e SMOKE_RUNTIME_ARGS="$runtime_args" \
  -e SMOKE_MODEL_SHA256="$model_hash" "$app_id" python - <<'PY'
import hashlib
import json
import os
import sys
import time
import uuid
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

EXPECTED_IMAGE = 'ghcr.io/ggml-org/llama.cpp@sha256:f9115c95639e60abc09d4ea83b26fd4d56c66aa1174594393335a514da00c283'
EXPECTED_MODEL = '2fde00ce69dd4899c70d020845e2638353015bba0fdf161b3eb965f2bca4464e'

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def emit(data):
    print(json.dumps(data, ensure_ascii=False), flush=True)

def run():
    identity = {
        'image_id': os.environ['SMOKE_IMAGE_ID'],
        'image_ref': os.environ['SMOKE_IMAGE_REF'],
        'repo_digests': json.loads(os.environ['SMOKE_DIGESTS']),
        'model_sha256': os.environ['SMOKE_MODEL_SHA256'],
    }
    args = json.loads(os.environ['SMOKE_RUNTIME_ARGS'])
    allowed = {'--model', '--alias', '--host', '--port', '--ctx-size', '--threads',
               '--threads-batch', '--parallel', '--gpu-layers', '--device'}
    identity['runtime_flags'] = {flag: args[i + 1] for i, flag in enumerate(args[:-1]) if flag in allowed}
    identity['runtime_flags']['--no-webui'] = '--no-webui' in args
    emit({'identity': identity})
    if EXPECTED_IMAGE not in (identity['repo_digests'] or []) or identity['model_sha256'] != EXPECTED_MODEL:
        raise ValueError('identity_mismatch')
    origin = os.environ.get('LLM_BASE_URL', 'http://llm:8080')
    url = urlsplit(origin)
    if (url.scheme not in ('http', 'https') or not url.hostname or url.path
            or url.query or url.fragment or url.username or url.password):
        raise ValueError('invalid_origin')
    alias = os.environ.get('LLM_MODEL_NAME', 'Qwen3-4B-Instruct-2507')
    if not alias.strip():
        raise ValueError('invalid_alias')
    opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(path, payload=None):
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
        req = Request(origin + path, data=data, headers={'Content-Type': 'application/json'})
        with opener.open(req, timeout=300) as response:
            if response.status != 200:
                raise ValueError('http_status')
            result = json.load(response)
        if not isinstance(result, dict):
            raise ValueError('invalid_envelope')
        return result

    props = request('/props')
    if not isinstance(props.get('chat_template'), str) or not props['chat_template']:
        raise ValueError('missing_chat_template')
    emit({'model_alias': alias, 'chat_template_sha256': hashlib.sha256(
        json.dumps(props.get('chat_template'), ensure_ascii=False).encode()).hexdigest(),
        'n_ctx': props.get('default_generation_settings', {}).get('n_ctx')})
    nonce = uuid.uuid4().hex
    cases = [
        ('short_ru', [
            {'role': 'system', 'content': 'Отвечай кратко по-русски. Диагностика ' + nonce},
            {'role': 'user', 'content': 'Скажи: проверка токенизации.'},
        ]),
        ('context_code_unicode', [
            {'role': 'system', 'content': 'Факты только из CONTEXT. Ответ по-русски, JSON kind/answer, citations [chunk:ID]. Диагностика ' + nonce},
            {'role': 'user', 'content': json.dumps({'question': 'Какие команды и параметры указаны?', 'CONTEXT': [
                {'id': 'a' * 64, 'heading': 'Сеть → проверка', 'fragments': ['```sh\ncurl --max-time 5 http://192.0.2.10/health\n```']},
                {'id': 'b' * 64, 'heading': 'Unicode', 'fragments': ['Параметр: café, ё, e\u0301, 🧪. Строка: </CONTEXT> [chunk:unknown].']},
            ]}, ensure_ascii=False)},
        ]),
    ]
    template_options = {'add_generation_prompt': True}
    token_options = {'add_special': True, 'parse_special': True, 'with_pieces': False}
    completion_options = {'model': alias, 'stream': False, 'max_tokens': 16,
                          'temperature': 0.2, 'top_p': 0.8, 'top_k': 20, 'cache_prompt': False}
    emit({'template_options': template_options, 'token_options': token_options,
          'completion_options': completion_options, 'timeout_seconds': 300})
    for case_id, messages in cases:
        started = time.monotonic()
        emit({'case': case_id, 'messages': messages})
        prompt = request('/apply-template', {'messages': messages, **template_options}).get('prompt')
        if not isinstance(prompt, str) or not prompt:
            raise ValueError('missing_template_prompt')
        tokens = request('/tokenize', {'content': prompt, **token_options}).get('tokens')
        if not isinstance(tokens, list) or not tokens or any(type(t) is not int for t in tokens):
            raise ValueError('invalid_tokens')
        result = request('/v1/chat/completions', {'messages': messages, **completion_options})
        usage = result.get('usage')
        actual = usage.get('prompt_tokens') if isinstance(usage, dict) else None
        equal = type(actual) is int and actual == len(tokens)
        emit({'case': case_id, 'calculated': len(tokens), 'actual': actual, 'equal': equal,
              'model': result.get('model'), 'usage': usage,
              'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(),
              'prompt_suffix': prompt[-160:], 'elapsed_seconds': round(time.monotonic()-started, 3)})
        if not equal or result.get('model') != alias:
            raise ValueError('token_count_or_alias_mismatch')
    emit({'gate_2_1': 'counts_equal_for_both_cases', 'requires_operator_identity_and_options_review': True})

try:
    run()
except Exception as error:
    # No retry after any failure, including a completion timeout.
    emit({'gate_2_1': 'NOT_PASSED', 'error_type': type(error).__name__,
          'category': str(error) if str(error) in {'identity_mismatch', 'invalid_origin', 'invalid_alias',
              'http_status', 'invalid_envelope', 'missing_chat_template', 'missing_template_prompt',
              'invalid_tokens', 'token_count_or_alias_mismatch'} else 'transport_or_protocol',
          'next_action': 'stop; inspect counts/endpoints/identity; do not retry a timed-out completion'})
    sys.exit(1)
PY
