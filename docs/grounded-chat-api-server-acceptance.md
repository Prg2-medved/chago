# Grounded chat API: журнал проверки

Дата: 2026-10-21. Среда реализации: локальный Windows workspace.
Linux-проверка 1.3 и live-gates 2.1, 7.1 подтверждены выводом оператора.
`POST /api/chat` реализован локально; серверные проверки 7.2–7.3 ещё не выполнены.

## Локальные проверки

Из каталога `app/`:

```powershell
../.venv/Scripts/python.exe -m pytest -q tests/test_active_retrieval.py tests/test_index_state.py tests/test_hybrid_retrieval.py tests/test_hybrid_retrieval_cli.py tests/test_health.py
```

Результат: **30 passed**, один существующий `StarletteDeprecationWarning`
о `httpx` в TestClient. Первый sandbox-прогон завершился ошибками доступа к
pytest temp/cache; результат выше получен повторным запуском вне sandbox.
В новом тесте исправлено обращение к source ranges как к словарям вместо
пар offsets; после исправления профильный прогон успешен.

Полный regression после финальных изменений lifecycle:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
../.venv/Scripts/python.exe -m pytest -q -rs -p no:cacheprovider
```

Результат: **808 passed, 46 skipped, 1 warning in 99.34s**.
Все 46 skips относятся к ограничениям Windows:
3 symlink privilege cases; 1 Linux flock case; 4 POSIX permission cases;
38 Linux Bash/flock/signals cases. Это не серверная приёмка и не подтверждение
поведения пропущенных Linux tests. Warning — тот же TestClient/httpx.

Типизация изменённых модулей:

```powershell
$env:MYPYPATH='typings'
../.venv/Scripts/python.exe -m mypy app/index_state.py app/hybrid_retrieval.py app/lexical_retrieval.py app/main.py --follow-imports=silent --cache-dir ../.tmp/mypy-grounded-chat
```

Результат: **Success: no issues found in 4 source files**.
Новые зависимости и type suppressions не добавлялись.

Из корня workspace также выполнены:

```powershell
openspec.cmd validate grounded-chat-api --strict
openspec.cmd validate --all --strict
git diff --check
```

Change валиден; общая проверка — **11 passed, 0 failed** (только INFO о длине
requirements). `git diff --check` успешен. README, ROADMAP, Compose/runtime
flags, frozen evaluation inputs и исторические отчёты не изменялись.
Сгенерированные тестами изменения двух tracked `.pyc` удалены из diff.

Ранние этапы 1.1–1.4, 2.1–2.2 приняты по автоматическим проверкам и выводу
оператора. Актуальные результаты последующей локальной реализации приведены
в конце отчёта. Серверные gates не считаются выполненными по unit/API tests.

## Завершённая задача 1.3

Первоначальный Windows-прогон не подтверждал подмену pathname при открытом
reader; Docker CLI локально отсутствует, список WSL distributions пуст.
Оператор выполнил подготовленную ниже команду на Linux и передал полный вывод.

- Linux, Python **3.12.15**, pytest **9.1.1**, anyio **4.15.1**.
- Результат: **30 passed, 1 warning in 1.07s**, без skips/failures.
- `test_snapshot_search_after_path_replacement` напечатал
  `PATHNAME_REPLACEMENT_OK: old snapshot retained; restart loaded new generation`.
- Проверены фактическая замена открытого временного SQLite, прежнее поколение
  retrieval/Markdown/ranges/title/URL до close и новое поколение после restart;
  app-only и прежний `/health` также прошли.
- Единственный pytest warning — прежний TestClient/httpx deprecation.
- Команда монтировала только read-only `app/`; production-индекс не монтировался.

Источник результата — приложенный оператором вывод команды (2026-10-21),
а не самостоятельный серверный запуск агента. На этом основании **1.3 выполнена**.

### Подготовленный Linux-прогон 1.3

При подготовке повторно выполнен локальный профильный прогон после добавления
маркера успешной подмены: **30 passed, 1 warning in 4.04s**. Команда из `app/`:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
../.venv/Scripts/python.exe -m pytest -q -rs -p no:cacheprovider --basetemp=../.tmp/grounded-13-preparation tests/test_active_retrieval.py tests/test_index_state.py tests/test_hybrid_retrieval.py tests/test_hybrid_retrieval_cli.py tests/test_health.py
```

Sandbox отказал в доступе к temp; успешный результат получен повторным запуском
вне sandbox. Это Windows regression, не фактическая Linux-проверка 1.3.
Docker-команда ниже локально не запускалась: Docker CLI отсутствует.

После переноса актуального `app/` из workspace на сервер выполнить **одну
команду из корня проекта** (Bash; Docker и уже собранный app image доступны):

```bash
docker run --rm --pull=never --read-only --tmpfs /tmp:rw,nosuid,nodev --mount "type=bind,src=$PWD/app,dst=/workspace/app,readonly" --workdir /workspace/app --env PYTHONDONTWRITEBYTECODE=1 --env INDEX_PATH=/tmp/chago-missing.sqlite3 --env EMBEDDING_MODEL_PATH=/tmp/chago-missing-assets "$(docker compose images -q app)" sh -ec 'python -m pip install --no-cache-dir --target /tmp/test-deps pytest==9.1.1 httpx==0.28.1 && PYTHONPATH=/tmp/test-deps:/workspace/app python -m pytest -v -rs --capture=tee-sys -p no:cacheprovider --basetemp=/tmp/chago-tests tests/test_active_retrieval.py tests/test_index_state.py tests/test_hybrid_retrieval.py tests/test_hybrid_retrieval_cli.py tests/test_health.py'
```

Команда использует существующий app image без build/pull. Устанавливаются
только dev-инструменты pytest/httpx с зависимостями в tmpfs `/tmp/test-deps`
одноразового контейнера; для этой установки нужен доступ к package index.
Runtime зависимости берутся из app image. Если image отсутствует или установка
не удалась, проверка не выполнена; это не повод засчитывать gate.

Production `/data`, `.env`, model assets и Docker socket в контейнер не
монтируются; Compose environment и volumes не наследуются. Сервисные контейнеры
не запускаются и не перезапускаются. `docker compose images -q app` только
определяет локальный image. Единственный host mount — read-only `app/`;
все SQLite fixtures создаются pytest внутри `/tmp/chago-tests`. Pipeline fixture
подменяет ingestion и encoder, поэтому не требуется Wiki.js, E5 или LLM.
Контейнер не подключается к Compose/Wiki сети. Cache и запись `.pyc` отключены.

Успех: exit code 0, **30 passed, без skips**, и строка:

```text
PATHNAME_REPLACEMENT_OK: old snapshot retained; restart loaded new generation
```

Она печатается только после успешной подмены при открытом reader, сохранения
прежнего retrieval/provenance и загрузки нового поколения после close.
В Linux отказ `os.replace` приводит к failure. Вывод с summary и маркером
получен и принят выше; **1.3 закрыта, прогресс 4/29**.
Следующий шаг — live-gate 2.1 на неизменном
закреплённом llama.cpp image, без его запуска в этой команде.

## Завершённый live-gate 2.1

Оператор передал полный JSONL-вывод `bash docs/grounded-chat-api-token-smoke.sh`.
Ниже зафиксированы фактические результаты этого запуска, а не результаты
исторических отчётов или mock tests. **2.1 принята**.

| Поле | Фактическое значение |
|---|---|
| Image ID | `sha256:3646ddb3a55bdbec3eacba16f8cb435dc1dc47dee57549437b8a361982a37454` |
| Image reference / RepoDigest | `ghcr.io/ggml-org/llama.cpp@sha256:f9115c95639e60abc09d4ea83b26fd4d56c66aa1174594393335a514da00c283` |
| GGUF SHA256 | `2fde00ce69dd4899c70d020845e2638353015bba0fdf161b3eb965f2bca4464e` |
| Model alias | `Qwen3-4B-Instruct-2507`, совпал в обоих completion responses |
| Chat template fingerprint | `05991410a4bad1a587959aa5c8901f699afc639540f931afd8ba2b359e4368a9` (SHA256 JSON serialization поля `chat_template` из `/props`) |
| Context / threads / threads-batch / parallel | `8192 / 8 / 8 / 1` |
| CPU flags | `--gpu-layers 0 --device none --no-webui` |
| Model / bind / port | `/models/model.gguf`, `0.0.0.0:8080` внутри сети |
| Diagnostic nonce | `df113424ee9d49c8beded6bc4d8be683` |

| Case | Calculated | `usage.prompt_tokens` | Cached | Completion tokens | Total tokens | HTTP chain, s |
|---|---:|---:|---:|---:|---:|---:|
| `short_ru` | 65 | 65 | 0 | 16 | 81 | 3.547 |
| `context_code_unicode` | 202 | 202 | 0 | 16 | 218 | 3.244 |

Поле времени скрипта включает template/tokenize/completion и называется
`elapsed_seconds`; это не отдельный замер generation duration.

SHA256 полных template prompts:

- `short_ru`: `2f45c4f9c5aecaf328c41d0ed7e181e05d792a1c0594fa5eb6989643cd6e72b9`;
- `context_code_unicode`: `3889d29525257ac4ac01e0cf7a1b96aeff64a30366e2d0bc5f7d1486ab968760`.

В обоих сохранённых prompt suffix присутствует generation prefix
`<|im_end|>\n<|im_start|>assistant\n`. Сравнивались одинаковые messages
из двух cases скрипта с nonce выше. JSON CONTEXT содержал два fragments,
shell code, Unicode и псевдо-delimiters. Request options — ровно описанные
ниже: template generation prompt, tokenizer special-token handling и completion
с `cache_prompt=false`, `max_tokens=16`, sampling 0.2/0.8/20. В обоих usage
`prompt_tokens_details.cached_tokens=0`, точное целочисленное равенство выполнено.
Это разрешает зависимую реализацию; проверка 7.1 на окончательных messages и
границах бюджета всё ещё обязательна.

Подготовлен административный скрипт
[`grounded-chat-api-token-smoke.sh`](grounded-chat-api-token-smoke.sh).
После переноса скрипта на сервер запустить из корня проекта:

```bash
bash docs/grounded-chat-api-token-smoke.sh
```

Он использует **уже работающие** app/llm (`docker compose ps`, `docker exec`),
не делает build/pull/restart и не меняет flags/template. Читает SHA256 GGUF
через фактический bind mount source на хосте; нужны права чтения файла.
Digest image и SHA256 сверяются с закреплённой исторической identity из
`local-cpu-runtime-benchmark.md`:

- image `ghcr.io/ggml-org/llama.cpp@sha256:f9115c95639e60abc09d4ea83b26fd4d56c66aa1174594393335a514da00c283`;
- GGUF `2fde00ce69dd4899c70d020845e2638353015bba0fdf161b3eb965f2bca4464e`.

Исторические identity служат ожидаемыми значениями, а фактические будут заново
прочитаны скриптом. При несовпадении он остановится до HTTP-запросов, не меняя
runtime. В stdout сохраняются actual identity, разрешённые runtime flags,
chat-template fingerprint, context size, оба синтетических messages и options,
calculated/actual counts, prompt suffix с generation prefix и timings.
Production SQLite и Wiki.js скрипт не использует.

Путь диагностики: `/apply-template` с `add_generation_prompt=true`, затем
`/tokenize` с `add_special=true`, `parse_special=true`, `with_pieces=false`;
completion получает те же messages, sampling 0.2/0.8/20 и **диагностический**
`max_tokens=16`. Это не изменение app default reserve=768. Два разных prompts
с уникальным nonce и request-only `cache_prompt=false` исключают использование
старого prompt cache в диагностике; сравнивается именно `usage.prompt_tokens`.
Options сверены с [официальной документацией закреплённого commit](https://github.com/ggml-org/llama.cpp/blob/fc07d781e/tools/server/README.md),
совместимость на этих двух случаях подтверждена результатом выше.

Запросы последовательны, tools отсутствуют, proxies и redirects отключены.
При mismatch/missing usage/endpoint error/timeout нет retries и следующего
completion. После timeout нельзя повторять smoke до подтверждения прекращения
предыдущей серверной генерации. Требуется полный вывод скрипта для проверки
фактической identity, options, generation prefix и двух точных равенств;
exit 0 сам по себе не подменяет этот review.

Локально выполнены `bash -n`, Python compilation встроенного кода и четыре
mock-прогона diagnostic control flow: равенство, mismatch, missing usage,
ошибка tokenize endpoint. Проверено отсутствие повторного/следующего completion
после ошибки и утечки sentinel secrets. Это проверки скрипта, **не выполнение
2.1**. Bash syntax check потребовал запуск вне sandbox из-за CreateFileMapping
permission error; runtime-код приложения не менялся.

На подготовленном сервере необходимо, сохранив закреплённый image/model,
runtime flags и template:

1. Зафиксировать фактический image digest, model identity, alias и options.
2. Для короткого русского messages и отдельного messages с несколькими
   CONTEXT fragments, code/Unicode и служебным форматом выполнить
   `/apply-template` → `/tokenize` и `/v1/chat/completions`.
3. Зафиксировать точные request options, generation prefix/special tokens и
   влияние cache; сравнить полный calculated count с `usage.prompt_tokens`
   для одинаковых messages. Требуется точное целочисленное равенство в каждом
   случае. Cached-only timing counters не заменяют prompt usage.
4. Сохранить пары counts и verdict в этом отчёте. При mismatch, отсутствии
   usage либо несовместимости endpoints остановиться для решения владельца
   о точном пути, сохранив задачу открытой.

Fake-server tests, approximate counts, поправочные коэффициенты и последующая
задача 7.1 не заменяют gate 2.1. LLM client/token counter используют проверенный точный путь.
Финальные live-проверки 7.1–7.3 остаются открытыми.

## Завершённая задача 2.2

Добавлены `ChatSettings` / `load_chat_settings()` в `app/app/config.py`:
context=8192, reserve=768, конечный HTTP timeout=300 секунд; поля — positive
integers, reserve строго меньше window. Alias и sampling defaults сохранены.
Новые chat settings загружаются отдельно от process startup settings;
невалидный chat context/timeout не ломает app-only health.

Compose передаёт app `LLM_CONTEXT_SIZE` из того же `${LLM_CONTEXT_SIZE:-8192}`,
которое используется llm `--ctx-size`, и `LLM_TIMEOUT_SECONDS` default 300.
LLM image/runtime flags/template не менялись. `.env.example` и lifecycle docs
описывают значения и отсутствие timeout на ожидание очереди.

Локально из `app/` выполнены:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
../.venv/Scripts/python.exe -m pytest -q -rs -p no:cacheprovider --basetemp=../.tmp/grounded-22 tests/test_chat_config.py tests/test_config.py tests/test_llm_check.py tests/test_health.py
$env:MYPYPATH='typings'
../.venv/Scripts/python.exe -m mypy app/config.py --follow-imports=silent --cache-dir ../.tmp/mypy-grounded-chat
```

Результаты: **117 passed, 1 warning in 0.84s**, без skips; mypy — success,
1 source file. Проверены defaults/overrides, invalid integers, reserve>=window,
типизированные non-integer/NaN/infinity, безопасные ошибки и app-only health.
Первый pytest в sandbox не получил доступ к temp, повторный вне sandbox прошёл.
Полный regression не повторялся: изменения ограничены новым loader и Compose;
startup loader/LLM smoke регрессия включена в профильный прогон.

Docker CLI локально отсутствует. Оператор выполнил следующую проверку
развёрнутой Compose configuration с актуальным `compose.yaml` из корня
проекта (без up/build/restart):

```bash
docker compose config --format json | python3 -c '
import json, sys
services = json.load(sys.stdin)["services"]
env = services["app"]["environment"]
args = services["llm"]["command"]
window = int(env["LLM_CONTEXT_SIZE"])
reserve = int(env["LLM_MAX_TOKENS"])
timeout = int(env["LLM_TIMEOUT_SECONDS"])
assert window == int(args[args.index("--ctx-size") + 1]), "context mismatch"
assert 0 < reserve < window and timeout > 0, "invalid budgets"
print(json.dumps({"compose_chat_config": "ok", "context_size": window, "max_tokens": reserve, "timeout_seconds": timeout}))
'
```

Весь JSON Compose проходит только через pipe, не выводится и не сохраняется;
stdout содержит только три публичных числовых settings и verdict. Production
индекс не читается и не меняется. Получен и принят результат:

```json
{"compose_chat_config":"ok","context_size":8192,"max_tokens":768,"timeout_seconds":300}
```

**2.2 выполнена** на основании этого вывода и локальных tests, без повторного
самостоятельного запуска Compose агентом.

## Локальная реализация chat: 2.3–6.2

Добавлены `llm_client.py`, `grounding.py`, `chat.py`, `chat_api.py`,
`chat_evaluation.py`; route и lifecycle подключены в `main.py`. Отдельный
admin diagnostic `chat_token_check.py` и shell wrapper подготовлены для 7.1.
Новые runtime dependencies, публичные reindex/context overrides, history,
новые LLM flags/template, README/ROADMAP и frozen eval inputs не добавлялись.

Подтверждённые промежуточные результаты (прогоны не суммируются):

| Проверка | Результат |
|---|---|
| Fake HTTP server для LLM client, paths/options/proxy/redirect/timeout/protocol/retry | 36 passed |
| Первичный manifest/parser/packing/citation/code validator | 46 passed |
| API + grounding до дополнительных edge cases | 80 passed, 1 warning |
| Управляемые concurrency/cancellation/continued-generation barriers | 7 passed |
| Frozen evaluation harness | 6 passed |
| Расширенные grounding + final token diagnostic offline logic | 51 passed |
| Health/config/index_state/hybrid/reindex regression | 164 passed, 39 skipped, 1 warning in 11.91s |
| Mypy всех app modules | Success, 30 source files |

В regression 39 skips: 1 actual Linux flock и 38 Linux Bash/flock/signals;
это ограничения Windows, не подтверждение пропущенных проверок. Warning —
прежний TestClient/httpx deprecation. Pytest с temporary files запускался
вне sandbox после отказа sandbox в доступе к temp. Локальные fake HTTP серверы
используют только loopback; LLM/Wiki/production assets для tests не нужны.

Во время реализации исправлены: тестовый search adapter harness, false positive
Markdown reference link для соседних citations, mapping фактического E5
`embedding_budget` в 422; добавлена повторная code validation после numbering,
чтобы замена marker внутри кода не меняла подтверждённую команду. Исходные
падающие прогоны не считаются успешными; результаты выше получены после
соответствующих исправлений. Полный финальный regression фиксируется отдельно.

## Завершённый серверный gate 7.1: окончательный prompt и context boundary

Подготовлен [`grounded-chat-api-final-token-smoke.sh`](grounded-chat-api-final-token-smoke.sh).
После переноса актуальных `app/` и этого скрипта на сервер, из корня проекта:

```bash
bash docs/grounded-chat-api-final-token-smoke.sh
```

Нужны уже работающие app и закреплённый llm, существующий app image и подготовленные
индекс/E5 assets в `data/` с путями из `.env`. Сам файл `.env` не выводится.
Wrapper заново читает digest действующего image и SHA256 GGUF, затем запускает
одноразовый app client через `docker run` по Image ID действующего app,
с read-only `app/` и `/data`; production SQLite только
читается, его SHA256 до/после должен совпасть. Нет build/pull/restart llm или app
service, нет портов нового контейнера, downloads и Wiki.js access/writes.
LLM runtime flags/template остаются прежними. На время диагностики оператор
исключает параллельный chat/harness traffic; application semaphore не разделяется
между отдельными административными процессами.

Wrapper исправлен после ошибки оператора `unknown flag: --no-build`:
этот флаг отсутствует у `docker compose run`. Теперь Compose используется
только для поиска работающих контейнеров. `docker run --pull=never` запускает
уже существующий Image ID, разделяет network namespace llm и обращается к
нему через `127.0.0.1:8080`. Порты не публикуются. Через allowlist копируются
только INDEX/EMBEDDING/RETRIEVAL и публичные LLM settings действующего app;
DB credentials и прочие environment secrets не передаются. Отсутствующие
settings используют прежние defaults Python loader. Pending изменения `.env`
этим способом не применяются — проверяется действующая конфигурация.
Ошибка `--no-build` произошла до запуска diagnostic client, поэтому не дала
результата 7.1 и не отправляла completion.
Исправление проверено локально: `bash -n` и mock Docker execution с проверкой
фактических argv (existing Image ID, network namespace, read-only mounts,
сохранение пробелов в settings, отсутствие sentinel DB secret). Подмена Docker
не выполняла контейнеры/HTTP. Первая попытка mock имела ошибку индекса аргумента
в самой подмене; после её исправления проверка успешна. Полный pytest не
повторялся: Python/runtime-код не менялся. Это само по себе не закрывало 7.1;
live-результат принят ниже.

Проверяются:

1. Реальный E5/hybrid retrieval для «Как работает роутплан?» и окончательные
   system rules/JSON manifest/packing. Полный completion с текущим reserve.
2. Синтетический admin boundary fixture с тем же final prompt format: точный
   поиск через token endpoints messages, для которых calculated+reserve=8192,
   и сравнение calculated с `usage.prompt_tokens` полного completion.
3. Fixture ровно на один prompt token больше: удаление целого единственного
   chunk и отсутствие overflow completion. Каждый кандидат считается реальным
   tokenizer, нет character estimates или поправочного коэффициента.

Вывод включает actual image/model/template identity, settings, index fingerprint,
retrieved/packed IDs и пары calculated/actual. Если точная граница недостижима,
assets/index не готовы, counts/identity не совпадают или endpoint несовместим,
gate остаётся открытым. При ошибке/timeout completion нет retry или следующего
completion; требуется подтверждённое прекращение прежней генерации до повтора.

Локально проверены Bash syntax и offline logic equality/overflow/mismatch;
это **не live acceptance 7.1**. Оператор затем передал полный live-вывод
(2026-10-22), на основании которого **7.1 принята**. Остаются 7.2
(реальные case verdicts, включая sufficient evidence) и 7.3
(Compose concurrency, timeout/cancellation/recovery, offline/app-only и isolation).
Только затем может завершаться 7.4. Change не архивирован.

### Фактический результат 7.1 от оператора

Image digest, GGUF SHA256, model alias и chat template fingerprint совпали
с принятыми в 2.1 значениями:

- image `ghcr.io/ggml-org/llama.cpp@sha256:f9115c95639e60abc09d4ea83b26fd4d56c66aa1174594393335a514da00c283`;
- GGUF `2fde00ce69dd4899c70d020845e2638353015bba0fdf161b3eb965f2bca4464e`;
- alias `Qwen3-4B-Instruct-2507`;
- template fingerprint `05991410a4bad1a587959aa5c8901f699afc639540f931afd8ba2b359e4368a9`;
- context/reserve/HTTP timeout: **8192 / 768 / 300**.

| Case | Calculated | Actual prompt tokens | Prompt + reserve | Completion HTTP, s |
|---|---:|---:|---:|---:|
| `final_retrieved_prompt` | 1850 | 1850 | 2618 ≤ 8192 | 82.063 |
| `prompt_plus_reserve_equals_window` | 7424 | 7424 | 8192 = 8192 | 126.87 |

Overflow: **7425 + 768 = 8193**; `overflow_completion_sent=false`,
`overflow_context_removed_whole=true`. Финальный `gate_7_1=passed`.

Индекс: SHA256 `96159df1c9c8cfacf88727b645d87850712bf1b45507641b8aa1f412953e3c74`,
`index_unchanged=true`. Metadata: format 1, indexed_at
`2026-10-20T10:18:41.693304+00:00`, **24 documents / 910 chunks**.
Для реального запроса сохранены и переданы все шесть retrieved IDs:

```json
["45d55467ee65d4684bf160ad725aae9bc6efa48f6208ae8006860eda808e8132","fba8058ab5f3fb60a77ef52684241f32e535c0434c0df763e68eb8558b4bfcce","038d1a279825ee78784f1e7464ee2e4c824c340a049fb31faa3712a698ecebac","5e13d3960bd6484b1c387d0ffa605b8faee1864e389c2d8e3f01315ec7a03dc7","0d500e60d97179b58c06832cbe4a206d4fdea6064073ac44f9ed156203fd0149","930d4ed2b3d524c71a584750dbd211adfbbbeef56dc06712532e712708298fce"]
```

Источник — фактический JSONL-вывод оператора, не повторный live-запуск агента.
Результат подтверждает token accounting и границы бюджета, но не заменяет
case review качества Qwen из 7.2 или concurrency/recovery из 7.3.

## Следующая задача 7.2: frozen corpus и ручная оценка

Локальная подготовка 2026-10-22: `validate_package` подтвердил текущий frozen
package; `StorageReader` подтвердил полное совпадение source/document inventory
обоих подготовленных evaluation-индексов с reference. Fixed-evidence manifest
построен для каждого single-question case без изменения inputs.

| Локальный input | SHA256 / inventory |
|---|---|
| Frozen live reference | `63ad12fec898ef6c73c5c37a66d18e0d1327c91f1f79102dfa646cadd8c9f95f` |
| Frozen synthetic reference | `9fe75320ace79ef6ee707f189137c6fd9fd886341b65395c87393ea4f2d9cf1a` |
| `data/hybrid-live.db` | `87fa5e9b2af30044a509d19c16440db2545d5941f0eab3d3795a9e6af7d2fa44`, 24 documents / 910 chunks |
| `data/hybrid-synthetic.db` | `e4b1d1f10d218c92fae848e7ec88c94ccf24d7c2eacf49cd85e265be5052ab89`, 1 document / 1 chunk |

Это identity локальных evaluation-индексов, а не требование совпадения бинарного
SQLite hash сервера с Windows. На сервере runner проверяет document inventory
и frozen reference identity и сохраняет фактические index fingerprints.
Production-индекс из 7.1 не используется вместо отдельного frozen набора.

Всего **18 single-question cases**. Все `answerable=false`: **q13–q17**;
partial=q12, clarify=q13, conflict=q18, injection=q20, similar identifiers=q07,
long code=q08. Follow-up q09/q10 исключены из обоих прогонов.

Подготовлен [`grounded-chat-api-evaluate.sh`](grounded-chat-api-evaluate.sh).
Перенести актуальные `app/`, `eval/` и скрипт на сервер; из корня проекта:

```bash
bash docs/grounded-chat-api-evaluate.sh
```

Нужны работающие app/llm и заранее подготовленные frozen файлы:
`data/eval/1/wiki-documents.json`, `data/hybrid-live.db`,
`data/hybrid-synthetic.db`. Если evaluation SQLite хранятся в другом месте,
переменные `FROZEN_SNAPSHOT`, `FROZEN_LIVE_INDEX`, `FROZEN_SYNTHETIC_INDEX`
задают их container paths под `/data/`; отсутствующие файлы дают остановку
до генерации. Скрипт не строит индексы и не подменяет frozen inputs.

При запуске оператором получено `Missing frozen input: /data/hybrid-live.db`:
проверка остановилась до генерации, задача 7.2 остаётся открытой.
В [отчёте серверной hybrid-приёмки](lexical-and-hybrid-retrieval-server-acceptance.md#фактический-серверный-отчёт-2026-10-09)
сохранён каталог `data/acceptance/lexical-and-hybrid-retrieval/run-20261009T185137Z-YCmy22/`.
Если исходные evaluation-индексы в нём сохранены, из корня серверного проекта:

```bash
FROZEN_LIVE_INDEX=/data/acceptance/lexical-and-hybrid-retrieval/run-20261009T185137Z-YCmy22/hybrid-live.db \
FROZEN_SYNTHETIC_INDEX=/data/acceptance/lexical-and-hybrid-retrieval/run-20261009T185137Z-YCmy22/hybrid-synthetic.db \
bash docs/grounded-chat-api-evaluate.sh
```

Наличие этих файлов на сервере локально не подтверждено; runner проверит его
перед генерацией. Команда читает отдельные evaluation-индексы через read-only
mount и не изменяет production-индекс. Если файлы отсутствуют и здесь, требуется
найти сохранённые исходные evaluation-индексы; подменять их production SQLite
нельзя.

Последовательно запускаются все end-to-end cases, затем все generation-only
cases на заданных исходных evidence ranges. Каждый вызов использует текущий
резерв/HTTP timeout; требуется исключить другой chat/harness traffic. Прогон
может занять десятки минут. При ошибке, timeout или обрыве второго запуска
после неуспешного первого не будет. Retry отсутствует; после uncertain timeout
нужно подтвердить прекращение прежней генерации до нового запуска.

Используется Image ID уже работающего app, pinned LLM identity проверяется
повторно. Код, `eval/` и `/data` смонтированы read-only, namespace llm общий,
портов нет. Только публичные settings копируются из app; DB credentials не
передаются. Нет build/pull/restart, Wiki access/writes, model downloads или
записи в исходные corpus/SQLite. Уникальный host report directory
`data/grounded-chat-api-eval.XXXXXXXX` создаётся с umask 077, старые reports
не перезаписываются. В нём:

- `end-to-end.jsonl` и `generation-only.jsonl`: case строки и успешный summary;
- `.stderr` для каждого режима;
- `image-digests.json` и `model.sha256` для фактической LLM identity.

Отчёты содержат source quotes; хранить с теми же правами, что frozen corpus.
Нужно передать оба `.jsonl` и `.stderr` для review. Поля `manual_verdict=pending`
не являются pass. Требуется проверить required facts, поддержку каждого claim
packed citations, точность commands, refusal/clarify/partial и обе стороны
conflict. Case verdicts и различение retrieval/context misses от generation
failures сохраняются после фактического вывода и review. Generation-only кейсы
без evidence отказывают без completion и не считаются испытанием Qwen на nearby
контексте — для них необходим end-to-end результат. Порог Hit@5 ≥90% не вводится.

Локально проверены `bash -n` и mock execution wrapper: последовательный запуск
двух режимов, разные JSONL/stderr files, public-only environment с сохранением
пробелов, read-only mounts и existing Image ID. При искусственной ошибке первого
прогона второй `docker run` отсутствовал. Реальные Docker/LLM не вызывались;
Bash проверки выполнялись вне sandbox из-за его CreateFileMapping restrictions.
Полный pytest/mypy повторно не запускались: Python/runtime-код не менялся.

**7.2 остаётся открытой.** Реальный corpus на Qwen в этой локальной среде не
запускался; validation inputs и wrapper checks не заменяют серверную приёмку.

## Итог локальной реализации: 6.3

После исправлений выполнен полный `pytest` из `app/`:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
../.venv/Scripts/python.exe -m pytest -q -rs -p no:cacheprovider --basetemp=../.tmp/grounded-full
$env:MYPYPATH='typings'
../.venv/Scripts/python.exe -m mypy app --follow-imports=silent --cache-dir ../.tmp/mypy-grounded-chat
```

- **1011 passed, 46 skipped, 1 warning in 75.35s**.
- 46 skips: 3 symlink privilege cases, 4 POSIX permission cases, 1 actual Linux
  flock case и 38 actual Linux Bash/flock/signals cases. Они не засчитываются
  как пройденные Linux checks; нужны предусмотренные серверные проверки.
- Единственный pytest warning — существующий TestClient/httpx deprecation.
- Mypy: **Success: no issues found in 30 source files**.
- `bash -n docs/grounded-chat-api-final-token-smoke.sh`: успешно; скрипт
  в этой среде не выполнялся, Docker CLI по-прежнему отсутствует.
- `openspec validate grounded-chat-api --strict` и `openspec validate --all --strict`
  (через Windows `.cmd` shim): change valid, **11 passed / 0 failed**.
- `git diff --check`: exit 0. Diff проверен: отсутствуют изменения README,
  ROADMAP, frozen inputs/expectations/baselines, архивных changes и зависимостей.

После принятия live-вывода **выполнено 26/29 задач: 1.1–7.1**.
Задачи **7.2–7.4 открыты**; 7.4 не считается
завершённой по одной валидации specs, поскольку итоговое соответствие зависит
от live acceptance. Новых результатов Qwen, corpus verdicts, Compose recovery
и offline restart в этом разделе не заявлено.
