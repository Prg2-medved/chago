# Atomic full reindex: журнал проверки

Дата приёмки: **2026-10-20**. Серверная приёмка выполнена частично: production
maintenance cycle и часть изолированных live-сценариев подтверждены. Полная
приёмка пока не завершена, в частности **peak RAM полного reindex не измерен**.

Серверные результаты приведены по подтверждённым данным оператора. При обновлении
отчёта испытания повторно не запускались: выполнена сверка с
[OpenSpec tasks](../openspec/changes/atomic-full-reindex/tasks.md),
[delta spec](../openspec/changes/atomic-full-reindex/specs/atomic-full-reindex/spec.md),
[design](../openspec/changes/atomic-full-reindex/design.md),
[runbook](atomic-full-reindex.md) и исходниками существующих тестов.
При последующей сверке `tasks.md` актуализирован по сохранённому Linux-выводу
и исходникам tests. Завершение автоматических проверок отделено от live-приёмки.

## Завершённые серверные проверки

### Linux regression и конфигурация

- Полный Linux pytest: **829 passed, 4 skipped**.
- Целевые Linux indexer/script tests: **70 passed in 23.92s**.
- mypy: **success, 24 source files**.
- `docker compose config --quiet`: успешно.

Сохранённая команда целевого Linux-прогона:

```bash
docker compose run --rm --no-deps -v "$PWD:/workspace:ro" -v "$PWD/data:/data:ro" -w /workspace/app app sh -c 'python -m pip install --no-cache-dir pytest==9.1.1 httpx==0.28.1 && python -m pytest -q -rs -p no:cacheprovider tests/test_indexer.py tests/test_reindex_script.py'
```

Затем полный Linux `python -m pytest -q -rs -p no:cacheprovider`:
**829 passed, 4 skipped, 1 warning in 44.10s**. Причина warning в переданном
выводе не детализирована. Сохранённые строки skips:

```text
SKIPPED [1] tests/test_reranking.py:89: pinned local tokenizer unavailable
SKIPPED [1] tests/test_reranking.py:102: pinned local tokenizer unavailable
SKIPPED [1] tests/test_reranking.py:112: pinned local tokenizer unavailable
SKIPPED [1] tests/test_reranking.py:134: pinned local tokenizer unavailable
```

Исходники подтверждают: четыре теста используют fixture `real_tokenizer_scorer`,
ожидающий `data/models/1427fd652930e4ba29e8149678df786c240d8825`. Это проверки
ранее отклонённого reranker, не atomic-full-reindex. Linux lock/signal tests
выполнены, не пропущены. Skips не считаются выполненными проверками.
Linux pytest и live-проверки ниже — разные виды подтверждений: запуск
fixture-теста на сервере не превращает его в live-сценарий.

### Production: публикация и восстановление app

- `./reindex.sh`: **exit 0**, app восстановлен, подтверждены **running и HTTP health**.
- Production SQLite: **integrity ok**, **24 документа**, **910 chunks**,
  `indexed_at=2026-10-20T10:18:41.693304+00:00`.
- Semantic, lexical и hybrid retrieval успешно проверены с настоящим индексом.

Это подтверждает успешный административный цикл и реальные retrieval-проверки.
Health сам по себе не доказывает согласованность содержимого индекса. Отдельный
протокол проверки SQLite/embeddings/FTS/provenance и запуска retrieval именно
новым процессом в переданных результатах не детализирован; эти части 5.2 нельзя
объявлять отдельно завершёнными лишь по integrity/health.

### Изолированный data path: отказы и повторная индексация

Подтверждены **failure preservation, first-run failure, WAL/SHM refusal,
builder lock, SIGTERM во время сборки, сохранение SHA-256** и последующая
успешная повторная индексация.

| Показатель повторной индексации | Значение |
| --- | --- |
| Документы | 25 |
| Chunks | 919 |
| `indexed_at` | `2026-10-20T11:30:28.266303+00:00` |
| `indexing_seconds` | 19.2775 |
| `embedding_seconds` | 17.8763 |

Добавлена страница Wiki.js **`page_id=48`**; остальные 24 документа по
`content_sha256` не изменились. Это подтверждает добавление документа, но не
live-проверку изменения Markdown существующей страницы или её исчезновения
из view. **Production SQLite остался на прежнем поколении** — 24 документа,
910 chunks, timestamp `2026-10-20T10:18:41.693304+00:00`.
Изолированное поколение 25/919 не опубликовано в production SQLite.

Прежнее утверждение отчёта «Production Wiki.js не изменялся» больше не
используется: зафиксировано добавление `page_id=48`. Для оставшихся
update/delete/empty сценариев требуется контролируемый read-only test source,
без дополнительных изменений production Wiki.js ради испытаний.

Длительности относятся к повторной изолированной индексации, а не к production
downtime или полному времени `./reindex.sh`. Peak RAM не измерен.
Сохранение SHA-256 не заменяет отдельного подтверждения прежних timestamp,
сохранности sidecars и retrieval после restart. SIGTERM во время сборки не
подтверждает весь протокол завершения собственного one-shot/manual recovery
или прерывание после commit point.

## Покрытие на fixtures

Сверка существующих тестов показывает следующий объём автоматического покрытия:

- `app/tests/test_config.py`: допустимый/некорректный `INDEX_PATH`, независимость
  обычной конфигурации от некорректного ingestion setting.
- `app/tests/test_indexer.py`: **mock source/encoder**, реальные SQLite/FTS;
  builder lock в `pipeline` fixture подменён. Проверяются update/delete/empty,
  точный Markdown/provenance, reopen отдельным процессом, fault injection до
  replace, hash/mtime и hybrid query после отказа, first-run failure, corrupt
  candidate, protected output, WAL/sidecars и busy checkpoint candidate,
  report/cleanup после успешного commit. Отдельный Linux
  `test_lock_subprocess_exit_and_kill` использует настоящий `flock` и subprocess:
  отказ конкуренту, повторный захват после TERM/KILL. Это реальная проверка OS
  lock, но не полный live reindex с E5/Wiki.js.
- `app/tests/test_index_state.py`: FastAPI TestClient lifecycle A→B и возврат
  к сохранённому поколению после ошибки, unavailable для
  missing/corrupt/incompatible/legacy, health без индекса, чтение без model
  libraries и обращения к источнику. Индексы создаются fixture pipeline.
- `app/tests/test_reindex_script.py`: **fake Docker в PATH**, настоящий Linux
  Bash/flock/signals. Проверяются порядок stop/run/up из другого cwd, второй
  host запуск, failed build/stop/up и одновременные ошибки, delayed recovery,
  app exit/restarting, HTTP timeout/bad JSON, смена ID, foreign identity/lost ID/
  launch failure, INT/TERM во время launch/inference, kill fallback,
  недоступный Docker и `bash -n`. Docker state и HTTP здесь моделируются;
  failure fixtures сокращают recovery deadline с 60 до 5 секунд.

Эти fixtures не заменяют live Docker/HTTP/Wiki.js/E5 приёмку. В указанных tests
нет отдельного signal-сценария, прицельно прерывающего настоящий reindex после
commit point. `test_report_failure_after_commit` проверяет ошибку отчёта после
публикации, а не такое прерывание.

### История локальной проверки

Предыдущая локальная проверка 2026-10-20: Windows, Python 3.12, существующее `.venv`.
Связанный regression-прогон — 342 passed, 28 skipped; дополнительные metadata
reader/query checks — 62 passed, 24 skipped; полный pytest — 797 passed, 31 skipped.
После уточнения safe CLI categories/cleanup целевой прогон — 62 passed,
1 Linux-only skipped (зафиксирован в OpenSpec tasks). mypy — без ошибок,
24 source files; `bash -n reindex.sh` через Git Bash — exit 0.
Windows skips не засчитывались как Linux-проверки. Эти исторические результаты
не заменяют и не суммируются с серверным прогоном.

## Оставшиеся критерии OpenSpec

Таблица согласована с актуализированным `tasks.md`. Неуказанные детали
считаются неподтверждёнными, а не неуспешными. Для 1.1–4.4 учитываются
предусмотренные задачами автоматические tests/smoke; отдельные live-критерии
остаются в 5.2–5.3.

| Задача | Что ещё требуется |
| --- | --- |
| 1.1 — выполнена | Config tests, типизированный общий `INDEX_PATH`, Compose/`.env.example` и успешный Compose config подтверждены. |
| 2.1 — выполнена | Linux subprocess lock/TERM/KILL, protected paths, staging и сохранность active до replace подтверждены кодом и tests; live builder lock/failure preservation дополняют их. Отдельной live-конкуренции полного pipeline задача не требует. |
| 4.1 — выполнена | Executable bit, prerequisites/пути, Linux fake-Docker порядок/другой cwd/второй host запуск подтверждены. Второй live host запуск остаётся в 5.3. |
| 4.2 — выполнена | Recovery deadline/probe/ID/RestartCount сверены с кодом, Linux fake-Docker матрица статусов выполнена; production running+HTTP подтверждены. Live failed recovery при `up=0` и running+HTTP после failed build остаются в 5.3. |
| 4.3 — открыта | Недостающие signal/identity tests добавлены: 14 cases для INT/TERM, включая до создания, потерю stdout ID, уже завершившийся контейнер, чужие identity и ожидание terminal state под lock. Их Linux-прогон ещё не выполнен: Windows skips не подтверждают критерии. Подробности и одна команда сервера приведены ниже. Детали live identity/terminal state/manual recovery и прерывания вокруг commit остаются в 5.3. |
| 4.4 — выполнена | Runbook содержит все требуемые инструкции и ограничения, script smoke выполнен. Отдельный live restore drill не является критерием этой задачи; live manual recovery остаётся в 5.3. |
| 5.1 — выполнена | Целевые/связанные и полный локальный regression, Linux indexer/script 70 passed, полный Linux 829 passed и mypy подтверждены. Все 4 skips идентифицированы: reranker; Linux lock/signal tests не пропущены. |
| 5.2 | Измерить peak RAM полного reindex; отдельно подтвердить согласованность SQLite/embeddings/FTS/provenance и retrieval новым процессом. Длительности изолированного повторного reindex записаны; production duration/downtime не предоставлены. |
| 5.3 | Live на контролируемом source: изменение существующей страницы, исчезновение страницы и пустой корпус; прежние timestamp и retrieval после failed rebuild/restart; неизменность main+sidecars при WAL/SHM отказе; unavailable и health после first-run failure; второй host запуск до действий с app; прерывания до/после commit с подтверждённым завершением one-shot и manual recovery; failed recovery при `up=0`. Частичные подтверждения SHA-256, first-run failure, WAL/SHM, builder lock и SIGTERM уже получены: где достаточно уточнить протокол, повторять испытания не нужно. |

Обязательные live-сценарии 5.2–5.3 остаются незавершёнными в указанном объёме.
Fixtures update/delete/empty и fake-Docker recovery/signals их не закрывают.
Hit@5 ≥90% не является gate этого этапа; строгая durability при power loss
не входит в заявленную гарантию. Change не архивирован; реализация, `SPEC.md`,
`ROADMAP.md` и `README.md` при сверке не изменялись.

## Дополнение 4.3: недостающее signal/identity покрытие, 2026-10-20

Сначала сверены утверждённые artifacts и существующие tests. Уже имеющиеся
creation-delay/inference, lost-id без сигнала, foreign label без сигнала,
Docker unavailable и kill fallback сохранены. В `app/tests/test_reindex_script.py`
добавлены только недостающие сочетания и проверки протокола завершения:

| Новый test / scenario | Критерий |
| --- | --- |
| `test_signal_at_identity_boundaries`: `before-creation` × INT/TERM | Сигнал во время stop app до launch: one-shot не создаётся, stop/kill/rm контейнера и автоматический recovery не выполняются; статус 130/143. |
| `lost-id-signal` × INT/TERM | Launch создаёт running one-shot, но не возвращает stdout ID и завершается ошибкой. После окончания launch скрипт разрешает свою identity, делает stop с `--time 10`, подтверждает terminal state и удаляет только свой ID; статус сигнала сохраняется. |
| `after-exit` × INT/TERM | Launch уже вернул ID, контейнер exited с code 0. Сигнал приходит при чтении terminal state: только rm собственного контейнера, без stop/kill/recovery, итог 130/143. Это fake-Docker lifecycle test, не прерывание настоящего indexer после commit point. |
| `foreign-signal`, `foreign-project` × INT/TERM | Совпавшее имя с чужим run-id либо project: неизменные байты состояния чужого контейнера, отсутствие stop/kill/rm/recovery, manual diagnostic, сохранение 130/143. |
| `foreign-similar` × INT/TERM | Чужой контейнер с похожим именем и совпадающими labels не выбирается точным lookup/filter; его состояние не меняется, recovery не выполняется, итог 130/143. |
| `test_signal_holds_lock_until_container_terminal` × INT/TERM | Stop и kill CLI возвращают 0, но inspect ещё показывает running: контейнер не удаляется, app не запускается, второй host запуск отклоняется до Docker. Только после terminal state допустим rm и release lock; code 137 контейнера не маскирует 130/143 сигнала. |

Новые cases синхронизируются через marker/release, без выбора момента сигнала
по sleep. Проверяется detached launch без `--rm`, связь имени с run-id label,
точный ID для mutations и доступность lifecycle lock после завершения скрипта.
Fake `container ls` учитывает точный name filter, чтобы похожее имя не считалось
совпавшим. Production `reindex.sh` не изменён: подтверждённого тестами дефекта
пока не выявлено; новые signal cases ещё требуют выполнения на Linux.

Фактически выполнено в этой сессии:

- Целевой Windows pytest всего `app/tests/test_reindex_script.py`:
  **4 passed, 38 skipped**. Новые tests: **14 skipped** (12 identity + 2 terminal/lock),
  **0 выполненных Linux cases**. Четыре passed — существующие переносимые
  проверки fake Docker; они проверяют также работоспособность изменённого fake.
- Первый sandbox-прогон остановился на 4 setup errors из-за доступа к Windows
  temp; повтор вне sandbox дал результат выше. Это ошибка среды, не reindex.
- `bash -n reindex.sh` через Git Bash вне sandbox: **exit 0** (первый запуск
  внутри sandbox блокировался CreateFileMapping). Это проверка синтаксиса,
  не Linux signal/flock.
- `openspec.cmd validate --all --strict`: **10 passed, 0 failed**.
- `git diff --check`: **exit 0**. Полный pytest и mypy повторно не запускались:
  Python application code не изменён, прежний полный Linux regression сохранён выше.
- Docker локально отсутствует; `wsl --list --quiet` вне sandbox вернул пустой
  список. Доступного локального Linux runtime для обязательных tests нет.

Для подтверждения 4.3 выполнить **одну команду из корня обновлённого checkout
на Linux-сервере**, используя уже применявшийся acceptance container:

```bash
docker compose run --rm --no-deps -v "$PWD:/workspace:ro" -v "$PWD/data:/data:ro" -w /workspace/app app sh -c 'bash -n /workspace/reindex.sh && python -m pip install --no-cache-dir pytest==9.1.1 && python -m pytest -q -rs -p no:cacheprovider tests/test_reindex_script.py'
```

Команда выполняет script tests с fake Docker в PATH и временными fixtures;
реальный `reindex.sh` против production Docker не запускается. Требуется
успешный прогон всех script cases без Linux skips. Его вывод следует сохранить
в этом отчёте; только после подтверждения всех критериев можно закрыть 4.3.
**4.3, 5.2 и 5.3 остаются открытыми**, change не архивирован.
