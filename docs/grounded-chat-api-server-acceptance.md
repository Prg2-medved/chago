# Grounded chat API: журнал проверки

Дата: 2026-10-21. Среда реализации: локальный Windows workspace.
Linux-проверка 1.3 и live-gate 2.1 подтверждены выводом оператора.
`POST /api/chat` ещё не реализован.

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

В tasks отмечены **1.1–1.4, 2.1**: **5/29**. Проверки 6.3 и 7.4 не отмечены
выполненными: chat ещё не реализован и полный объём этих задач не проверен.

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
задача 7.1 не заменяют gate 2.1. LLM client/token counter ещё не реализованы.
Финальные live-проверки 7.1–7.3 остаются открытыми.

## Задача 2.2: локальная реализация, ожидается Compose config

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

Docker CLI локально отсутствует. **2.2 не отмечена выполненной** до проверки
развёрнутой Compose configuration. На сервере с актуальным `compose.yaml`
из корня проекта выполнить одну команду (без up/build/restart):

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
индекс не читается и не меняется. Требуется полный вывод этой команды; пока
прогресс **5/29**, остановка на оставшейся проверке 2.2.
