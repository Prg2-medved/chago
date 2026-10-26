# Серверная последовательность 7.7 → 7.3 → 7.2 → 7.4

Подготовлено 2026-10-26. Это инструкция оператору, **не результаты live-проверки**.
7.6 уже принята; 20 запросов не повторять. Выполнять из корня проекта на Linux
Docker host, без другого chat/reindex/evaluation traffic. Нужны текущие `app/`,
`docs/grounded-chat-api-fault.py`, memory-series harness и frozen `eval/`.
Ожидается тот же frozen live индекс, что в принятой 7.6.

Если осталась незавершённая/неопределённая генерация, сначала подтверждённо
остановить прежнюю LLM, запустить её и затем app. Один restart app недопустим.
Не менять `.env`, Compose, image/model, flags (включая принятый `--cache-ram 0`),
timeout=300, reserve, ranking, prompts или corpus. Новые baseline/identity здесь
относятся к новому интервалу, старую OOM/recovery диагностику не повторяют.

## 1. Доставка исправления и preflight без completions

Перенести перечисленные файлы штатным способом. Пересобрать только app;
не выполнять pull/update LLM. Запускать после подтверждения отсутствия генерации:

```bash
docker compose build --pull=false app
docker compose up -d --no-deps --pull never app
export CHAT_URL=http://127.0.0.1:8000  # фактический опубликованный app origin
python3 docs/grounded-chat-api-memory-series.py --app-url "$CHAT_URL" --preflight-only --cache-ram-zero-experiment
```

Последняя команда **только с `--preflight-only`**: она не запускает ни 4, ни 20
запросов. Проверяет code/model/image/settings identity, readiness, headroom,
индекс и отсутствие host-published LLM port; сохраняет новый каталог отчёта.
Ожидается `preflight_passed_no_chat`. При mismatch/низкой памяти остановиться,
не подбирать настройки и не продолжать запросы. `/health` не обнаруживает
generation_uncertain; отсутствие этого состояния до начала подтверждает оператор.

```bash
umask 077
export GATE_DIR="$(mktemp -d "$PWD/data/grounded-chat-api-compose.XXXXXXXX")"
export LLM_ID="$(docker compose ps -q llm)"
export SINCE="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
export APP_IMAGE="$(docker compose images -q app)"
python3 - <<'PY'
import json, os
from pathlib import Path
q = next(q for q in json.loads(Path('eval/questions.yaml').read_text())['questions'] if q['id'] == 'q01')
assert (q['split'], q['source_set']) == ('tuning', 'live')
Path(os.environ['GATE_DIR'], 'q01.json').write_text(json.dumps(
    {'session_id': 'compose-acceptance', 'message': q['question']}, ensure_ascii=False))
PY
```

Не публиковать полные inspect/env или ответы с source quotes в общие логи.
Каталог evidence хранить с правами frozen corpus. Сохранить путь preflight report.

## 2. Test-only граница transport и наблюдение

`grounded-chat-api-fault.py` запускает тот же app одним Uvicorn worker в
**заменяющем** Compose container. Штатный app в это время остановлен. Сохраняются
Compose environment/networks/volumes/ports и локальная Qwen; новая production
настройка или публичный control endpoint не добавляются.

Только первый completion полностью отправляется upstream, затем HTTPConnection
не читает response. В `release` чтение разрешает файл `release`; в `timeout`
оно остаётся заблокированным ровно штатный socket timeout, после чего transport
получает TimeoutError. Это fault приложения после отправки request, **не timeout
curl**. Template/tokenize не перехватываются. Следующие sends не скрываются:
каждый записывается в `trace.jsonl` как `upstream_completion_sent`, `count=N`.
Payload и timeout не изменяются, повторных отправок в harness нет.

Счётчик означает полностью отправленные HTTP requests, а не число принятых или
завершённых llama-server задач. Подтвердить первый request также по штатным LLM
logs за интервал; не включать verbose и не делать прямые completion/slot probes.
Если связь с LLM logs не установлена, gate остаётся открытым. При withheld response
app не получает доказательства завершения LLM: она может ещё генерировать либо
уже закончить. Испытание проверяет именно неопределённость; оно не утверждает,
что Qwen генерировала все 300 секунд.

SIGUSR1 здесь отменяет первый ASGI task **после** upstream send. Это явная
test-only инъекция task cancellation. Простое закрытие curl не гарантирует
CancelledError в Uvicorn; отдельно сохранить его фактическое поведение, не
выдавать отсутствие записи `client_cancelled` при disconnect за доказанную
task cancellation. Поздние transport/INFO records проверяются после SIGUSR1.

Если на хосте уже имеются `nsenter` и `tcpdump`, после `start_case` и до запросов
запустить в отдельном терминале захват заголовков в network namespace app:

```bash
sudo nsenter -t "$(docker inspect --format '{{.State.Pid}}' "$NAME")" -n \
  tcpdump -i any -nn -l -q 'ip or ip6' > "$CASE/network.txt" 2> "$CASE/network-summary.txt"
```

После case остановить Ctrl+C и сохранить summary, включая dropped packets.
Не включать `-A`, `-X`, `-w` или payload capture. Сопоставить адреса с
`docker inspect --format '{{json .NetworkSettings.Networks}}' "$NAME" "$LLM_ID"`:
разрешены клиентский app port, внутренний llm:8080 и service DNS; любые обращения
к Wiki/DB/внешним API/download hosts требуют разбора. Отсутствие пакетов при
потерях/неполном интервале не доказывает isolation. Если инструменты отсутствуют
или нет прав, сохранить этот пробел и остановиться перед live gate; не устанавливать
их и не менять сеть в рамках процедуры.

Общие shell-функции (одна сессия Bash; вызывать шаги ниже последовательно):

```bash
start_case() {
  export CASE="$GATE_DIR/$1" NAME="chago-gate-$1-$(date +%s)"
  mkdir "$CASE"
  docker compose stop app
  docker compose run -d --no-deps --pull never --service-ports --name "$NAME" \
    -v "$PWD/docs/grounded-chat-api-fault.py:/app/grounded_chat_fault.py:ro" \
    -v "$CASE:/evidence" app python /app/grounded_chat_fault.py --directory /evidence --mode "$2"
  # Не запускать HTTP до 200; readiness не делает completion.
  for n in $(seq 1 30); do
    if curl --noproxy '*' -fsS --max-time 2 "$CHAT_URL/health" > "$CASE/health-start.json"; then break; fi
    sleep 1
  done
  test "$(cat "$CASE/health-start.json")" = '{"status":"ok"}' || return 1
}
post() {
  test ! -e "$CASE/STOP" || return 1
  curl --noproxy '*' -sS --max-time 900 -H 'Content-Type: application/json' \
    --data-binary "@$GATE_DIR/q01.json" -o "$CASE/$1.json" \
    -w '%{http_code} %{time_total}\n' "$CHAT_URL/api/chat" > "$CASE/$1.status"
}
start_cancelled_client() {
  test ! -e "$CASE/STOP" || return 1
  curl --noproxy '*' -sS --max-time 900 -H 'Content-Type: application/json' \
    --data-binary "@$GATE_DIR/q01.json" -o "$CASE/cancelled.json" \
    -w '%{http_code} %{time_total}\n' "$CHAT_URL/api/chat" > "$CASE/cancelled.status" &
  CANCELLED=$!  # PID самого curl, а не subshell с shell-функцией
}
wait_sent() {
  for n in $(seq 1 120); do
    if grep -q '"event": "upstream_completion_sent"' "$CASE/trace.jsonl"; then return 0; fi
    sleep 1
  done
  echo 'No upstream send: STOP; inspect evidence, do not retry.' >&2
  return 1
}
save_logs() {
  docker logs --timestamps "$NAME" > "$CASE/app.log" 2>&1
  docker logs --timestamps --since "$SINCE" "$LLM_ID" > "$CASE/llm.log" 2>&1
  docker inspect --format '{{json .State}}' "$LLM_ID" > "$CASE/llm-state.json"
}
```

При любой неожиданной ошибке команд **не выполнять следующие шаги**. `wait_sent`
с ограниченным ожиданием не разрешает retry. До каждого case требуется headroom
≥2097152 KiB; во время case запустить observer ниже в отдельном терминале с теми
же экспортированными `CASE`, `NAME`, `LLM_ID` (либо во втором окне той же shell).
Он использует существующий monitor без отправки запросов, собирает app/LLM/host/
cgroup telemetry примерно раз в секунду и останавливает LLM при stop criterion.
Только после появления `memory.jsonl` без `STOP` отправлять первый запрос.

```bash
python3 - <<'PY'
import importlib.util, os, pathlib, time
s = importlib.util.spec_from_file_location('memory', 'docs/grounded-chat-api-memory-series.py')
m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
p = pathlib.Path(os.environ['CASE'])
app, llm = m.docker_json('inspect', os.environ['NAME'], os.environ['LLM_ID'])
monitor = m.Monitor(app, llm, p)
try:
    while not (p / 'monitor-stop').exists():
        began = time.monotonic()
        monitor.sample('compose')
        time.sleep(max(0, 1 - (time.monotonic() - began)))
except Exception:
    (p / 'STOP').write_text('Monitor stopped; no further requests; inspect memory.jsonl.\n')
    m.command('docker', 'stop', os.environ['LLM_ID'], timeout=45)
    raise
PY
```

Новый OOM, остановка/смена LLM PID, недостаточный headroom или telemetry gap:
прекратить traffic, сохранить evidence, подтвердить остановку LLM; никакого retry.
Порог консервативный, пиков между samples не исключает. Штатно observer завершать
через `touch "$CASE/monitor-stop"` **до** planned cleanup/LLM stop.

## 3. Concurrency, затем cancellation с поздним полным ответом

Первый case:

```bash
start_case concurrent release
# Запустить observer и проверить первый sample.
post first & FIRST=$!
wait_sent
post waiting & WAITING=$!
curl --noproxy '*' -fsS --max-time 2 "$CHAT_URL/health" > "$CASE/health-during.json"
sleep 2
cat "$CASE/trace.jsonl"  # ровно один upstream send, второй ещё ждёт
touch "$CASE/release"
wait "$FIRST"
wait "$WAITING"
save_logs
touch "$CASE/monitor-stop"
```

Ожидается два HTTP 200, два sends всего, второй send только после
`response_read_released` и первого полного response; отдельный wait_ms у второго,
query/retrieval/generation timings, `/health`=200 во время удержания. Сопоставить
с LLM logs: нет двух одновременно активных генераций. JSON обоих ответов должен
соблюдать публичный contract; fallback не объявлять quality pass.
Если второй запрос не дошёл до ожидания semaphore до release (его wait_ms не
подтверждает перекрытие), concurrency не засчитывать; одного count=1 через 2 s
недостаточно. Сохранить результат для разбора, не объявлять pass по двум 200.

После полного завершения обеих генераций удалить только временный container:
`docker stop "$NAME" && docker rm "$NAME"`. Штатный app пока остановлен.
Создать новый case `start_case cancel-full release`, запустить observer и:

```bash
start_cancelled_client
wait_sent
kill "$CANCELLED"  # закрытие клиента; само по себе не отменяет ASGI task
wait "$CANCELLED" || true
docker kill --signal=USR1 "$NAME"
post waiting & WAITING=$!
sleep 2
cat "$CASE/trace.jsonl"
touch "$CASE/release"
wait "$WAITING"
save_logs
touch "$CASE/monitor-stop"
```

Требуются `asgi_task_cancelled`, INFO `outcome=client_cancelled` до release,
поздний отдельный INFO `chat generation_ms=...` после него; следующий completion
только после полного ответа. Если SIGUSR1 отклонён или полноценный ответ не
получен до native timeout, не повторять case, перейти к разбору/recovery.
Проверить отсутствие question/session/source/prompt/credentials в `app.chat`
records. Затем после завершённых вызовов удалить временный container как выше.

## 4. Настоящий app timeout и удержание uncertain slot

```bash
start_case timeout timeout
# Запустить observer и проверить первый sample.
post original & ORIGINAL=$!
wait_sent
post waiting & WAITING=$!
wait "$ORIGINAL"
wait "$WAITING"
cat "$CASE/original.status" "$CASE/waiting.status"
# Ожидается 504 и 503; timeout около 300 s ПОСЛЕ response_withheld, плюс retrieval.
post new
curl --noproxy '*' -fsS --max-time 2 "$CHAT_URL/health" > "$CASE/health-uncertain.json"
sleep 10
post later
save_logs
touch "$CASE/monitor-stop"
cat "$CASE/trace.jsonl"
```

Ожидается `transport_timeout`, безопасные `llm_timeout` и
`generation_uncertain/recovery=operator_required`, новые/ожидающие HTTP 503,
health=ok, **ровно один upstream send** до и после проверок/задержки.
Не вызывать LLM health/slot/completion, не снимать слот и не перезапускать один
app. Даже если LLM logs содержат завершение, app его не прочёл и блокировка
должна сохраняться. При утрате trace/count evidence не делать проверочных POST.

Recovery — только в таком порядке, с сохранением состояния старого процесса:

```bash
docker inspect --format '{{json .State}}' "$LLM_ID" > "$CASE/llm-before-stop.json"
docker stop "$LLM_ID"
docker inspect --format '{{json .State}}' "$LLM_ID" > "$CASE/llm-stopped.json"
test "$(docker inspect --format '{{.State.Running}} {{.State.Pid}}' "$LLM_ID")" = 'false 0'
docker start "$LLM_ID"
# После подтверждённого stop/start разрешена readiness-проверка новой LLM.
docker exec "$NAME" python -c 'from urllib.request import build_opener,ProxyHandler; print(build_opener(ProxyHandler({})).open("http://llm:8080/health",timeout=5).read().decode())'
# Если ещё loading: только readiness, без chat; дождаться {"status":"ok"}.
docker stop "$NAME"
docker rm "$NAME"
docker compose up -d --no-deps --pull never app
```

Теперь один успешный chat штатному app (через `post recovered` после readiness)
разрешён. Сохранить Docker logs штатного app и новая LLM process identity.
Повторить **новый case** `start_case cancel-timeout timeout` с observer:
`start_cancelled_client`, `wait_sent`, закрыть клиента и послать USR1
как в шаге 3; запустить `post waiting` и дождаться его 503 после позднего timeout.
Исходный клиент уже отключён, ему 504 не приписывается. Сделать `post new`, health,
10 s, `post later`, сохранить logs/count=1. Требуется поздний generation INFO
после `client_cancelled`, блокировка остаётся. Затем **тот же полный recovery**,
один успешный chat и сохранение логов. Ни один timeout не разрешает следующий case
без подтверждённого recovery.

## 5. Offline/app-only/isolation и index identity

После recovery повторить **только preflight-only** из шага 1. Сравнить
`identity-before.json.index` до/после: SQLite SHA256, snapshot/reindex metadata,
documents, inode/device. Смена app image ожидаема лишь при доставке logging fix;
сам индекс не должен измениться. Сохранить selected inspect Cmd/ports/mounts,
один worker/PID; LLM порт без host binding. Не выгружать env с DB credentials.

App-only проверка без дополнительных completions: остановить штатный app
после полного ответа, запустить заменяющий container **без сети и без assets**
на том же image (без published ports); внутри него запросить health и chat:

```bash
docker compose stop app
docker run -d --pull never --network none --name chago-app-only "$APP_IMAGE"
docker exec -i chago-app-only python - <<'PY'
import json
from urllib.error import HTTPError
from urllib.request import build_opener, ProxyHandler, Request
o = build_opener(ProxyHandler({}))
print(o.open('http://127.0.0.1:8000/health', timeout=5).read().decode())
try:
    o.open(Request('http://127.0.0.1:8000/api/chat',
        data=json.dumps({'session_id':'offline', 'message':'test'}).encode(),
        headers={'Content-Type':'application/json'}), timeout=5)
except HTTPError as e:
    assert e.code == 503
    print(e.code, e.read().decode())
else:
    raise SystemExit('expected 503')
PY
docker logs chago-app-only > "$GATE_DIR/app-only.log" 2>&1
docker stop chago-app-only
docker rm chago-app-only
docker compose up -d --no-deps --pull never app
```

Дождаться startup до exec; при connect refused повторять только health, а не chat.
Нет models/index mounts или доступа к Wiki/LLM/Интернету. Это отдельное доказательство
offline app-only, не доказательство отсутствия Wiki/внешнего traffic у штатного
indexed chat. Для последнего сохранить наблюдение сетевых соединений на интервале
шагов 3–4 средствами хоста и штатные app/LLM logs; одних code review и отсутствия
записей недостаточно. Если такого evidence нет, isolation часть 7.3 открыта;
не устанавливать packet-capture инструменты/не менять сеть молча.

## 6. Передача результатов и следующие gates

Для review нужны preflight каталоги до/после и `$GATE_DIR`: traces, statuses,
ответы, app/LLM logs с timestamps, memory series, recovery process states,
network evidence и app-only результат. Сохранить ручные timestamps для отправки,
SIGUSR1/release, timeout и recovery. Trace содержит UTC timestamps и отдельное
monotonic время для измерения интервалов.

Только после review этих результатов закрывать 7.7/7.3. Затем выполнить
существующий `docs/grounded-chat-api-evaluate.sh` по acceptance report (7.2):
end-to-end и fixed-evidence generation-only, все single-question/unanswerable и
synthetic security/conflict cases. Сохранить исходный failed review; verdicts
stability/safety/semantic quality раздельные, q13/q18 требуют safety review,
раскрытый holdout не использовать для настройки. При transport failure остановиться.

После фактических gates выполнить 7.4: сверка обязательных delta scenarios,
перечень открытых safety/quality defects, `openspec validate grounded-chat-api
--strict`, `openspec validate --all --strict`, проверка Git diff. До live evidence
прогресс остаётся **28/32**, архивировать change нельзя.
