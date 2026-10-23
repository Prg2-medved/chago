# Ограниченный эксперимент RAM prompt cache, 2026-10-23

Решение владельца: временно проверить гипотезу KV-снимков RAM prompt cache
закреплённой llama.cpp с единственным изменением `--cache-ram 0` у `llm`.
Это диагностическое исключение из запрета смены flags, не изменение MVP и не
замена полной приёмки design §9. OpenSpec `grounded-chat-api`: **27/31, 7.6 `[ ]`**.
7.3 не начинается. Прежние отрицательные verdicts и OOM evidence сохраняются.

Локальный `compose.yaml` содержит временную пару flags в конце command.
Harness имеет отдельный opt-in `--cache-ram-zero-experiment`: ровно четыре
end-to-end запроса **q01 → q02 → q01 → q02**, исходные tuning/live questions,
никаких generation-only/probe completions. Режим без этого аргумента сохраняет
прежние 20 запросов и прежний argv; с экспериментальным Compose он откажется
работать. Не запускать полную серию для этого эксперимента.

## Подготовка и отсутствие генерации

Все команды ниже выполняет **оператор на Linux Docker host**, из корня
существующего проекта, в одной Bash-сессии. Нужны прежние права Docker и чтения
`/proc/<llm-pid>/cmdline`, cgroup v2. Не запускать второй LLM, `compose run llm`,
build/pull, не менять `.env`, image/model/window/threads/FastAPI/swap/limits.
До начала остановить внешнюю подачу chat/evaluation и автоматические клиенты;
не останавливать сторонние сервисы. Не подменять индекс с момента startup app.

Перед первым блоком оператор подтверждает: все отправленные chat получили
полный ответ, нет незавершённых запросов, timeout/cancellation/обрыва с неизвестным
исходом и `generation_uncertain`. Проверить текущий интервал app/LLM logs;
последнему началу генерации должен соответствовать полный конец. Health и idle
задержка не доказывают отсутствие генерации. Если исход не установлен — этот
эксперимент не начинать; сначала ручной recovery с подтверждённой остановкой LLM,
её запуском и затем restart app, без пробного completion. После recovery вернуться
к началу процедуры. По одному лог-фильтру или отсутствию строк это условие не принимать.

Перенести обновлённый harness в `docs/grounded-chat-api-memory-series.py`.
Экспериментальный локальный `compose.yaml` перенести **отдельно** как
`data/cache-ram-zero-input/compose.yaml`, сохранив действующий серверный
`compose.yaml` исходным до backup. Если он уже заменён, сначала восстановить
точную исходную конфигурацию; не объявлять экспериментальную копию rollback backup.

```bash
set -euo pipefail
umask 077
APP_URL=http://192.168.12.100:8091
RUN=$(mktemp -d "$PWD/data/cache-ram-zero.XXXXXXXX")
export RUN
APP_ID=$(docker compose ps -q app)
OLD_LLM_ID=$(docker compose ps -q llm)
test -n "$APP_ID" && test -n "$OLD_LLM_ID"
PROJECT=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "$APP_ID")
export PROJECT
cp -- compose.yaml "$RUN/compose.original.yaml"
printf '%s\n' "$APP_ID" > "$RUN/app-id-before.txt"
printf '%s\n' "$OLD_LLM_ID" > "$RUN/llm-id-before.txt"
printf '%s\n' "$RUN" > data/cache-ram-zero-last-run.txt

# Fresh old-runtime baseline, identity, index; no chat/completion.
python3 docs/grounded-chat-api-memory-series.py --app-url "$APP_URL" --preflight-only
```

Сохранить напечатанный каталог preflight. Продолжать только при exit=0,
`preflight_passed_no_chat`, `index_unchanged=true`, без missing metrics/state
errors. Исходный baseline — новый интервал сравнения, не повтор диагностики OOM.

## Применение только к LLM

Сначала проверить **всю resolved конфигурацию**: допустимо только добавление
двух command arguments у llm. JSON может содержать secrets — сравнение в памяти,
без печати/сохранения resolved environment. Результат сравнения ничего не запускает.

```bash
python3 - <<'PY'
import copy, json, os, subprocess
def config(path):
    return json.loads(subprocess.check_output([
        'docker', 'compose', '--project-directory', os.getcwd(), '-p', os.environ['PROJECT'],
        '-f', path, 'config', '--format', 'json']))
before = config('compose.yaml')
after = config('data/cache-ram-zero-input/compose.yaml')
expected = copy.deepcopy(before)
assert '--cache-ram' not in before['services']['llm']['command']
expected['services']['llm']['command'] += ['--cache-ram', '0']
assert after == expected, 'STOP: changes beyond llm --cache-ram 0'
print('PASS: only llm command appends --cache-ram 0')
PY
cp -- data/cache-ram-zero-input/compose.yaml compose.yaml
docker compose config --quiet

# Explicit stop BEFORE recreation prevents overlap with the old LLM process.
docker stop --time 10 "$OLD_LLM_ID"
test "$(docker inspect --format '{{.State.Running}} {{.State.Pid}}' "$OLD_LLM_ID")" = 'false 0'
docker compose up -d --no-deps --no-build --pull never --force-recreate llm
test "$(docker compose ps -q app)" = "$APP_ID"
LLM_ID=$(docker compose ps -q llm)
test -n "$LLM_ID" && test "$LLM_ID" != "$OLD_LLM_ID"
docker inspect --format '{{json .Config.Cmd}}' "$LLM_ID"
LLM_PID=$(docker inspect --format '{{.State.Pid}}' "$LLM_ID")
test "$LLM_PID" -gt 0
python3 - "$LLM_PID" <<'PY'
import sys
from pathlib import Path
args = Path('/proc/' + sys.argv[1] + '/cmdline').read_bytes().decode().rstrip('\0').split('\0')
assert args.count('--cache-ram') == 1 and args[args.index('--cache-ram') + 1] == '0'
print(args)
PY
```

Readiness проверяется GET без генерации, максимум 60 попыток по 2 s; это повторы
только health, не completion. При неуспехе нет traffic, выполнить rollback.

```bash
ready=0
for attempt in $(seq 1 60); do
  if docker exec "$APP_ID" python -c 'import json,urllib.request; o=urllib.request.build_opener(urllib.request.ProxyHandler({})); r=o.open("http://llm:8080/health",timeout=5); assert r.status == 200 and json.load(r) == {"status":"ok"}'; then
    ready=1
    break
  fi
  sleep 2
done
test "$ready" = 1

# New-runtime control baseline and strict full argv/model/image/settings/index checks.
python3 docs/grounded-chat-api-memory-series.py --app-url "$APP_URL" \
  --cache-ram-zero-experiment --preflight-only
```

Продолжать только после review preflight summary/identity/memory: baseline выше
2097152 KiB, OOM counters не выросли между исходным и новым preflight (новый cgroup
имеет собственные counters), app ID прежний, settings прежние, индекс совпадает
между обоими preflights. Нужны текущие readiness и process flags именно нового
процесса; принятые старые результаты это не заменяют. На failure не повторять
запуск в надежде получить pass.

## Четыре запроса, остановка и review

```bash
python3 docs/grounded-chat-api-memory-series.py --app-url "$APP_URL" \
  --cache-ram-zero-experiment
```

Один запуск, без shell retry/цикла и без дальнейших completions. Сохранить
напечатанный каталог. Harness сам записывает baseline, before/during/post каждого
запроса (1 s), 10 s idle после четырёх ответов и final; LLM/app cgroup current,
`memory.stat` anon/file, swap, доступные peak, host MemAvailable/swap,
host/cgroup OOM counters, PID/start/restarts, request boundaries/status/ответы,
числовые log counts/timings. `identity-before.json` и `index-after.json` включают
hash/inode/metadata/inventory read-only индекса; `summary.index_unchanged` должен
быть true. Сравнить индекс также между исходным preflight и экспериментом.

Stop conditions прежние: MemAvailable <2 GiB, новый host/container OOM, смерть/
смена LLM process, изменение состава containers, HTTP не 200/невалидный contract,
transport failure/uncertain, sample duration >1 s или gap >2 s. При исходной
памяти ниже порога запросы не начинаются. При memory pressure/OOM harness
останавливает текущую LLM и проверяет PID=0; если подтверждения нет — оператор
выполняет stop и проверяет его вручную. На остальных failures следующий запрос
не отправляется; до stop/recovery нельзя считать генерацию завершённой.
Ctrl+C/закрытие клиента не останавливает генерацию. Порог не гарантирует защиты
от OOM между samples. Никаких автоматических повторов или перезапусков.

Минимальный просмотр результатов (путь взять из stdout конкретного запуска):

```bash
REPORT=/absolute/path/from/Reports
python3 - "$REPORT" <<'PY'
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
s = json.loads((p/'summary.json').read_text())
print(json.dumps(s, indent=2))
identity = json.loads((p/'identity-before.json').read_text())
llm = identity['llm']['id']
rows = [json.loads(line) for line in (p/'memory.jsonl').read_text().splitlines()]
print('phase request current anon file swap MemAvailable host_oom cgroup_events')
for r in rows:
    if llm not in r['containers']:
        print('INCOMPLETE SAMPLE', r['utc'], r['phase'])
        continue
    c = r['containers'][llm]
    if r['phase'] != 'during_request':
        print(r['phase'], r['request'], c['memory_current_bytes'], c['stat']['anon'],
              c['stat']['file'], c['memory.swap.current'], r['host_kib']['MemAvailable'],
              r['host_oom_kill'], c['events'])
print('min MemAvailable KiB:', min(r['host_kib']['MemAvailable'] for r in rows))
print('sampled max LLM current:', max(r['containers'][llm]['memory_current_bytes']
      for r in rows if llm in r['containers']))
assert s['state'] == '4_responses_experiment_review_pending' and s['index_unchanged'] is True
assert s['order'] == ['q01', 'q02', 'q01', 'q02']
requests = [json.loads(line) for line in (p/'requests.jsonl').read_text().splitlines()]
assert len(requests) == 8
assert [r['status'] for r in requests if r['event'] == 'end'] == [200]*4
PY
```

Дополнительно проверить `metrics.json`, `containers-after.json`, все четыре
responses, отсутствие `metrics_or_final_state_missing`, process/OOM изменения,
полноту during samples и наибольший anon+swap во всех samples. Review не должен
скрывать transient peaks. Отсутствующие counts явно раскрыть: prompt eval не
всегда полный usage. Peak counters относятся к жизни process/cgroup; sampled
max не абсолютный пик. Ошибка review не разрешает повтор серии.

## Откат после review или при остановке

Постоянное изменение отдельно не утверждено, поэтому вернуть исходный Compose
и пересоздать только LLM. Блок выполняется и после успешных четырёх ответов.
Оставить traffic выключенным до окончания. Если Bash завершился из-за `set -e`,
в новой сессии из того же корня восстановить переменные:

```bash
set -euo pipefail
RUN=$(cat data/cache-ram-zero-last-run.txt)
APP_ID=$(cat "$RUN/app-id-before.txt")
test -s "$RUN/compose.original.yaml"
CURRENT_LLM_ID=$(docker compose ps -a -q llm)
test -n "$CURRENT_LLM_ID"
docker stop --time 10 "$CURRENT_LLM_ID"
test "$(docker inspect --format '{{.State.Running}} {{.State.Pid}}' "$CURRENT_LLM_ID")" = 'false 0'
cp -- "$RUN/compose.original.yaml" compose.yaml
docker compose config --quiet
docker compose up -d --no-deps --no-build --pull never --force-recreate llm
test "$(docker compose ps -q app)" = "$APP_ID"
RESTORED_LLM_ID=$(docker compose ps -q llm)
docker inspect --format '{{json .Config.Cmd}}' "$RESTORED_LLM_ID"
cmp -- compose.yaml "$RUN/compose.original.yaml"
```

Повторить readiness GET loop из блока выше (с `APP_ID` прежнего app). Проверить
отсутствие `--cache-ram` и совпадение остального argv с исходным preflight.
Если были timeout/обрыв/uncertain/cancellation, **после подтверждённого stop старой
LLM, запуска восстановленной LLM и readiness** выполнить `docker compose restart app`;
это отдельный ручной recovery, не пересоздание/смена настроек FastAPI. Обычный
успешный эксперимент restart app не требует. До восстановления не возвращать
traffic. После него разрешён preflight без chat с исходным режимом:

```bash
python3 docs/grounded-chat-api-memory-series.py \
  --app-url http://192.168.12.100:8091 --preflight-only
```

Rollback preflight проверит полный исходный command, hash/model/settings/index,
readiness и baseline. Сопоставить index identity с исходным preflight и серией.
Backup и каталоги измерений не удалять. Временная локальная правка Compose также
не должна стать постоянным runtime default без отдельного решения владельца.

## Критерии гипотезы

Основная метрика — **anon + swap**, current и file нужны отдельно: file reclaim
может скрывать anonymous growth. Сравнивать приращения от свежего baseline,
все post-response и during samples, особенно переходы q01 → q02 и повторный
q01 → q02. По прежней серии сохранение предыдущего q01 соответствовало примерно
0,406 GiB; для нового run оценить ожидаемый state по фактическим counts
`(prompt_eval + eval - 1) × 147456 bytes` при прежних K/V f16 и архитектуре.
Это оценка, не measurement cache live bytes.

- Сильная поддержка гипотезы: флаг подтверждён, четыре ответа/telemetry/index
  корректны, оба перехода после q01 больше не дают прежних ~0,406 GiB ступеней
  anon+swap; после warm-up нет сопоставимого накопления при повторе. Проверить
  это на всём trace, без маскировки ростом swap или падением file. Допустимые
  рабочие allocations первого запроса отдельно показать, не вычёркивать baseline.
- Гипотеза недостаточна: при подтверждённом отключении cache сохраняются
  сопоставимые ступени или продолжающийся рост anon+swap. Это повод разобрать
  allocator/buffers отдельно, не разрешение нового эксперимента или flags.
- Неопределённо: failure, OOM/давление, неполная telemetry/counts, изменённая
  identity/нагрузка, слишком малые различия. Restart сам снижает память, поэтому
  одного более низкого baseline недостаточно; сравнение с историей не является
  одновременным A/B при одинаковом состоянии allocator/host.

Даже положительный результат не докажет отсутствие leak, не объяснит весь
исторический OOM, не подтвердит безопасность на любой нагрузке и не закроет 7.6.
Четыре запроса проверяют узкую гипотезу; расширение серии и постоянный флаг
требуют отдельного решения. К 7.3 не переходить.
