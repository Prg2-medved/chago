# Полная атомарная переиндексация

На Linux-сервере из каталога проекта:

```bash
./reindex.sh
```

Скрипт работает и из другого cwd: Compose project и `data` определяются относительно
самого скрипта. Нужны Bash, `flock`, `timeout`, Python 3, Docker с Compose v2,
существующий каталог `data` и доступ к Docker daemon. При переносе исходников без
сохранения executable bit сначала выполните `chmod +x reindex.sh`.
Перед работой проверьте конфигурацию без вывода секретов:

```bash
docker compose config --quiet
```

Заранее установите E5 assets в `EMBEDDING_MODEL_PATH`, образ app и LLM согласно
существующим offline-инструкциям. Runtime не скачивает модель. Настройте read-only
Wiki.js view и `WIKI_DB_*`/`WIKI_SOURCE_ORIGIN` через environment/secrets; Python
сам не загружает `.env`. Не выводите полную Compose config или DSN в отчёты.
LLM и Wiki.js продолжают работать; app и чат недоступны на время всей операции.

`INDEX_PATH` — общий путь app и one-shot. Compose default `/data/index.sqlite3`
попадает в существующий bind mount `./data:/data`. Каталог должен существовать,
быть доступен для записи индексатору и находиться на локальном filesystem с
поддержкой atomic rename и OS locks. Для локального Python экспортируйте отдельный
локальный путь. Путь внутри E5 assets, symlink/hardlink aliases assets запрещены.
Оставьте место для source JSON, base, semantic и lexical SQLite-копий одновременно,
временных файлов builders, старого active и модели. Фиксированного универсального
лимита места/RAM нет: измеряйте на своём корпусе.

Скрипт берёт неблокирующий lifecycle flock `data/.reindex-operation.lock` до
остановки только `app`, создаёт detached one-shot без `--rm`, ждёт завершения,
сохраняет exit code и затем выполняет `docker compose up -d --no-deps app`.
Ошибка stop запрещает сборку. Ошибка сборки сохраняет свой код даже при ошибке
recovery. Успешная сборка с ошибкой recovery возвращает ненулевой код, новый
опубликованный индекс при этом сохраняется.

После успешного `up` проверка удерживает lock до результата в пределах 60 секунд:
текущий service app должен быть running, probe внутри него должен получить
HTTP 200 и JSON `{"status":"ok"}` с `localhost:8000/health` (HTTP timeout 2 секунды).
После probe повторно проверяются container ID/running/RestartCount. Смена ID или
restart требует повторной проверки в том же deadline. `up=0` само по себе не
означает восстановление. Health подтверждает процесс app; retrieval/LLM этим не
проверяются. `/health` сохраняет прежний контракт и работает без индекса.

## Низкоуровневый индексатор

Только при уже остановленном app и отсутствии внешних readers/writers:

```bash
docker compose stop app
docker compose run --rm --no-deps app python -m app.indexer
docker compose up -d --no-deps app
```

Для Python вне Compose из `app/`, при заранее экспортированных настройках:

```bash
python -m app.indexer
```

Эта команда не управляет app. Все административные builders обязаны соблюдать
соседний постоянный `INDEX_PATH.builder.lock`; ядро Linux освобождает flock при
выходе/kill процесса. Lock-файлы не удаляйте: unlink создаёт гонку разных inode.

Индексатор создаёт уникальный `.index.sqlite3.reindex-*` рядом с active.
В нём полный ingestion → chunking с tokenizer одного LocalEncoder → base SQLite
→ CPU E5 → FTS5. Markdown, code/table/CRLF и provenance сохраняются прежними
policies. Изменённые страницы пересобираются, отсутствующие в view исчезают;
успешный пустой SELECT публикует валидный пустой индекс. Ошибка чтения/transaction
или невалидная строка запрещают публикацию всего результата.

Кандидат содержит все данные одного поколения и additive `reindex_metadata`:
singleton=1, format_version=1, `indexed_at` в UTC, `document_count`, `chunk_count`.
Время фиксируется после build stages и становится активным только с публикацией.
Counts сверяются с inventory. Base/semantic/lexical versions не меняются.
Существующие offline readers продолжают читать расширенный файл.

Кандидат полностью checkpointed в DELETE mode, без WAL/SHM/journal; busy или
неполный checkpoint запрещает публикацию. Проверяются integrity/FK/provenance,
model/tokenizer identity, vectors/ordered IDs, FTS content/postings и metadata
через один retained handle. После закрытия всех handles выполняется единственный
`os.replace(candidate, INDEX_PATH)` — commit point. До него ошибка сохраняет bytes,
hash и timestamp старого active; при first-run failure active не создаётся.
После commit cleanup/report failure не означает откат: отчёт прямо сообщает
`published`/`report_failed` либо `cleanup_warning`.

Индексатор выводит JSON `reindex_start`/`reindex_end`, UTC time, counts и длительности
embedding/indexing. При ошибке выводится безопасная категория без credentials,
DSN, Markdown и backend traceback. Во время detached запуска отчёт доступен в
логах собственного one-shot до его удаления. При прямом CLI он выводится сразу.
Штатный cleanup удаляет только собственный staging. Остатки после kill не
переиспользуются и не являются active; автоматического сборщика остатков нет.

## WAL и backup

До сборки и прямо перед replace active проверяется без открытия SQLite: заголовок
должен иметь rollback DELETE format, рядом не должно быть `-wal`, `-shm`,
`-journal`, даже пустых/осиротевших или при отсутствующем main file. WAL-format
даже после checkpoint — причина отказа. Индексатор не checkpoint/repair active,
не меняет его journal_mode, не удаляет sidecars.

При отказе остановите всех владельцев отдельно, сохраните согласованное состояние
через SQLite backup (при необходимости вместе с исходными WAL/SHM для диагностики),
затем отдельной административной SQLite-сессией выполните recovery/checkpoint и
переход в DELETE. Проверьте результаты checkpoint (busy=0, весь WAL записан),
integrity и закрытие handles. Не удаляйте sidecars вручную ради прохождения preflight.
При восстановлении backup app и все writers должны быть остановлены, backup должен
представлять полное согласованное SQLite-поколение. После проверки запустите app.

## Startup и прерывание

При каждом startup FastAPI читает `INDEX_PATH` read-only, загружает согласованные
snapshot, immutable matrix, ordered IDs и metadata через один retained handle,
закрываемый на shutdown. Wiki.js и E5 inference/assets для чтения не нужны.
Missing/corrupt/incompatible/legacy файл без reindex metadata даёт внутреннее
`index unavailable` с безопасной причиной и требует полного reindex. Автомиграции
или вымышленного времени нет; старые offline CLI contracts сохраняются.
Валидный пустой корпус — available с counts=0, а не unavailable. Новых endpoints
или UI этот этап не добавляет.

Каждый host запуск заранее назначает уникальное имя `chago-reindex-<run-id>` и label
`chago.reindex-run=<run-id>`; перед stop/kill/rm проверяются точное имя, label,
Compose project и ID. При INT/TERM во время launch сигнал откладывается до окончания
launch-команды, затем identity разрешается даже при потере stdout ID. Собственный
контейнер получает graceful stop с timeout 10 секунд, при необходимости kill;
terminal state подтверждается inspect до удаления и освобождения lock. Завершение
процесса Docker CLI само по себе не доказывает завершения контейнера.

При прерывании код 130/143; app автоматически не запускается. Если Docker/identity
не удалось проверить, скрипт сообщает имя/run-id/project для ручной проверки и
не останавливает чужие контейнеры. Перед recovery или следующим reindex убедитесь
через `docker inspect <точное-имя>` в соответствующих labels/ID и terminal state
собственного one-shot; при необходимости остановите именно этот подтверждённый ID.
Затем:

```bash
docker compose up -d app
```

Проверьте running/HTTP и отдельно поколение индекса. После SIGKILL/сбоя host могут
остаться one-shot и staging: требуется та же ручная проверка. Process interruption
вокруг commit даёт старое либо новое полное поколение. Строгая durability при
power loss/fsync-протокол не заявлены, как и hot reload или поддержка сетевых FS.

## Локальные fixtures

Из `app/` без Wiki.js/E5 assets:

```bash
python -m pytest tests/test_config.py tests/test_reindex_metadata.py tests/test_indexer.py tests/test_index_state.py tests/test_reindex_script.py
```

`test_pipeline_update_delete_empty_reopen` выполняет тот же pipeline на mock source/
encoder с реальными SQLite/FTS и reopen отдельным процессом;
`test_cli_safe_report_and_post_commit_cleanup` вызывает CLI main и проверяет report.
Linux lock/signal tests нужно действительно выполнить на Linux; Windows skips
не являются приёмкой. Серверные результаты фиксируются отдельно после фактического
прогона, без изменения исторических отчётов.
