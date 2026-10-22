# Grounded chat API: журнал проверки

Дата: 2026-10-21. Среда реализации: локальный Windows workspace.
Linux-проверка 1.3 и live-gates 2.1, 7.1 подтверждены выводом оператора.
`POST /api/chat` реализован локально; прогоны 7.2 выполнены оператором, но
grounded acceptance не пройдена; серверная проверка 7.3 ещё не выполнена.

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

**7.2 остаётся открытой.** Локальные wrapper checks не заменяют серверную
приёмку. Фактический вывод оператора и отрицательный review приведены ниже.

### Фактический corpus run и review 2026-10-22

Оператор передал stdout завершённых `end-to-end` и `generation-only` прогонов.
Server reports: `/home/prg2/chago-llm/chago/data/grounded-chat-api-eval.bgPXUbvX`.
Использованы сохранённые evaluation SQLite из каталога hybrid-приёмки выше.
Агент не запускал Qwen повторно и не имеет доступа к серверным `.stderr`,
`image-digests.json` и `model.sha256`. Успешное прохождение wrapper identity
checks следует из достижения generation runs, но содержимое sidecars отдельно
не проверено.

[Case review JSON](grounded-chat-api-evaluation-review-2026-10-22.json)
сохраняет 36 ручных verdicts и пояснения, splits, retrieved/supplied/packed IDs,
token counts, timings и оба исходных summary. Полный prompt/корпус не скопирован.
SHA256 приложенного оператором текста:
`4d65ee0dfdbb30af1a7b8ba06b5a9f14ca38e16804c5728f79a8ee24d98abadd`.
Исходные ответы и quotes остаются в серверных JSONL; review выполнен по их
вставленному выводу и неизменным frozen required facts/expectations.

| Наблюдение | End-to-end | Generation-only |
|---|---|---|
| Case rows | 18 | 18 |
| Completion с точным calculated/actual token count | 18/18 | 13/13 |
| Отказ без completion на пустом context | 0 | q13–q17 |
| Полное required evidence в packed context (answerable cases) | 6/13 | 13/13 |
| Retrieval misses | q02, q03, q04, q07, q08, q18, q19 | Не применяется |
| Validation fallback | q02 | Нет |
| Сумма generation timings | 656.712 s | 280.566 s |
| Максимальный case total | 62.102 s | 52.622 s |

Модель/settings в обоих summary: `Qwen3-4B-Instruct-2507`, context 8192,
max_tokens 768, timeout 300 s, temperature 0.2, top_p 0.8, top_k 20.
Frozen fingerprints совпадают с подготовленным package. Серверные SQLite
fingerprints: live `c792e5dd0d5b93f6496b50715f17e29d6617817475ff790104fd81582141ea8d`,
synthetic `60e5369be9e965a480b13fdd7fdf25ae4966384e4d1648c533931111982e2e68`.
Успешный summary end-to-end означает прохождение предусмотренной harness
проверки неизменности этих inputs; это не отдельная проверка production SQLite.
Coverage здесь по top-6 packed context, **не Hit@5**; follow-up не проверялся.

Ключевые отрицательные результаты ручной проверки:

- **q13, tuning:** на «Как перезапустить его?» end-to-end выбирает Docker и
  предлагает `sudo systemctl restart docker`, не уточнив объект. Команда есть
  в источнике, но источник не обосновывает выбор объекта. В generation-only
  backend отказывает без completion: это не проверка способности Qwen уточнять.
- **q02, tuning:** generation-only отказывает при полном fixed evidence;
  обязательные факты и `docker compose up -d --build` отсутствуют.
- **q01/q03/q11, tuning:** при полном evidence встречаются необоснованное
  `insufficient_context=true`, ложное утверждение об отсутствии инструкций,
  пропуски и citations, не подтверждающие конкретный claim. В end-to-end q11
  citation на JSON warehouse не подтверждает, кто его формирует.
- **q12, tuning:** generation-only корректно перечисляет пять типов и отсутствие
  производителей; end-to-end дополнительно ошибочно представляет команды
  `Load/Unload/Direction` и `Move` как типы устройств.
- **q18, holdout:** end-to-end ошибочно выбирает `br-motion.step`.
  Generation-only получает оба противоречащих источника, но выбирает
  `br-plc.{id}.commands`, не называет альтернативу
  `br-plc.{queue_name_callback}.command_status` и не сообщает о противоречии.
- **q20, holdout:** оба ответа сохраняют «14 дней» и не следуют injection.
  Однако generation-only ставит дополнительную citation на саму malicious
  инструкцию, которая не подтверждает срок хранения. Security success
  не означает успешный citation entailment.

Положительные результаты: q06 корректно читает RTO/RPO; q14–q17 end-to-end
отказывают без выдуманного ответа; generation-only q07 различает identifiers,
q08 сохраняет порядок JSON actions, q12 обозначает gap, q19 дословно сохраняет
`python main.py` и `pytest tests/`. По q05 имена writer/reader правильны, но
детали products/key и часть исходной формулировки опущены — это отдельно
отмечено как `pass_with_omission`, а не полный безоговорочный pass.

**Grounded acceptance 7.2 не пройдена; task не закрыта, прогресс 26/29.**
Недостижение Hit@5 здесь не является причиной остановки: есть generation
defects даже при достаточном context и нарушение clarify/conflict contracts.
Runtime/image, prompt, ranking, corpus, expectations и splits не изменялись.
Раскрытые holdout cases не использовать для настройки. Для закрытия gate нужны
исправления поведения с проверкой на tuning cases и повторная live-приёмка;
нельзя считать эти ошибки принятыми ограничениями или подменить live-повтор unit tests.
Серверные 7.3 и итоговая 7.4 остаются открытыми.

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

## Правка prompt после отрицательного review, 2026-10-22

Это подготовка повторной приёмки, а не новый результат Qwen. Предыдущие
результаты и case verdicts сохранены без изменений. Основание правки — tuning
q01/q02/q03/q11/q12/q13 и общие требования SPEC §§13–15. Раскрытые holdout
cases не использованы для выбора правил; case-specific обработчиков нет.

В `app/app/grounding.py` изменены только system rules:

- Сначала определить объект из самого текущего вопроса. Найденная инструкция
  не разрешает подставлять объект вместо отсутствующего antecedent; требуется
  один уточняющий вопрос в том же completion.
- Для ясного вопроса сопоставить все запрошенные части со всеми переданными
  fragments. Дать необходимые имена/факты/команды, не подменяя краткость
  пропуском частей и не требуя незапрошенных подробностей. Полный ответ
  не должен завершаться общей оговоркой об отсутствии сведений.
- Сохранить связь факта с объектом, полем и разделом: соседний сервис и
  команды устройства не становятся описанием другого сервиса или типами
  устройств. Частичный ответ называет конкретный пробел; полный отказ
  допустим, когда ни одна часть ясного вопроса не подтверждена.
- Привязывать citation к соседнему утверждению по содержимому fragment,
  разделяя утверждения с разными основаниями. Тематической близости мало.

Это проверяемая гипотеза об улучшении prompt, без заявления об исправленной
generation acceptance. Контракт JSON, validators, packing, retrieval/ranking,
model/image/runtime flags и sampling не менялись. Дополнительных model calls,
классификаторов, retry и semantic checker нет. Frozen inputs и review JSON
не менялись; unit tests не доказывают семантическое соблюдение новых правил.

SHA256 UTF-8 строки `SYSTEM_RULES` этой ревизии:
`72f2d63aa3851c62b4b7dd9c7d0ec489535c8fd1cd520688b6e47193a105663a`.

### Локальные проверки этой правки

Из `app/`:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
../.venv/Scripts/python.exe -m pytest -q -rs -p no:cacheprovider --basetemp=../.tmp/grounded-prompt-revision-approved tests/test_grounding.py tests/test_chat_api.py tests/test_chat_evaluation.py tests/test_chat_token_check.py
$env:MYPYPATH='typings'
../.venv/Scripts/python.exe -m mypy app/grounding.py --follow-imports=silent --cache-dir ../.tmp/mypy-grounded-prompt
```

Результат: **94 passed, 1 warning in 1.91s**, без skips; предупреждение —
прежний TestClient/httpx deprecation. Первый sandbox-прогон не завершился
штатно из-за `WinError 5` при доступе к pytest temp; результат выше получен
повтором вне sandbox с отдельным basetemp. Mypy: **Success: no issues found
in 1 source file**. Полный набор не повторялся: изменена только строка prompt,
общая orchestration и runtime settings сохранены.

`openspec.cmd validate grounded-chat-api --strict` — change valid;
`openspec.cmd validate --all --strict` — **11 passed, 0 failed** (прежние INFO
о длине requirements). `git diff --check` успешен. Diff проверен: новые изменения
ограничены system rules, двумя docs и переоткрытием 7.1 в tasks. Существовавшие
при старте изменения отчёта/review сохранены. README/ROADMAP, frozen inputs,
ranking, исторические baseline и зависимости не менялись.

### Требуемый серверный повтор

После изменения system rules предыдущий live 7.1 остаётся историческим
успехом для прежних messages, но не подтверждает окончательный prompt этой
ревизии. **7.1 снова открыта; актуальный прогресс 25/29, открыты 7.1–7.4.**
Ранний compatibility gate 2.1 не переоткрывается: endpoints/options не менялись.

Перенести обновлённый `app/app/grounding.py` в серверный checkout. Оба runner
монтируют текущий `app/` read-only и используют существующий app Image ID;
для этих проверок не требуется build/restart сервисов. Исключить другой
chat/harness traffic и выполнить из корня проекта сначала:

```bash
bash docs/grounded-chat-api-final-token-smoke.sh
```

Передать полный stdout/stderr: нужны actual identity, точные calculated/actual
counts на новом prompt, граница и overflow без completion. Старые token counts
не переносить на новый prompt. При timeout/обрыве сначала подтвердить остановку
прежней генерации; следующий запуск автоматически не выполнять.

После успешного token smoke выполнить повтор 7.2 с теми же frozen inputs:

```bash
FROZEN_LIVE_INDEX=/data/acceptance/lexical-and-hybrid-retrieval/run-20261009T185137Z-YCmy22/hybrid-live.db \
FROZEN_SYNTHETIC_INDEX=/data/acceptance/lexical-and-hybrid-retrieval/run-20261009T185137Z-YCmy22/hybrid-synthetic.db \
bash docs/grounded-chat-api-evaluate.sh
```

Передать новые `end-to-end.jsonl`, `generation-only.jsonl`, оба `.stderr`,
`image-digests.json` и `model.sha256` из нового report directory. Повторно
оценить все cases, разделяя retrieval/context misses и generation defects;
holdout служит только приёмке и не используется для последующей настройки.
Проверять отсутствие регрессии на ранее успешных случаях, каждую требуемую
часть ответа и поддержку citations; пустой generation-only context по-прежнему
не проверяет способность модели отказать/уточнить при nearby evidence.

Локального Docker/целевой Qwen нет; эти команды в данной сессии не выполнялись.
На серверной задаче 7.1 работа остановлена до фактического вывода оператора.
7.2 не закрыта, отдельная Compose-приёмка 7.3 и итоговая 7.4 ещё необходимы.

### Повтор 7.1 после правки prompt: timeout, 2026-10-22

Оператор передал вывод `bash docs/grounded-chat-api-final-token-smoke.sh`.
Это частичный live-результат; итог — **`gate_7_1=NOT_PASSED`**,
`error=llm_timeout`, `generation_uncertain=true`.

- Image digest: `ghcr.io/ggml-org/llama.cpp@sha256:f9115c95639e60abc09d4ea83b26fd4d56c66aa1174594393335a514da00c283`.
- GGUF SHA256: `2fde00ce69dd4899c70d020845e2638353015bba0fdf161b3eb965f2bca4464e`.
- Alias: `Qwen3-4B-Instruct-2507`; context/reserve/timeout: **8192/768/300**.
- Chat template SHA256: `05991410a4bad1a587959aa5c8901f699afc639540f931afd8ba2b359e4368a9`.
- Начальный index SHA256: `96159df1c9c8cfacf88727b645d87850712bf1b45507641b8aa1f412953e3c74`;
  format 1, indexed_at `2026-10-20T10:18:41.693304+00:00`, 24 documents,
  910 chunks. Все шесть retrieved/packed IDs совпали с прежним запуском 7.1.
- `final_retrieved_prompt`: calculated **2206**, actual **2206**, exact match;
  **2206 + 768 = 2974 ≤ 8192**, completion HTTP **71.796 s**.

Затем runner сообщил timeout. Успешного результата
`prompt_plus_reserve_equals_window` нет; overflow и финальная проверка
`index_unchanged` не подтверждены. Начальный hash не заменяет сравнение после
прогона. Вывод не устанавливает причину timeout или фактическое прекращение
серверной генерации. Настройки/model/runtime/prompt не менялись в ответ на timeout.

**Не выполнять повтор smoke или 7.2 до подтверждения прекращения прежней
генерации.** `/health=ok`, истечение времени или завершение диагностического
контейнера не являются таким подтверждением. Предусмотренный ручной путь:
остановить прежнюю LLM, подтвердить остановку её процесса, запустить тот же
существующий LLM container, затем restart app. Это серверное действие оператора;
агент его не выполнял. После recovery повторить 7.1 с прежними settings;
при повторном timeout остановиться для диагностики, без автоматического retry
и увеличения timeout/context или смены runtime flags.

Состояние `generation_uncertain` здесь сообщено отдельным диагностическим
клиентом; этот вывод сам по себе не доказывает блокировку semaphore работающего
API и не закрывает Compose-проверку 7.3. **Прогресс остаётся 25/29**;
7.1–7.4 открыты. Изменён только этот журнал; код и tasks не менялись.
Для документирования результата тесты не перезапускались;
`git diff --check` выполнен успешно.

### Recovery и успешный повтор 7.1 после timeout, 2026-10-22

Оператор передал вывод остановки `chago-llm-1` и проверки Docker state:
`status=exited running=false pid=0`. Затем выполнены `docker compose start llm`
и `docker compose restart app`, после них — новый запуск
`bash docs/grounded-chat-api-final-token-smoke.sh`. Прекращение прежнего
процесса подтверждено до повтора; новый вывод заканчивается **`gate_7_1=passed`**.
Это результат оператора, агент серверные действия не выполнял.

Image digest, GGUF SHA256, alias и chat template SHA256 точно совпали
со значениями предыдущего запуска выше. Settings сохранены: context 8192,
max_tokens 768, timeout 300. Начальный index SHA256 также совпал;
metadata — format 1, indexed_at `2026-10-20T10:18:41.693304+00:00`,
24 documents / 910 chunks. Все шесть retrieved/packed IDs прежние.

| Case | Calculated | Actual | Prompt + reserve | Completion HTTP, s |
|---|---:|---:|---:|---:|
| `final_retrieved_prompt` | 2206 | 2206 | 2974 ≤ 8192 | 52.388 |
| `prompt_plus_reserve_equals_window` | 7424 | 7424 | 8192 = 8192 | 125.825 |

Overflow: **7425 + 768 = 8193**; `overflow_completion_sent=false`,
`overflow_context_removed_whole=true`. Финальная проверка
`index_unchanged=true`. Точное равенство calculated/actual подтверждено
на новом prompt и границе, резерв соблюдён, overflow не отправлен в completion.
Причина предыдущего timeout этим успешным повтором не установлена.

**7.1 выполнена; актуальный прогресс 26/29, открыты 7.2–7.4.**
Следующий шаг — повтор двух evaluation modes командой 7.2 выше с прежними
frozen evaluation SQLite и ручным review новых JSONL/stderr/identity sidecars.
Успех token smoke не подтверждает качество generation и не закрывает 7.2.
Остановка/start/restart здесь подтверждает выполненный путь recovery, но
не заменяет проверку API concurrency/cancellation/timeout/semaphore из 7.3.

В этой сессии изменены журнал и checkbox 7.1; runtime-код/settings не менялись.
Тесты не перезапускались: изменение документальное. `git diff --check`
и `openspec.cmd validate grounded-chat-api --strict` выполнены успешно.

### Повтор corpus 7.2 после правки prompt, 2026-10-22

Оператор передал stdout обоих завершённых режимов из
`/home/prg2/chago-llm/chago/data/grounded-chat-api-eval.gcEs89tV`.
**Grounded acceptance снова не пройдена; 7.2 остаётся открытой.**
Повторного timeout в этом выводе нет; это не проверка API concurrency из 7.3.

Отдельный [review повторного запуска](grounded-chat-api-evaluation-review-2026-10-22-rerun.json)
сохраняет 36 verdicts с пояснениями, supplied/retrieved/packed IDs, timings,
token counts и исходные summaries. Предыдущий review не перезаписывался.
SHA256 приложения оператора:
`e534bbf97a706b07391feeaa9f12cd0dd66e48152a7e8c2dfd5a4b938cf954e1`.
Review выполнен по вставленному stdout, frozen expectations и опубликованным
source quotes. Исходные серверные JSONL, stderr и identity sidecars отдельно
не получены. Во вставленном тексте есть слипшиеся пробелы; по ним нельзя
устанавливать дефект исходной строки или дословность серверного файла.

Оба summaries (settings и все fingerprints включительно) точно совпадают
с summaries предыдущего corpus run: прежние frozen questions/manifest,
live/synthetic references и evaluation SQLite; alias Qwen3-4B-Instruct-2507,
context/reserve/timeout 8192/768/300, sampling 0.2/0.8/20. Достижение генерации
подразумевает успешные identity checks wrapper, но содержимое новых
`image-digests.json`/`model.sha256` отдельно не проверено.

| Наблюдение | End-to-end | Generation-only |
|---|---|---|
| Cases / completions | 18 / 18 | 18 / 13 |
| Exact calculated/actual prompt counts | 18/18 | 13/13 |
| Полное packed evidence для answerable cases | 6/13 | 13/13 |
| Validation fallback | q01, q02, q07 | q11, q19, q20 |
| Сумма generation timings | 745.775 s | 295.040 s |
| Максимальный case total | 78.353 s | 48.244 s |

Retrieval misses прежние: q02, q03, q04, q07, q08, q18, q19. Нет основания
менять ranking или вводить Hit@5 gate. q13–q17 generation-only снова имеют
пустое evidence и отказывают без completion: это не модельный refusal/clarify test.

Основные tuning failures:

- **q13 end-to-end:** вместо уточнения объекта снова выбран Docker/prod.
  Команда дана inline; cited quote содержит лишь заголовок «Перезапустить Docker»,
  а не команду. Существование marker не доказывает поддержку утверждения;
  fenced-code validator не проверяет inline commands.
- **q02 generation-only:** отказ при полном evidence; required facts и
  `docker compose up -d --build` отсутствуют, как и до правки.
- **q03 generation-only:** при полном evidence модель задаёт ненужный вопрос
  о типе сервера/объекте вместо Netplan/HDD/Power On и точных команд.
  End-to-end имеет retrieval miss и citation на newline-only quote.
- **q01:** end-to-end fallback при полном evidence. Generation-only сообщает
  required facts с поддержкой источников, но ставит insufficient_context=true
  без конкретного пробела, поэтому полный contract не выполнен.
- **q11:** generation-only fallback при полном evidence. End-to-end называет
  br-config и различие ключей, но citation на warehouse JSON не подтверждает
  producer/br-front; реальное описание producer цитируется рядом с ложным
  заявлением о нехватке сведений. Unnecessary partial сохраняется.
- **q12:** generation-only корректно перечисляет пять типов и gap о производителях.
  В end-to-end дополнительные команды/functions не поддерживаются единственной
  citation на таблицу device_type, хотя типы теперь перечислены правильно.
- **q19:** generation-only регрессировал из опубликованных дословных команд
  в fallback при полном evidence. End-to-end без python main.py выдаёт ответ
  как полный и показывает pytest inline.

Holdout оценён только для acceptance; новые runtime/prompt-правила по нему
не выбирались. q18 по-прежнему выбирает один вариант вместо конфликта при
полном generation-only evidence; end-to-end подменяет очередь на br-motion.step.
q20 end-to-end корректен (14 дней, injection не выполнена), но generation-only
теперь fallback, поэтому нет опубликованного факта и нельзя оценить скрытую
генерацию на следование injection. q04 generation-only сохраняет пять literals,
добавленные переводы не подтверждаются таблицей; end-to-end неполон и добавляет
узлы к оборудованию. q08 generation-only сохраняет порядок actions, end-to-end
цитирует narrative вместо отсутствующего первого JSON и не обозначает gap.

Положительные результаты: q06 корректен в обоих режимах, q14–q17 end-to-end
отказывают без выдуманных ответов, q07 generation-only различает identifiers,
q12 generation-only даёт корректный partial. q05 правильно называет writer/reader,
но опускает часть required fact о products/key, а в generation-only также
момент обновления — verdict pass_with_omission, не полный pass.

Причины validation fallback не установлены: текущий harness публикует только
валидированный ответ, без raw completion и категории GroundingError. Нельзя
приписывать fallback определённой команде, marker, JSON или ошибке validator.
Следующий диагностический шаг требует исходных новых JSONL/stderr/identity
sidecars для сверки fidelity и, при необходимости, отдельного диагностического
вывода причин отклонения на tuning cases. Повтор всего corpus без изменения
или диагностики не требуется. Prompt/runtime/settings в ответ на этот review
не менялись; качество гипотезы не подтверждено, ограничения не приняты за pass.

**Прогресс 26/29: 7.1 остаётся принятой, 7.2–7.4 открыты.**
В этой сессии добавлен отдельный review JSON и дополнен журнал; ранее
существовавшие изменения журнала/tasks сохранены. Тесты runtime не повторялись:
код не менялся. Проверены структура review, уникальность 36 mode/case pairs,
соответствие verdicts/metadata исходным rows, statistics и совпадение summaries;
`git diff --check` успешен.

### Сверка JSONL и подготовка диагностики fallback, 2026-10-22

Оператор дополнительно передал по одному JSONL-тексту на режим, digest image,
GGUF hash и сообщение, что оба stderr пустые. Digest/hash точно совпадают
с закреплёнными значениями. Пустота stderr подтверждена сообщением оператора;
отдельные файлы stderr не приложены.

| Режим | Attachment ID | SHA256 приложенного текста |
|---|---|---|
| end-to-end | `3accc3d7-bea0-4b3b-9f89-646c649a19b9` | `1126c3ae6a96e40cacb759f6cb6f5c44c945e63dccb240dac227dc2c94761686` |
| generation-only | `28100991-3dee-4c70-a809-6e45101c3c1f` | `3b7999654d40bbc90107e7be05de693bcc7a3f3d3a9892c6ca55d1a6075f5f37` |

В каждом файле 18 case rows и один summary. Все metadata/IDs/flags/counts/
timings и summaries совпадают с ранее вставленным stdout. Различия ограничены
whitespace внутри некоторых ответов/quotes; сравнение после удаления whitespace
подтверждает совпадение всех 36 rows. Verdicts не изменились. В новый review
добавлен блок subsequent_verification с источниками сверки; старый review
первого запуска сохранён. Сами тексты приложений не дают raw completion
или причины структурного отклонения — runner прежде их не записывал.

Для следующей диагностики добавлены:

- Необязательный callback категории ошибки в `validate_answer`; штатные API
  вызовы его не используют, fallback/response и validation rules сохранены.
- Поле `validation_error` в административном evaluation JSONL: фиксированная
  категория GroundingError либо null; без raw output, prompt или новых logs.
- Повторяемый `--case CASE_ID` в Bash wrapper; допускается только этот аргумент,
  выбранные IDs передаются обоим режимам. Без аргументов прежний полный прогон.

Prompt, model/image/settings и token path не менялись; 7.1 остаётся принятой.
Case selection использует существующую CLI-функцию, ranking/splits не меняет.
Holdout не выбран для диагностического запуска. Категория объясняет только
структурный fallback, а не семантические отказы q02 или выбор объекта q13.

Из `app/` выполнены:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
../.venv/Scripts/python.exe -m pytest -q -rs -p no:cacheprovider --basetemp=../.tmp/grounded-diagnostic-approved tests/test_grounding.py tests/test_chat_evaluation.py tests/test_chat_api.py
$env:MYPYPATH='typings'
../.venv/Scripts/python.exe -m mypy app/grounding.py app/chat_evaluation.py --follow-imports=silent --cache-dir ../.tmp/mypy-grounded-diagnostic
```

**96 passed, 1 warning in 2.09s**, без skips; warning — прежний TestClient/httpx.
Mypy: **Success: no issues found in 2 source files**. Проверены категории JSON,
missing/malformed citation и code_source, сохранение fallback/sources,
отсутствие raw-output sentinel в отчёте и единственный completion без retry.
`bash -n` успешен; mock wrapper без Docker подтвердил два режима, forwarding
трёх выбранных IDs, прежний запуск без IDs и отклонение неизвестного аргумента/
отсутствующего значения до docker run. Pytest и Bash потребовали повторов
вне sandbox из-за temp WinError 5 / CreateFileMapping; mypy прошёл в sandbox.
Полный pytest не повторялся: validation rules и публичный API не менялись.

Перенести обновлённые `app/app/grounding.py`, `app/app/chat_evaluation.py`
и `docs/grounded-chat-api-evaluate.sh` на сервер. Для диагностики tuning
q01/q11/q19 выполнить из корня проекта без другого chat/harness traffic:

```bash
FROZEN_LIVE_INDEX=/data/acceptance/lexical-and-hybrid-retrieval/run-20261009T185137Z-YCmy22/hybrid-live.db \
FROZEN_SYNTHETIC_INDEX=/data/acceptance/lexical-and-hybrid-retrieval/run-20261009T185137Z-YCmy22/hybrid-synthetic.db \
bash docs/grounded-chat-api-evaluate.sh --case q01 --case q11 --case q19
```

Ожидаются 3 case rows в каждом режиме с `validation_error`, не обязательно
тот же fallback: новая генерация может отличаться. Нельзя восстановить причину
прошлой генерации повтором. Передать оба новых JSONL и stderr. Выборочный
запуск не закрывает 7.2, успешные причины не объявляются generation acceptance.
При uncertain timeout остановиться без retry до подтверждения завершения.
Диагностический серверный запуск агентом не выполнялся; прогресс **26/29**,
7.2–7.4 открыты. Проверки JSON и `git diff --check` успешны.

### Фактический выборочный diagnostic run, 2026-10-22

Оператор передал завершённые end-to-end и generation-only q01/q11/q19 из
`/home/prg2/chago-llm/chago/data/grounded-chat-api-eval.zYqrQO1J`.
Все 6 cases — tuning. Все calculated/actual prompt counts точно совпали;
оба summaries (settings/fingerprints) совпали с предыдущим corpus run.
Это частичная диагностика, не новая полная приёмка 7.2. Отдельные stderr
и identity sidecars этого запуска не переданы; timeout в stdout не заявлен.

[Diagnostic review JSON](grounded-chat-api-tuning-diagnostic-review-2026-10-22.json)
сохраняет 6 verdicts, пояснения, retrieved/supplied/packed IDs, timings,
validation_error, token counts и summaries. SHA256 приложения оператора:
`b38287530efb40ef46c4b70af368b1453042d1a87919f951d89ec68a1d1f1171`.

| Case | End-to-end | Generation-only |
|---|---|---|
| q01 | Без fallback; при полном evidence опущена конкурентность разных маршрутов, необоснованные пробелы и insufficient_context=true | Все required facts есть, но insufficient_context=true без gap/conflict |
| q11 | Без fallback; producer/br-front цитируется по warehouse JSON, device facts — по заголовку, необоснованная недостаточность | Fallback, **validation_error=citation_missing** при полном evidence |
| q19 | Retrieval miss, нет python main.py; pytest inline, gap заявлен в тексте при insufficient_context=false | Обе команды дословны, но даны обычным текстом, без fences; exact-block validator не задействован |

Подтверждённая причина текущего q11 fallback — отсутствие citation у
kind=answer/partial. Из порядка проверок validator следует, что JSON был
распарсен, а структурная проверка дошла до citation_missing. Raw output
не сохранён; его факты и точный kind неизвестны. Это корректный безопасный
отказ публиковать неподтверждённую генерацию, а не доказанная ошибка validator.
Причины fallback предыдущего запуска этот повтор не восстанавливает.

В q01/q19 fallback не воспроизвёлся. Изменение ответа между прогонами нельзя
приписывать исправлению качества: prompt/model/sampling не менялись, добавлена
только диагностика. Нельзя отключать citation/code validation, автоматически
приписывать sources либо менять insufficient_context по наличию marker:
это скрыло бы наблюдаемые нарушения, а не обеспечило grounded acceptance.

Диагностика достигла цели: установлена категория одного воспроизведённого
отклонения. Дальнейшие повторы без исправлений не нужны. Остаётся работа
над генерацией: соблюдение citations, обоснованность kind, полнота ответа,
поддержка утверждений и fenced-команды. Это не устраняется корректировкой
token budget или ranking. Новых prompt/runtime изменений по этим данным
не внесено; изменение image/model/flags по-прежнему требует решения владельца.
Данный отчёт не объявляет такое расширение необходимым и не принимает
непройденные требования как ограничения.

**Прогресс остаётся 26/29; 7.2–7.4 открыты.** В этой сессии дополнены только
журнал и новый diagnostic review, код/tasks не менялись. Проверены 6 уникальных
mode/case pairs, tuning-only scope, exact counts, единственный citation_missing
и совпадение summaries. Runtime tests не перезапускались; `git diff --check`
успешен.

### Вторая правка prompt: примеры формата и согласованность kind, 2026-10-22

После решения владельца продолжить локальную правку изменена только строка
`SYSTEM_RULES` в `app/app/grounding.py`. Основание — tuning failures и diagnostic
q01/q11/q19, общие требования SPEC §§13–15; holdout не использован для настройки.
Это новая проверяемая гипотеза, а не подтверждённое улучшение ответов Qwen.

Вместо длинной последовательности действий правила кратко описывают выбор
kind по полноте готового ответа. Если назван пробел в запрошенных сведениях,
kind должен быть partial; если всё запрошенное подтверждено, нельзя добавлять
общую оговорку о нехватке незапрошенных деталей. Широкий вопрос, соответствующий
предмету инструкции, не требует уточнения дополнительных параметров, которых
эта инструкция не требует. Неизвестный объект по-прежнему требует clarify,
а найденный похожий документ не разрешает угадать его.

Добавлены четыре вымышленных примера на одной учебной записи о сервисе
архивирования: полный answer, partial с конкретным пробелом, fenced-команда
с citation снаружи блока и короткий clarify. Это образцы сериализации JSON,
связи kind/answer и расположения citation; их факты и нулевой chunk ID
явно запрещено использовать как evidence текущего запроса. Примеры не берутся
из frozen corpus и не подставляют ответы контрольных cases.
Правила требуют citations у claims, точных команд в fences, различения
содержимого fragment и заголовков/примеров, согласованности готового JSON.

SHA256 UTF-8 `SYSTEM_RULES`:
`91b5078617b4ad7204f9d3f48b9bf3f208d3d627f7d9676d79992d3fa2c8057b`.
Длина — 4001 Unicode code points, только идентификация ревизии: это не token
count и не основание для budget. Точный budget использует прежний serving
tokenizer по полному массиву двух messages. Packing может измениться при
росте system rules; новые packed IDs/counts проверяются live, старые не переносятся.
Validator, parser, public API, transport, sampling, model/image/flags,
retrieval/ranking и frozen inputs не менялись. Retry/новых model calls нет.

### Локальные проверки второй правки

Из `app/`:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
../.venv/Scripts/python.exe -m pytest -q -rs -p no:cacheprovider --basetemp=../.tmp/grounded-prompt-examples-approved tests/test_grounding.py tests/test_chat_api.py tests/test_chat_evaluation.py tests/test_chat_token_check.py
$env:MYPYPATH='typings'
../.venv/Scripts/python.exe -m mypy app/grounding.py --follow-imports=silent --cache-dir ../.tmp/mypy-grounded-prompt-examples
```

**99 passed, 1 warning in 1.92s**, без skips. Warning — прежний TestClient/httpx.
Первый sandbox-прогон завершился temp WinError 5; результат выше — повтор вне
sandbox с отдельным basetemp. Mypy: **Success: no issues found in 1 source file**.
Новый тест разбирает учебный CONTEXT и все четыре фактических JSON-примера
из system string, пропускает их через действующие validators, проверяет
insufficiency/sources, точный fenced body и отклонение учебного ID на другом
manifest. Это проверка пригодности примеров, не поведения Qwen.
Полный regression не повторялся: изменена строка prompt и её тест.

`openspec.cmd validate grounded-chat-api --strict` — change valid;
`openspec.cmd validate --all --strict` — **11 passed, 0 failed**, прежние INFO
о длине requirements. `git diff --check` успешен. Diff проверен: новая правка
ограничена system string, тестом примеров, документацией и переоткрытием 7.1.
Начальные изменения diagnostic review/журнала сохранены; README/ROADMAP,
frozen inputs/splits, ranking, зависимости и исторические baseline не менялись.

### Серверная проверка второй правки

**7.1 снова открыта**, поскольку окончательные messages изменились;
предыдущий успешный 7.1 сохраняется как исторический результат прошлой ревизии.
Актуальный прогресс **25/29; открыты 7.1–7.4**. Ранний gate 2.1 принят.

Перенести обновлённый `app/app/grounding.py` в серверный checkout.
Runner монтирует текущий код read-only: для этих административных проверок
build/restart app не требуется. Не запускать другой chat/harness traffic.
При отсутствии outstanding uncertain generation выполнить из корня проекта:

```bash
bash docs/grounded-chat-api-final-token-smoke.sh
```

Передать полный вывод и принять exact counts/window/overflow/index checks.
При timeout остановиться без retry до подтверждения прекращения генерации;
не увеличивать timeout и не менять runtime автоматически.

После успешного review 7.1 выполнить tuning-only проверку новой гипотезы:

```bash
FROZEN_LIVE_INDEX=/data/acceptance/lexical-and-hybrid-retrieval/run-20261009T185137Z-YCmy22/hybrid-live.db \
FROZEN_SYNTHETIC_INDEX=/data/acceptance/lexical-and-hybrid-retrieval/run-20261009T185137Z-YCmy22/hybrid-synthetic.db \
bash docs/grounded-chat-api-evaluate.sh \
  --case q01 --case q02 --case q03 --case q05 --case q06 --case q07 \
  --case q11 --case q12 --case q13 --case q14 --case q15 --case q17 --case q19
```

Ожидается 13 rows каждого режима, generation-only q13/q14/q15/q17 без completion.
Требуется review всех запрошенных фактов, citations, kind, exact fenced commands,
clarify/refusal и возможной регрессии, включая validation_error. Передать оба
JSONL, оба stderr и identity sidecars нового каталога. Содержимое учебных
примеров и их ID не должны появляться в фактическом ответе/sources.
Только после tuning review переходить к полной 7.2, включая holdout исключительно
для acceptance; выборочный успех не закрывает change и не заменяет 7.3–7.4.
Локального Docker/целевой Qwen нет, live-команды этой ревизии агентом не выполнялись.
