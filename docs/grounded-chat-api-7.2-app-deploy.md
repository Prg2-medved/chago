# Установка кандидата 7.9 в штатный app на Ubuntu

2026-10-27: протокол 7.11 согласован владельцем для серверной приёмки;
сейчас подготовлен только этап установки. Ниже команды оператору, **не отчёт
об их выполнении**. Docker/Ubuntu из локального Windows workspace не опрашивались.
После каждого блока просмотреть evidence, при ошибке остановиться. Здесь нет
token gate, chat request или evaluation. 7.2/7.4 остаются открытыми.

## Что требуется установить

В `app/Dockerfile` код копируется в image через `COPY app/ ./app/`; Compose
монтирует только `./data:/data`. Поэтому перенос файла в checkout и
`docker compose restart app` не устанавливают новую версию. Нужны сборка
только app и пересоздание только app. LLM, `.env`, Compose runtime, данные,
модели и прочие сервисы не изменяются.

Перенести согласованный `app/app/grounding.py` в **существующий серверный checkout**
штатным способом. Не делать слепой git pull: локальный кандидат ещё может быть
незакоммичен. Не переносить Windows SQLite/models/.env поверх серверных файлов.
Остальные исходники/Dockerfile/requirements в checkout должны оставаться версией,
использованной для принятых gates; их hashes сохраняются ниже.

Работать из корня того же Compose project, тем же пользователем и в одном Bash
shell. Нужны доступ к Docker, Python 3 и текущие .env/offline assets. Нет другого
chat/harness/reindex traffic; оператор подтверждает, что прежняя генерация
полностью завершилась и app не в generation_uncertain. Одно health=ok либо
перезапуск только app этого не доказывают. При неопределённости — STOP до
отдельного recovery, не выполнять эти команды как способ снять блокировку.

## A. Сохранить baseline и проверить checkout, без замены контейнеров

```bash
set -Eeuo pipefail
umask 077
deploy_dir=$(mktemp -d "$PWD/data/grounded-chat-api-app-deploy.XXXXXXXX")
printf 'Deployment evidence: %s\n' "$deploy_dir"
date -u +%FT%TZ > "$deploy_dir/start.txt"
trap 'deploy_rc=$?; printf "%s\n" "$deploy_rc" > "$deploy_dir/failed.exit"; date -u +%FT%TZ > "$deploy_dir/failed-at.txt"; printf "STOP; preserve %s; no token/evaluation/retry.\n" "$deploy_dir"; exit "$deploy_rc"' ERR

# Не подмешивать оставшийся fault override или другой Compose project.
test -z "${COMPOSE_FILE:-}"
test ! -e compose.override.yaml
test ! -e compose.override.yml
old_app=$(docker compose -f compose.yaml ps -q app)
llm_id=$(docker compose -f compose.yaml ps -q llm)
test -n "$old_app" && test -n "$llm_id"
test "$(docker inspect --format '{{.State.Running}}' "$old_app")" = true
test "$(docker inspect --format '{{.Config.Cmd}}' "$old_app")" = '[python -m app]'
test "$(docker inspect --format '{{.State.Running}}/{{.State.OOMKilled}}' "$llm_id")" = true/false

test "$(sha256sum app/app/grounding.py | cut -d ' ' -f1)" = \
  1587022b84f4ab1ad586403ab673516defa455d77c34b18b330343891b0c045a
sha256sum app/app/*.py app/Dockerfile app/requirements.txt app/.dockerignore compose.yaml \
  > "$deploy_dir/checkout.sha256"
docker inspect --format '{{.Id}} image={{.Image}} started={{.State.StartedAt}} restarts={{.RestartCount}}' \
  "$old_app" > "$deploy_dir/app-before.txt"

llm_snapshot() {
  docker inspect --format '{{.Id}}|{{.Image}}|{{.State.Pid}}|{{.State.StartedAt}}|{{.State.Running}}|{{.State.OOMKilled}}|{{.RestartCount}}|{{json .Config.Cmd}}' "$llm_id"
}
env_hash() {
  docker inspect --format '{{json .Config.Env}}' "$1" \
    | python3 -c 'import hashlib,json,sys; print(hashlib.sha256(json.dumps(sorted(json.load(sys.stdin)),separators=(",",":")).encode()).hexdigest())'
}
headroom() {
  free -k
  awk '/^MemAvailable:/ {found=1; if ($2<2097152) exit 1} END {if (!found) exit 1}' /proc/meminfo
}
llm_snapshot > "$deploy_dir/llm-before.txt"
llm_image=$(docker inspect --format '{{.Image}}' "$llm_id")
docker image inspect --format '{{json .RepoDigests}}' "$llm_image" > "$deploy_dir/llm-repodigests.json"
python3 -c 'import json,sys; assert "ghcr.io/ggml-org/llama.cpp@sha256:f9115c95639e60abc09d4ea83b26fd4d56c66aa1174594393335a514da00c283" in json.load(open(sys.argv[1]))' "$deploy_dir/llm-repodigests.json"
env_hash "$old_app" > "$deploy_dir/app-env-before.sha256"
headroom > "$deploy_dir/memory-before.txt"
docker stats --no-stream "$old_app" "$llm_id" > "$deploy_dir/stats-before.txt"
```

Просмотреть baseline: LLM image/command должны соответствовать принятому pinned
runtime (Qwen, context 8192, parallel=1, CPU-only, threads=8, cache-ram=0).
Перед B сверить их с принятой identity; при расхождении не продолжать.
В этом этапе фиксируется новый интервал установки, не повторяются 7.3/7.7.
Сохранён только hash env; не выводить raw env/full inspect/Compose config с
DB credentials. Оператор наблюдает ресурсы и во время сборки: snapshots и порог
2 GiB не гарантируют предотвращения OOM между проверками.

## B. Собрать image app, пока старый app ещё работает

Dockerfile содержит `pip install`. Ожидается переиспользование существующего
base image и cached dependency layer. Временный override ниже применяется
**только к build**, запрещает сеть для RUN и не меняет штатный compose.yaml.
`--pull=false` не требует обновления base; build.network не запрещает обращения
самого builder за image metadata. Если локального base/cache нет или сборка
пытается потребовать загрузки — STOP, не включать сеть/--no-cache автоматически.
Описание флагов: [Compose build](https://docs.docker.com/reference/cli/docker/compose/build/),
[build.network](https://docs.docker.com/reference/compose-file/build/#network).

```bash
docker image inspect python:3.12-slim --format '{{.Id}}' > "$deploy_dir/base-image.txt"
cat > "$deploy_dir/build-offline.yaml" <<'YAML'
services:
  app:
    build:
      context: ./app
      network: none
YAML
docker compose -f compose.yaml -f "$deploy_dir/build-offline.yaml" \
  build --pull=false app > "$deploy_dir/build.log" 2>&1
sha256sum -c "$deploy_dir/checkout.sha256" > "$deploy_dir/checkout-check-build.txt"
llm_snapshot > "$deploy_dir/llm-after-build.txt"
cmp "$deploy_dir/llm-before.txt" "$deploy_dir/llm-after-build.txt"
headroom > "$deploy_dir/memory-after-build.txt"
```

Сборка не заменяет запущенный app. Просмотреть build.log перед C; при ошибке
сохранить evidence и оставить старый app, не пытаться запустить evaluation
через bind-mounted новый checkout. Если кеш отсутствует, отдельное решение
по подготовке build environment предшествует установке. Dockerfile/dependencies
ради успешной сборки не править.

## C. Пересоздать только app из собранного image

```bash
docker compose -f compose.yaml up -d --no-deps --no-build --pull never \
  --force-recreate app > "$deploy_dir/up.log" 2>&1
new_app=$(docker compose -f compose.yaml ps -q app)
test -n "$new_app" && test "$new_app" != "$old_app"
test "$(docker inspect --format '{{.State.Running}}' "$new_app")" = true
test "$(docker inspect --format '{{.Config.Cmd}}' "$new_app")" = '[python -m app]'
docker inspect --format '{{.Id}} image={{.Image}} started={{.State.StartedAt}} restarts={{.RestartCount}}' \
  "$new_app" > "$deploy_dir/app-after.txt"
env_hash "$new_app" > "$deploy_dir/app-env-after.sha256"
cmp "$deploy_dir/app-env-before.sha256" "$deploy_dir/app-env-after.sha256"
llm_snapshot > "$deploy_dir/llm-after-deploy.txt"
cmp "$deploy_dir/llm-before.txt" "$deploy_dir/llm-after-deploy.txt"
headroom > "$deploy_dir/memory-after-deploy.txt"
```

Команда сохраняет mounted data и не запускает зависимости; она исключает новую
сборку/pull во время переключения ([Compose up](https://docs.docker.com/reference/cli/docker/compose/up/)).
Проверка env hash запрещает незаметную смену settings/credentials при recreate.
Несовпадение — STOP; не исправлять .env наугад и не выполнять rollback/recovery
автоматически. LLM ID/image/PID/StartedAt/command/restarts должны остаться прежними.

## D. Проверить candidate identity и обычную readiness; затем остановиться

Проверить ту же candidate identity, что в шаге 2
[протокола 7.11](grounded-chat-api-7.11-runbook.md):

```bash
app_id=$new_app
evidence=$deploy_dir
docker exec -i "$new_app" python -B - > "$deploy_dir/candidate-identity.json" <<'PY'
import hashlib, json
from pathlib import Path
import app.grounding as grounding
from app.chat_token_check import BOUNDARY_QUESTION, boundary_manifest
code = hashlib.sha256(Path(grounding.__file__).read_bytes()).hexdigest()
rules = hashlib.sha256(grounding.SYSTEM_RULES.encode()).hexdigest()
messages = grounding.build_messages(BOUNDARY_QUESTION, boundary_manifest(1))
probe = hashlib.sha256(json.dumps(messages, ensure_ascii=False, sort_keys=True,
                                separators=(',', ':')).encode()).hexdigest()
assert code == '1587022b84f4ab1ad586403ab673516defa455d77c34b18b330343891b0c045a'
assert rules == 'a2619f7c53f8149a89891654571592f09bb0679234bedef13e90ccb8d54085fe'
assert probe == 'a7fed6720da4dc11bb5d339970f1c82a5b75b9c5b47224ad858184335ee096ee'
print(json.dumps(dict(code_sha256=code, system_rules_sha256=rules,
                     boundary_probe_messages_sha256=probe)))
PY
docker exec -i "$new_app" python -B - > "$deploy_dir/health.json" <<'PY'
import json, time
from urllib.request import ProxyHandler, build_opener
opener = build_opener(ProxyHandler({}))
for attempt in range(10):
    try:
        with opener.open('http://127.0.0.1:8000/health', timeout=2) as response:
            body = json.load(response)
            assert response.status == 200 and body == {'status': 'ok'}
        print(json.dumps(body))
        break
    except Exception:
        if attempt == 9:
            raise
        time.sleep(1)
PY
docker logs --since "$(cat "$deploy_dir/start.txt")" "$new_app" \
  > "$deploy_dir/app-start.log" 2>&1
sha256sum -c "$deploy_dir/checkout.sha256" > "$deploy_dir/checkout-check-final.txt"
date -u +%FT%TZ > "$deploy_dir/end.txt"
printf '%s\n' 'INSTALL_CHECKS_COMPLETE_NO_TOKEN_OR_EVALUATION' > "$deploy_dir/result.txt"
```

Health polling — ограниченное ожидание запуска app, не generation/retry/recovery
и не повтор проверки health во время inference из 7.3. При health/identity
failure сохранить частичные evidence и app logs, не отправлять chat.
После успешного D передать deployment evidence для review. **На этом шаге
остановиться:** не запускать ни token smoke, ни evaluation. Следующий отдельный
этап — token gate нового prompt по 7.11; только после его фактического pass
можно переходить к corpus. Если что-либо пошло не так, старое/частичное evidence
не удаляется, автоматического повторного deploy/evaluation нет.

## Локальная проверка инструкции

Проверены Dockerfile/Compose и поддерживаемые флаги по официальной документации.
Bash blocks — только bash -n; Python heredoc — только ast.parse. Сборка,
развёртывание, Docker inspect/health на Ubuntu и model calls не выполнялись.
Фактическое состояние сервера ещё требуется подтвердить evidence этапа A.
Результаты: 4 Bash blocks через bash -n и 2 Python heredoc через ast.parse —
pass; OpenSpec strict change/all — 11/11, `git diff --check` — pass.
Полный pytest/mypy не повторялись: изменена только инструкция/отметки planning,
runtime source SHA256 кандидата остался прежним. Прогресс change — 34/36.
