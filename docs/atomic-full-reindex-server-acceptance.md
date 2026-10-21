# Atomic full reindex: журнал проверки

Дата исходной приёмки: **2026-10-20**; актуализация по данным оператора —
**2026-10-21**. Задачи **4.3, 5.2 и 5.3 выполнены**, итого **21/21**.
Production maintenance cycle,
изолированная полная индексация с измерением peak RSS и контролируемые
source/failure проверки подтверждены раздельно.

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
- После добавления 14 signal/identity cases весь `tests/test_reindex_script.py`
  выполнен на Linux: **42 passed, 0 skipped**. Это отдельный целевой прогон,
  а не новый полный regression; результаты не суммируются с 829/70.
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

- `./reindex.sh`: **exit 0**, app восстановлен, подтверждены **running и HTTP 200**.
- Production SQLite: **integrity ok**, **24 документа**, **910 chunks**,
  `indexed_at=2026-10-20T10:18:41.693304+00:00`.
- Semantic, lexical и hybrid retrieval успешно проверены **новым процессом**
  с настоящим индексом, независимо от процесса сборки.

Это подтверждает успешный административный цикл и реальные retrieval-проверки.
Health сам по себе не доказывает согласованность содержимого индекса. По
дополнительно переданным результатам embeddings и FTS5 согласованы с chunks,
размерность embeddings — **384**. Проверены **1210 provenance-сегментов**
рабочего индекса и **1223** изолированного, **ошибок 0**; SQLite integrity — `ok`.

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
`content_sha256` не изменились. Это подтверждает добавление документа; отдельные
update/delete/empty результаты на контролируемом source приведены ниже.
**Production SQLite остался на прежнем поколении** — 24 документа,
910 chunks, timestamp `2026-10-20T10:18:41.693304+00:00`.
Изолированное поколение 25/919 не опубликовано в production SQLite.

Добавление `page_id=48` зафиксировано отдельно от контролируемых испытаний ниже.
Контролируемые update/delete/empty испытания выполнены без изменения production Wiki.js.

Длительности 19.2775/17.8763 относятся к прежней повторной изолированной
индексации. Отдельное измерение полного reindex с реальным Wiki.js source:

| Показатель отдельного измерения | Значение |
| --- | --- |
| Документы / chunks | 25 / 919 |
| Wall time | 20,92 с |
| `indexing_seconds` | 20,75335 с |
| `embedding_seconds` | 19,20777 с |
| Peak RSS процесса через `resource.getrusage` | 1390,16 MiB |

Это peak RSS процесса полной индексации, не суммарная память Docker/host и не
измерение production `./reindex.sh`. Production duration/downtime не предоставлены.
Буквальный критерий 5.2 требует фактических длительности и peak RAM полного reindex,
но не требует измерять их в том же production maintenance cycle; поэтому
раздельных подтверждений достаточно для закрытия 5.2. SIGTERM индексатора до
публикации не подтверждает host-script termination/manual recovery либо
прерывание после commit point.

### Контролируемый source: update/delete/empty и failed build

Изолированный SQLite и тестовый PostgreSQL `chago-rag-acceptance-pg`;
production Wiki.js не изменялся в рамках этих испытаний.

| Live-проверка | Подтверждённый результат |
| --- | --- |
| Пустой source | Успешная публикация: 0 документов, 0 chunks. |
| Добавление двух страниц | 0 → 2 документа. |
| Обновление Markdown `900001` | Новые данные проиндексированы, прежнее содержимое заменено. |
| Удаление `900002` | 2 → 1 документ; integrity `ok`, documents/chunks/embeddings/FTS5 согласованы и относятся к одному оставшемуся поколению. |
| Ошибка PostgreSQL ingestion | `reindex: build_failed`, exit 1; SHA-256, mtime и metadata старого active неизменны. |
| Чтение после failed build | Новый Python-процесс открыл прежнее поколение, lexical retrieval нашёл только `900001`, удалённая страница отсутствует. |

Последний подтверждённый вывод оператора:

```text
PREVIOUS_GENERATION_LOADED: True
RETRIEVAL_EXIT: 0
RESULT_COUNT: 1
PAGE_IDS: [900001]
RETRIEVAL_AFTER_FAILURE: PASSED
RETRIEVAL_CHECK_EXIT=0
```

Ранее также подтверждены first-run failure без active, WAL/SHM refusal **без
изменения файлов**, конкурентный builder lock, прерывание индексатора до
публикации и последующий успешный reindex. Эти испытания повторять не нужно.
Новый Python reader сам по себе не подтверждает restart FastAPI. Дополнительные
live Docker и диагностические подтверждения приведены отдельно ниже.

### Дополнительные live Docker испытания 5.3, 2026-10-21

По данным оператора испытания выполнены на изолированной тестовой среде,
с отдельными data path и контролируемым read-only source. Production Wiki.js
не изменялся. Ранее подтверждённые update/delete/empty, WAL/SHM, failure
preservation и retrieval не повторялись при этой актуализации.

| Live Docker сценарий | Фактический результат |
| --- | --- |
| First-run failure | `reindex.sh` вернул exit 1, активный SQLite отсутствует. Тестовый FastAPI автоматически восстановился; HTTP 200, health `{"status":"ok"}`. |
| Failed build с поколением A | Exit 1; SHA-256 и MTIME A не изменились, SQLite integrity `ok`. FastAPI восстановился; работающий процесс удерживает SQLite handle. Проверки загрузки A и retrieval диагностическим lifespan описаны ниже. |
| Host lifecycle lock | Второй `reindex.sh` вернул exit 1 и `reindex: operation busy`; первый завершился с exit 0 и восстановил FastAPI. Это дополняет ранее проверенный отдельный builder lock. |
| SIGTERM до commit | Hook непосредственно перед `os.replace`: `PRE_COMMIT_REACHED=1`. Exit 143; собственный one-shot завершён и удалён, автоматического восстановления не было. SHA-256 и MTIME старого поколения неизменны, integrity `ok`; manual recovery успешен. |
| SIGTERM после commit | Hook подтвердил выполнение `os.replace` до сигнала: `POST_COMMIT_REACHED=1`. Exit 143; собственный one-shot завершён и удалён. Опубликовано целостное B: SHA-256, MTIME и indexed_at изменились, integrity `ok`, 1 документ / 1 chunk. Manual recovery успешен, HTTP 200; работающий FastAPI удерживает SQLite handle нового поколения. |
| Негативный recovery | Тестовый Compose принял запуск (`up=0`), но приложение сразу завершилось с exit 0. Скрипт сообщил `app recovery failed` и вернул exit 1; собственных one-shot контейнеров не осталось. |
| Cleanup | Временная инструментализация удалена, штатный Compose восстановлен, FastAPI работает, HTTP health успешен: `TEST_CLEANUP_PASSED`. |

### Диагностические проверки и границы live-наблюдения

После failed build отдельный диагностический lifespan загрузил поколение A,
lexical retrieval вернул **1 результат**. Это проверка загрузки через lifespan
и retrieval отдельно от работающего FastAPI. У работающего процесса подтверждён
удерживаемый SQLite handle; выполнение retrieval внутри этого процесса не заявляется.

После first-run failure непосредственно наблюдались отсутствие активного файла,
автоматический restart FastAPI и успешный HTTP health. Значение
`app.state.index.available` в работающем процессе **не считывалось**.
Health не доказывает unavailable state. Вывод об `index_missing` опирается на
`load_index_state()` в `app/app/index_state.py`, вызов loader в lifespan
`app/app/main.py` и ранее выполненный `test_unavailable[missing]` из
`app/tests/test_index_state.py`: отсутствующая БД не создаётся, state unavailable,
health успешен. Это подтверждение исходниками и автоматическими lifecycle tests,
а не прямое live-наблюдение внутреннего state.

Таким образом, first-run failure из буквального текста 5.3 проверен live;
требование delta spec/design об unavailable state подтверждено совокупностью
live-фактов, исходников и ранее выполненных tests. Прямое считывание внутреннего
state работающего процесса отдельным обязательным live-критерием 5.3 не задано.

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

## Итоговая сверка критериев OpenSpec

Таблица согласована с актуализированным `tasks.md`. Неуказанные детали
считаются неподтверждёнными, а не неуспешными. Для 1.1–4.4 учитываются
предусмотренные задачами автоматические tests/smoke; отдельные live-критерии
5.2–5.3 сверены с серверными результатами.

| Задача | Подтверждение |
| --- | --- |
| 1.1 — выполнена | Config tests, типизированный общий `INDEX_PATH`, Compose/`.env.example` и успешный Compose config подтверждены. |
| 2.1 — выполнена | Linux subprocess lock/TERM/KILL, protected paths, staging и сохранность active до replace подтверждены кодом и tests; live builder lock/failure preservation дополняют их. Отдельной live-конкуренции полного pipeline задача не требует. |
| 4.1 — выполнена | Executable bit, prerequisites/пути, Linux fake-Docker порядок/другой cwd/второй host запуск подтверждены. Второй live host запуск подтверждён дополнением 5.3. |
| 4.2 — выполнена | Recovery deadline/probe/ID/RestartCount сверены с кодом, Linux fake-Docker матрица статусов выполнена; production running+HTTP подтверждены. Live failed recovery при `up=0` и восстановление после failed build подтверждены дополнением 5.3. |
| 4.3 — выполнена | Весь Linux script suite: 42 passed, 0 skipped, включая 14 новых signal/identity cases. Исходники tests и script согласованы с критериями; `bash -n` успешен. Live завершение собственного one-shot/manual recovery и прерывания вокруг commit подтверждены дополнением 5.3. |
| 4.4 — выполнена | Runbook содержит все требуемые инструкции и ограничения, script smoke выполнен. Отдельный live restore drill не является критерием этой задачи; live manual recovery подтверждён дополнением 5.3. |
| 5.1 — выполнена | Целевые/связанные и полный локальный regression, Linux indexer/script 70 passed, полный Linux 829 passed и mypy подтверждены. Все 4 skips идентифицированы: reranker; Linux lock/signal tests не пропущены. |
| 5.2 — выполнена | Production cycle exit 0, running+HTTP 200, UTC/counts, согласованность SQLite/embeddings/FTS/provenance и retrieval новым процессом подтверждены. Отдельное изолированное измерение полной индексации: wall 20,92 с, peak RSS 1390,16 MiB. |
| 5.3 — выполнена | Ранее подтверждены update/delete/empty, hash/mtime/metadata A и retrieval новым reader, WAL/SHM refusal без изменения файлов, builder lock. Дополнение подтверждает live first-run failure/restart/health, failed build/restart/handle A и диагностический lifespan/retrieval, второй host запуск, SIGTERM до/после реального replace с завершением собственного one-shot и manual recovery, HTTP после восстановления и отрицательный recovery при `up=0`. Граница наблюдения first-run state указана выше. |

Буквальные критерии 5.3 покрыты совокупностью ранее сохранённых и новых
подтверждений; задача отмечена `[x]`, итого **21/21**. Неподтверждённых
обязательных критериев 5.3 не осталось. Автоматические tests отдельно проверяют
identity/terminal-state/удержание lock и матрицу recovery failures; новые live
результаты не приписывают им выполнение настоящего Docker reindex.
Повторные серверные проверки не требуются. Change готов к архивированию
со стандартной синхронизацией delta specs после успешной строгой валидации;
в рамках этой актуализации архивирование, commit и push не выполняются.

Hit@5 ≥90% не является gate этого этапа; строгая durability при power loss
не входит в заявленную гарантию. Change не архивирован; реализация, `SPEC.md`,
`ROADMAP.md` и `README.md` при сверке не изменялись.

## История дополнения 4.3: signal/identity покрытие, 2026-10-20

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
пока не выявлено. На момент дополнения Linux-прогон ещё ожидался;
теперь он подтверждён: **42 passed, 0 skipped**, включая все 14 новых cases.

Исторические результаты локальной сессии 2026-10-20:

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

Команда, ранее подготовленная для подтверждения 4.3 из корня Linux checkout
с уже применявшимся acceptance container (повторять прогон не требуется):

```bash
docker compose run --rm --no-deps -v "$PWD:/workspace:ro" -v "$PWD/data:/data:ro" -w /workspace/app app sh -c 'bash -n /workspace/reindex.sh && python -m pip install --no-cache-dir pytest==9.1.1 && python -m pytest -q -rs -p no:cacheprovider tests/test_reindex_script.py'
```

Команда выполняет script tests с fake Docker в PATH и временными fixtures;
реальный `reindex.sh` против production Docker не запускается. Требуется
успешный прогон всех script cases без Linux skips. По данным оператора он
выполнен: **42 passed, 0 skipped**, включая 14 новых cases. Это Linux fake-Docker
подтверждение 4.3, а не live one-shot испытания. На момент этого дополнения **4.3 и 5.2 были закрыты, 5.3 оставалась открытой**;
change не архивирован.

## Проверки этой актуализации, 2026-10-21

`git diff --check` — exit 0; `openspec.cmd validate --all --strict` —
**10 passed, 0 failed**. Diff проверен на scope и secrets: изменены только этот
отчёт и `tasks.md`, значений credentials/DSN/tokens в добавлениях нет.
`openspec.cmd instructions apply --change atomic-full-reindex --json` —
`state: all_done`, **21 complete / 21 total, 0 remaining**.
Pytest/mypy и серверные испытания повторно не запускались: менялась только
документация, результаты Linux-прогонов выше получены от оператора.
