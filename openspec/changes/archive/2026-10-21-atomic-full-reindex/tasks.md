# Tasks

## 1. Active path и metadata полного индекса

- [x] 1.1 Добавить типизированную конфигурацию `INDEX_PATH` с Compose default `/data/index.sqlite3`, одинаковую для app/indexer, передать её через `compose.yaml` и описать в `.env.example`; проверить целевыми config tests валидный/некорректный путь и независимость обычного startup от ingestion settings, проверить `docker compose config --quiet` без вывода secrets.
- [x] 1.2 Добавить writer/reader additive `reindex_metadata` (version, UTC indexed_at, document/chunk counts) и проверку counts по inventory без изменения base/semantic/lexical versions; проверить целевыми pytest round-trip, неправильные version/time/counts и чтение расширенного файла прежними readers.
- [x] 1.3 Создать `docs/atomic-full-reindex.md` с контрактом активного пути, metadata, требованиями к data mount/model assets и обработкой legacy файла без metadata; сверить примеры с настройками и metadata tests, не менять README.md/ROADMAP.md.

## 2. Полный pipeline и атомарная публикация

- [x] 2.1 Реализовать `app.indexer`: неблокирующая builder file lock, нормализация/защита output от model assets и aliases, уникальный staging рядом с active; проверить отказ конкурирующего subprocess, освобождение lock после завершения/kill, protected paths и отсутствие изменений active до публикации на Linux.
- [x] 2.2 Соединить `ingestion.ingest` → `chunking.load_snapshot/build_output` → `index_storage.parse_output/write_snapshot` → `semantic_storage.build` → `lexical_storage.build`, переиспользуя tokenizer одного LocalEncoder и текущие policies; проверить fixture pipeline с mock source/encoder и реальными SQLite/FTS, включая изменённую/удалённую страницу, пустой корпус и точный code/table/CRLF provenance.
- [x] 2.3 Добавить metadata кандидата, полную base/semantic/lexical/reindex validation одного поколения, проверяемую нормализацию собственного staging к checkpointed DELETE без WAL/SHM/journal, закрытие handles и единственный final replace; до сборки и непосредственно перед replace проверять journal format active и отсутствие sidecars без изменения старых файлов. Проверить повторное открытие новым процессом, точные IDs/counts/vectors/metadata и независимость от удалённого staging.
- [x] 2.4 Добавить fault-injection tests для connection/SELECT/неполного чтения/завершения transaction/невалидной строки, chunking, assets/inference, записи/нехватки места, corrupt candidate и final replace; проверить hash/timestamp старого active, его read/query после отказа, first-run failure без active и cleanup только своего staging.
- [x] 2.5 Проверить реальными SQLite fixtures отказ для active WAL с committed, ещё не checkpointed данными, clean WAL-format, WAL/SHM/journal sidecars (включая пустые/осиротевшие), их появление перед replace и busy candidate checkpoint; подтвердить неизменность main+sidecars при отказе, запрет ручного unlink/checkpoint active, успешную нормализацию только candidate и restart без WAL старого поколения.
- [x] 2.6 Добавить безопасный CLI report/диагностику с start/end, counts, UTC timestamp и длительностями embedding/indexing; проверить exit codes и отсутствие fixture secrets/DSN/Markdown/tracebacks в stdout/stderr, отдельно проверить результат после уже успешного replace при проблеме cleanup/report.
- [x] 2.7 Дополнить `docs/atomic-full-reindex.md` низкоуровневой командой `python -m app.indexer`, предусловиями остановленного app/отсутствия внешних владельцев, staging/commit point, пустым корпусом и отказом при active WAL/sidecars; описать отдельное восстановление через SQLite и согласованный backup без ручного удаления sidecars. Выполнить документированный CLI smoke на fixtures и сопоставить вывод с контрактом.

## 3. Загрузка индекса приложением после restart

- [x] 3.1 Добавить небольшой active index state loader с retained read-only handle, согласованными snapshot/matrix/ordered IDs/metadata и безопасным unavailable state; проверить valid/empty/missing/corrupt/incompatible/legacy файлы, запрет создания отсутствующей БД и загрузку без Wiki.js/model assets.
- [x] 3.2 Подключить loader к FastAPI lifespan с закрытием handles на shutdown; проверить lifecycle tests для запуска на A, публикации B при остановленном app и нового startup на B, а также restart на A после failed build; проверить текущий `/health` без индекса и отсутствие inference при startup.
- [x] 3.3 Описать в `docs/atomic-full-reindex.md` startup state, совместимость legacy snapshots и отличие unavailable от пустого корпуса; сверить с lifecycle tests и сохранить отсутствие новых HTTP endpoints/UI.

## 4. Административный Compose script

- [x] 4.1 Добавить исполняемый Linux `reindex.sh` с путями относительно script, проверкой prerequisites и host lifecycle flock до stop; проверить через fake docker в PATH порядок stop/run/up, отсутствие остановки llm/Wiki.js, работу из другого cwd и отказ второго запуска до действий с app.
- [x] 4.2 Реализовать восстановление app после результата индексатора, сохранение его exit code и отдельную ошибку restart, запрет сборки после stop failure; удерживая lifecycle lock, после up проверять в пределах 60 секунд running/current container ID/RestartCount и HTTP 200 с ожидаемым JSON через probe внутри app с timeout ≤2 секунд. Проверить delayed success, up=0 с exit/restarting/HTTP timeout/неверным JSON, смену ID во время probe, Docker error и одновременные build/recovery failures; failed build сохраняет свой exit code.
- [x] 4.3 Назначать уникальные имя/run-id label до создания one-shot, запускать detached без --rm, сохранять returned ID/exit code и удалять только после подтверждения завершения; при INT/TERM разрешать identity по точному имени+run-id+project после окончания launch-команды, stop с timeout 10 секунд, при необходимости kill и wait/inspect terminal state до release lock. Проверить Linux signal tests до/во время создания, при потере stdout ID, во время inference и после выхода контейнера, чужой container с похожим/совпавшим именем, Docker unavailable, graceful timeout/kill и отсутствие автоматического app restart при неподтверждённом завершении. Проверить, что завершение Docker CLI не принимается за terminal state контейнера, исходный status не маскируется; выполнить `bash -n reindex.sh`.
- [x] 4.4 Завершить runbook в `docs/atomic-full-reindex.md`: `./reindex.sh`, downtime, Linux Bash/flock, установка assets заранее, требуемое место, критерий running+HTTP восстановления и его deadline, identity своего one-shot и ручная проверка завершения перед recovery `docker compose up -d app`, ручное восстановление backup при остановленном app; проверить команды в script smoke и отдельно отметить ограничения process interruption/power loss.

## 5. Сквозная проверка и фактическая приёмка

- [x] 5.1 Сначала запустить целевые новые indexer/state/script tests и связанные существующие ingestion/chunking/storage/semantic/lexical/health/config tests, затем полный `python -m pytest` из `app/`, поскольку lifecycle и pipeline затрагивают несколько компонентов; выполнить принятый в проекте mypy check и зафиксировать результаты. Linux lock/signal tests выполнить на Linux, skips на Windows не считать проверкой.
- [x] 5.2 На целевом Linux-сервере с предустановленной E5 и настроенным read-only Wiki.js view выполнить `./reindex.sh`, проверить app restart, UTC time/counts, согласованные SQLite/embeddings/FTS/provenance и известные semantic/lexical/hybrid запросы новым процессом; сохранить фактические длительность и peak RAM в новом `docs/atomic-full-reindex-server-acceptance.md`, без изменения исторических отчётов и без требования Hit@5 ≥90%.
- [x] 5.3 На изолированном data path и контролируемом read-only test source проверить обновление/исчезновение страницы и пустой корпус, ошибку полного reindex с неизменными hash/timestamp A и работоспособным retrieval после restart, отказ при active WAL/SHM без изменения файлов, first-run failure, второй запуск и прерывание до/после commit point с подтверждённым завершением собственного one-shot и manual recovery; отдельно подтвердить running+HTTP после up и ошибку восстановления при up=0 с неработающим app. Записать фактические результаты в тот же acceptance report без изменений production Wiki.js. Если среда недоступна, оставить эти проверки незавершёнными.
- [x] 5.4 Выполнить `openspec validate --all --strict`, проверить Git diff на scope и отсутствие secrets/изменений README.md/ROADMAP.md; сверить tasks с реально выполненными проверками и оставить невыполненные пункты открытыми.


## Проверки реализации 2026-10-20

Локально выполнены переносимые pipeline/storage/state проверки и полный pytest:
797 passed, 31 skipped; mypy — без ошибок (24 source files); `bash -n reindex.sh` —
exit 0 через Git Bash; `openspec validate --all --strict` — 10 passed, 0 failed.
После финального уточнения safe CLI categories/cleanup повторены целевые tests:
62 passed, 1 Linux-only skipped. Подробности — `docs/atomic-full-reindex-server-acceptance.md`.

### Сверка с серверной приёмкой 2026-10-20

Сохранённые результаты Linux-сессии: целевые `tests/test_indexer.py`
и `tests/test_reindex_script.py` — **70 passed in 23.92s**; затем полный
`python -m pytest -q -rs -p no:cacheprovider` — **829 passed, 4 skipped,
1 warning in 44.10s**. mypy — success, 24 source files;
`docker compose config --quiet` — успешно. Команда целевого прогона и live-результаты
записаны в [acceptance report](../../../docs/atomic-full-reindex-server-acceptance.md).
При этой сверке испытания повторно не запускались.

Все четыре skips — `tests/test_reranking.py`, строки 89, 102, 112, 134:
`pinned local tokenizer unavailable`. Исходники подтверждают общий fixture
`real_tokenizer_scorer`, ожидающий pinned assets
`data/models/1427fd652930e4ba29e8149678df786c240d8825`, для тестов:

- `test_real_pair_budgets_no_padding_or_truncation`;
- `test_real_exact_512_boundary`;
- `test_batch_one_full_input_order_finite_raw_logit`;
- `test_preflight_overflow_prevents_all_model_calls`.

Это проверки ранее отклонённого reranker, не atomic-full-reindex.
Linux flock/Bash/signal tests не пропущены. Fixture-покрытие ниже засчитывается
только там, где задача требует автоматические tests/smoke; live-критерии
5.2–5.3 этим не закрываются.

| Задача | Подтверждение и оставшиеся проверки |
| --- | --- |
| 1.1 — выполнена | `test_config.py`: valid/invalid path и независимость от ingestion settings; тип `Path`, единый `load_index_path` для app/indexer, Compose default и `.env.example` сверены с кодом; Compose config успешно проверен. |
| 2.1 — выполнена | Linux `test_lock_subprocess_exit_and_kill`: конкурентный subprocess и повторный захват после TERM/KILL; `test_protected_paths`: model asset и hardlink alias; pipeline/failure tests: staging рядом с active, сохранение hash/mtime до replace. Нормализация/защита aliases сверены с `protect_output`. Linux-прогон 70 passed и live builder lock/failure preservation подтверждены. Дополнительная live-конкуренция полного pipeline не является отдельным критерием 2.1. |
| 4.1 — выполнена | Git mode `100755`, prerequisites и пути сверены со script; Linux fake-Docker tests подтверждают stop/run/up только app, другой cwd и отказ второго host запуска до Docker. Live production `./reindex.sh` завершился с 0. |
| 4.2 — выполнена | Код recovery проверяет deadline 60 секунд, request timeout 2 секунды, running/ID/RestartCount и HTTP 200 с ожидаемым JSON под lifecycle lock. Linux fake-Docker cases success/build-failure/both-failure/up-failure/stop-failure/app-exit/app-restarting/http-timeout/bad-json/probe-delay/changed-id подтверждают статусы и порядок; Docker error моделируется в failure cases. Production running+HTTP подтверждены live. Live failed recovery при `up=0` остаётся в 5.3, а не дополнительным условием закрытия 4.2. |
| 4.3 — выполнена | Весь Linux script suite: 42 passed, 0 skipped, включая 14 новых INT/TERM cases до создания, при lost stdout ID, после выхода, с чужими identity и ожиданием terminal state под lock. Код и tests согласованы с критерием; Bash syntax check успешен. Это fake-Docker подтверждение, live administrative lifecycle остаётся в 5.3. |
| 4.4 — выполнена | Runbook содержит все перечисленные предусловия, downtime, assets/место, recovery deadline/running+HTTP, identity/manual recovery, backup при остановленных владельцах и ограничения interruption/power loss. Команды script проверены Linux fake-Docker smoke и успешным production запуском. Задача требует документирования manual/backup recovery, не отдельного live restore drill; live manual recovery остаётся в 5.3. |
| 5.1 — выполнена | Ранее выполнены целевые state/config и связанные regression tests, затем полный локальный pytest; Linux indexer/script 70 passed закрывает platform-specific skips, полный Linux pytest 829 passed подтверждает regression; mypy успешен. Все четыре Linux skips идентифицированы и не относятся к этому change. |

5.2 закрыта после дополнительных подтверждений согласованности/retrieval и
изолированного измерения полной индексации (см. актуализацию ниже).
На момент этой сверки 5.3 оставалась открытой: требовались live host lock, прерывания административного скрипта
до/после commit с terminal state/manual recovery, FastAPI restart и running+HTTP
после failed build, failed recovery при `up=0`, unavailable+health после first-run
failure. Уже подтверждённые source update/delete/empty и сохранность/retrieval
старого active повторять не требуется.
Windows skips не засчитаны как проверка. Реализация, README.md, ROADMAP.md и
SPEC.md при сверке не изменены; change не архивирован.

### История продолжения 4.3: signal/identity tests, 2026-10-20

В `app/tests/test_reindex_script.py` добавлены 12 cases
`test_signal_at_identity_boundaries` и 2 cases
`test_signal_holds_lock_until_container_terminal`. Существующее покрытие
сохранено; `reindex.sh` не изменён. Windows целевой pytest: **4 passed,
38 skipped**, включая **14 новых skipped**. Linux tests этим не подтверждены.
`bash -n reindex.sh` через Git Bash — exit 0;
`openspec.cmd validate --all --strict` — **10 passed, 0 failed**;
`git diff --check` — exit 0. Полный pytest повторно не запускался.

На момент этой сессии локальный Linux runtime отсутствовал; 4.3, 5.2 и 5.3
оставались открытыми. Этот исторический результат дополнен ниже.

### Актуализация по результатам оператора, 2026-10-21

- **4.3 закрыта**: Linux `tests/test_reindex_script.py` — **42 passed, 0 skipped**,
  включая все 14 новых signal/identity cases. Повторный запуск не требовался;
  ранее выполненный `bash -n` успешен. Исходники script/tests сверены.
- **5.2 закрыта**: production `./reindex.sh` exit 0, app running+HTTP 200,
  UTC/counts 24/910; изолированный полный reindex с реальным source — 25/919.
  Embeddings (384) и FTS5 согласованы с chunks, integrity `ok`; provenance
  1210/1223 сегмента без ошибок, semantic/lexical/hybrid retrieval новым процессом.
  Отдельное изолированное измерение: wall **20,92 с**, indexing **20,75335 с**,
  embeddings **19,20777 с**, peak RSS процесса через `resource.getrusage`
  **1390,16 MiB**. Это не RAM/downtime production `./reindex.sh`; задача не
  требует одного общего production-прогона для всех измерений.
- **5.3, первоначальная сверка**: контролируемый PostgreSQL и изолированный SQLite подтвердили
  empty/add/update/delete, failure exit 1, неизменные SHA-256/mtime/metadata и
  lexical retrieval старого поколения новым Python-процессом (`900001`, без `900002`).
  Ранее подтверждены first-run без active, WAL/SHM без изменения файлов,
  builder lock, прерывание индексатора до публикации и следующий успешный reindex.
  Это не подтверждает restart FastAPI и live административные recovery/signals.
  Последующие подтверждения и итоговая сверка приведены в
  [acceptance report](../../../docs/atomic-full-reindex-server-acceptance.md).

### Закрытие 5.3 по дополнительным результатам оператора, 2026-10-21

First-run failure: exit 1, active отсутствует, FastAPI автоматически восстановлен,
HTTP 200 и health `{"status":"ok"}`. Failed build: exit 1, SHA-256/MTIME A
неизменны, integrity `ok`, FastAPI восстановлен и удерживает SQLite handle;
отдельный диагностический lifespan загрузил A, lexical retrieval вернул 1 результат.
Второй host запуск получил `operation busy`/exit 1, первый — exit 0 с recovery.
SIGTERM до/после `os.replace` подтверждены `PRE_COMMIT_REACHED=1` и
`POST_COMMIT_REACHED=1`: exit 143, собственный one-shot завершён и удалён,
manual recovery успешен. До commit сохранено A; после опубликовано целостное B
(1 документ / 1 chunk), HTTP 200 и handle нового поколения подтверждены.
При `up=0` с сразу завершающимся app скрипт сообщил `app recovery failed`
и вернул exit 1. Cleanup подтверждён `TEST_CLEANUP_PASSED`.

Внутренний `app.state.index.available` после first-run failure в работающем
процессе не считывался. `index_missing` подтверждают исходники loader/lifespan
и ранее выполненные lifecycle tests; live подтверждены отсутствие файла,
restart и health. Буквальный критерий 5.3 не требует прямого live-чтения state.
Виды доказательств разделены в acceptance report. Вместе с ранее подтверждёнными
сценариями это закрывает 5.3; неподтверждённых обязательных критериев не осталось.

Итого **21/21 tasks**. Изменены только tasks и acceptance report; требования,
design, runbook и реализация не менялись. Серверные испытания не повторялись,
production app/Wiki.js/SQLite не затрагивались; change не архивирован.
