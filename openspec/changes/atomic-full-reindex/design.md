# Design

## Context

Мотивация — proposal.md, нормативная основа — SPEC.md §7, §9, §11, §24, §27 и ROADMAP.md §9.

Наблюдаемая реализация:

- `wiki_client.fetch_pages` выполняет фиксированный SELECT в read-only transaction и возвращает rows только после fetchall и успешного завершения transaction; `ingestion.build_documents` валидирует их.
- `chunking.build_output`, `index_storage.parse_output/write_snapshot`, `semantic_storage.build` и `lexical_storage.build` уже покрывают отдельные переходы. Каждый file writer публикует свой output атомарно, но общей команды и активного пути нет.
- `StorageReader` проверяет base/provenance; `SemanticReader` загружает immutable matrix и IDs; `LexicalReader` валидирует content/postings. `HybridIndex` уже читает обе ветки через одно retained read-only соединение.
- Base schema v1 допускает additive tables. Semantic/lexical extensions уже живут в том же SQLite файле.
- `main.py` содержит только app и независимый `/health`. Startup не загружает индекс. Compose монтирует `./data:/data`, передаёт настройки Wiki.js и E5, но не активный index path.
- Тесты storage/semantic/lexical используют небольшие fixtures и известные нормализованные vectors; они пригодны для сквозных отказов без настоящей модели. В docs есть инструкции и исторические отчёты, которые не нужно переписывать.

Main hybrid spec содержит исторический quality gate, расходящийся с актуальным SPEC.md: Hit@5 ≥90% вынесен в post-MVP. Этот change не исправляет историю и не зависит от достижения порога.

## Goals / Non-Goals

**Goals:** один проверяемый момент активации, единственный активный путь, повторное использование существующих validators, восстановление app после ошибки и доказательство согласованности после restart.

**Non-Goals:** горячая смена поколения, автоматическая свежесть, миграции Wiki.js, изменение chunking/ranking policies, production chat endpoint, UI или расширение health. Отдельный storage/semantic/lexical CLI не становится full reindex и не обязан производить новые orchestration metadata.

## Decisions

### 1. Два уровня: host lifecycle и Python pipeline

`reindex.sh` предназначен для Linux-сервера из исходной среды SPEC.md. Скрипт определяет Compose project относительно своего каталога, проверяет необходимые команды и берёт неблокирующий `flock` на постоянном `data/.reindex-operation.lock` до `docker compose stop app`. Далее запускает собственный one-shot через `docker compose run --detach --no-deps --name <unique-name> --label chago.reindex-run=<random-run-id> app python -m app.indexer`, дожидается результата и выполняет `docker compose up -d --no-deps app`. Здесь намеренно нет `--rm`: завершившийся контейнер сохраняет exit code до inspect/wait и удаляется скриптом после подтверждения результата. При ошибке индексатора сохраняется его exit code, ошибка восстановления сообщается отдельно. Cleanup/trap не должен маскировать исходный статус. После неудачной остановки сборка запрещена, попытка восстановления app допустима.

Успех `up -d` означает только отправку команды запуска. Восстановление подтверждается в течение 60 секунд: определить ID service `app` в том же Compose project, дождаться состояния running и HTTP 200 с JSON `{"status":"ok"}` от существующего `/health` через probe внутри именно этого контейнера (Python stdlib, localhost:8000, timeout каждого запроса ≤2 секунд). После ответа повторно проверить тот же ID и running state без увеличения RestartCount за probe; при смене ID/restart проверку повторить в пределах общего deadline. Exit/restarting/dead, timeout, неверный HTTP/JSON или ошибка Docker означают неуспешное восстановление. Lifecycle lock удерживается до окончания проверки. Probe не требует LLM/Wiki.js/model assets и не меняет контракт `/health`; согласованность загруженного индекса проверяется отдельно lifecycle/acceptance tests. При успешной индексации и неуспешном восстановлении вернуть ненулевой код, сохранив опубликованный индекс; при failed build сохранить код индексатора.

В самом индексаторе — отдельная неблокирующая OS file lock на фиксированном соседнем lock-файле активного пути. Она защищает direct CLI builders и освобождается ядром при выходе процесса. Host lifecycle lock и builder lock имеют разные имена: контейнер не пытается повторно захватить блокировку host-скрипта. Builder lock удерживается до конца публикации/cleanup. Файл блокировки не удалять: unlink создаёт гонку разных inode. На Linux использовать stdlib `fcntl`; platform-specific часть изолировать и проверять на целевой Linux-среде. Прямой CLI — только при уже остановленном app, это явное эксплуатационное предусловие.

До обращения к Docker генерировать непредсказуемый run-id и уникальное имя, зарегистрировать traps и сохранить identity текущего запуска. Returned container ID — основной адрес; при ошибке/прерывании создания искать только точное заранее выбранное имя и проверять run-id label и Compose project labels. Коллизия имени или несовпадение labels запрещают stop/kill/rm этого контейнера. Нельзя выбирать по service `app`, списку всех one-off, шаблону имени или одному PID процесса Docker CLI.

На коротком участке создания trap только отмечает pending INT/TERM: обработка начинается после завершения launch-команды и разрешения identity, чтобы контейнер не появился уже после cleanup. При pending signal, ошибке создания или потере stdout выполнить reconciliation по точному имени/labels. При INT/TERM остановить только подтверждённый собственный container ID (`docker stop` с timeout 10 секунд, затем при необходимости `docker kill`), через wait/inspect подтвердить terminal state и лишь затем удалить его и освободить lifecycle lock. Исчезновение после подтверждённого удаления также допустимо. Сигнал возвращает ненулевой статус (130/143); ожидание CLI само по себе не доказывает остановку контейнера. Если Docker недоступен и завершение/identity нельзя подтвердить, сообщить безопасную ошибку с identity запуска и требованием ручной проверки, не запускать app автоматически и не объявлять cleanup успешным. После такого сбоя/SIGKILL/сбоя host перед ручным recovery или следующим reindex оператор обязан убедиться в отсутствии оставшегося one-shot; builder lock дополнительно защищает публикацию. Документировать `docker compose up -d app` после подтверждённого завершения индексатора.

Альтернативы: очередь/job API добавляет инфраструктуру; один lock одновременно в host и контейнере приводит к самоблокировке. Одна лишь блокировка публикации не защищает stop/start от второго административного скрипта.

### 2. Staging pipeline без записи в активный файл

Ввести `INDEX_PATH`, default `/data/index.sqlite3` для Compose; app и one-shot индексатор получают одинаковое значение. Каталог должен существовать и быть доступен для записи индексатору. Перед сборкой нормализовать путь, исключить model assets/aliases, не перезаписывать assets. Не использовать новый активный путь как input существующих offline builders.

Под builder lock и после остановки app выполнить fail-closed preflight активного пути, затем повторить непосредственно перед replace: отсутствуют `INDEX_PATH-wal`, `INDEX_PATH-shm` и `INDEX_PATH-journal`, включая пустые/осиротевшие файлы при отсутствующей БД; существующий активный файл должен иметь rollback DELETE format (проверка journal format заголовка без открытия WAL/recovery). WAL-format или любой sidecar означает безопасный отказ без checkpoint, смены journal_mode, удаления/переименования sidecars или изменения старой БД. Оператор отдельно восстанавливает/закрывает WAL через SQLite при остановленных владельцах и делает backup согласованного состояния перед повтором. Неподтверждённые внешние readers/writers не поддерживаются: все административные процессы должны соблюдать builder lock, app остановлен. Проверка отсутствия sidecars не заменяет это предусловие.

`app.indexer` создаёт уникальный временный каталог непосредственно в parent активного файла и выполняет последовательность:

1. `ingestion.ingest` пишет полный проверенный `source.json` только в staging.
2. `chunking.load_snapshot/build_output` с текущими defaults и tokenizer одного `LocalEncoder` создают output; `index_storage.parse_output/write_snapshot` создают staging storage DB. Chunking JSON можно передавать в памяти, поскольку downstream принимает StorageSnapshot.
3. `semantic_storage.build` строит staging semantic DB через тот же encoder, с прежней identity и проверкой бюджета.
4. `lexical_storage.build` строит staging candidate DB, сохраняя vectors и текущие policies; inference повторно не выполняется.
5. В candidate добавляются reindex metadata, он приводится к самодостаточному DELETE snapshot, полностью проверяется заново и закрывается.
6. Один `os.replace(candidate, INDEX_PATH)` активирует поколение. Никакой промежуточный builder не получает активный путь как output.

До replace любая ошибка оставляет активный файл побайтово прежним. После успешного replace cleanup/report failure нельзя объявлять сохранением старого поколения: commit point уже пройден. Cleanup удаляет только собственный staging, не активный файл или чужие каталоги. Остатки после kill не читаются и не переиспользуются. Не добавлять автоматический сборщик старых staging-каталогов в этот change.

Альтернатива — единый новый SQLite writer — дублирует существующую проверенную логику. Последовательные staging DB приемлемы для малого корпуса и дают простые точки проверки отказов. Несколько активных файлов/manifest потребовали бы дополнительного протокола согласованности.

### 3. Additive metadata и полная проверка перед commit point

Добавить только к полному orchestration snapshot таблицу `reindex_metadata`: singleton, format_version=1, `indexed_at` в UTC, document_count, chunk_count. Timestamp фиксируется после завершения основных build stages непосредственно перед итоговой проверкой; он обозначает подготовленный успешный reindex и становится виден только при активации. Counts сверяются с фактическим inventory. Время отдельных ingestion JSON не меняется: его reproducibility contract сохраняется.

Все staging writers явно используют `journal_mode=DELETE` с проверкой возвращённого режима. Если у собственного candidate всё же WAL, после закрытия остальных его handles writable SQLite connection выполняет `wal_checkpoint(TRUNCATE)` с проверкой успешного результата (busy=0, WAL полностью checkpointed), затем `journal_mode=DELETE` с проверкой результата `delete`. Ошибка/busy запрещает публикацию. После commit/close не должно остаться `candidate-wal`, `candidate-shm`, `candidate-journal`; вручную удалять их ради прохождения проверки нельзя. Это нормализация только собственного staging, никогда активной БД.

Затем проверить candidate через retained `LexicalReader`, semantic validation того же handle и reader новых metadata; base reader уже проверяет integrity/FK/provenance. Закрыть все соединения и повторно проверить отсутствие sidecars как candidate, так и активного пути до replace. Проверить итоговые IDs/counts и согласованность model/tokenizer metadata. Не менять base user_version и прежние semantic/lexical format versions ради additive таблицы. Единственная замена main file безопасна только при этих предусловиях: WAL/SHM старого поколения не могут сопровождать новый файл. Основа решения — [SQLite WAL](https://www.sqlite.org/wal.html) и [wal_checkpoint](https://www.sqlite.org/pragma.html#pragma_wal_checkpoint).

Старые отдельные snapshots сохраняют прежние readers/CLI contracts. Для активного индекса full-reindex metadata обязательны; существующий offline snapshot без них обозначается как требующий полного reindex, а не получает вымышленное время успеха. Автоматической миграции нет.

### 4. Startup читает активное поколение, model inference не требуется

Небольшой модуль, например `app/index_state.py`, хранит active snapshot, immutable matrix с ordered chunk IDs, metadata и retained read-only lexical connection; загружает всё через один исходный handle по аналогии с `HybridIndex`. FastAPI lifespan читает `INDEX_PATH` при startup, закрывает handle при shutdown. Model assets/encoder для чтения не загружаются; NumPy требуется лишь при наличии файла и загрузке vectors. Ленивая загрузка сохраняет startup без индекса и тяжёлых model imports.

Отсутствие/повреждение/несовместимость переводит index state в unavailable с безопасной причиной и логом; `/health` сохраняет текущий ответ. Такое состояние не выдаёт пустой valid snapshot. Следующий chat change сможет использовать загруженное поколение и различать unavailable от отсутствия evidence. Отдельного HTTP status endpoint и обещания готового chat API сейчас нет.

Альтернативы: ограничиться reopen тестом CLI не выполняет SPEC.md §7 о загрузке app после restart; создавать placeholder DB маскирует отсутствие индекса; hot reload создаёт ненужный lifecycle.

### 5. Проверки наблюдаемого поведения

Offline pytest для нового pipeline использует mock DB source/encoder, но реальные SQLite writers/readers, FTS5 и atomic replace. Проверяются A→B (изменение и удаление страницы), пустой корпус, provenance code/table/CRLF, counts/timestamp, restart lifecycle и сравнение hash активного A при отказах ingestion/chunking/inference/write/validation/replace. До/после commit point и first-run failure — разные cases.

Host script проверяется через fake `docker` в PATH: порядок stop/run/up, ненулевые статусы, восстановление, повторный запуск под настоящим OS lock, прерывание one-shot. Linux-specific tests выполняются на Linux; локальная недоступность Bash/flock не считается успешной проверкой. Реальная Compose/модель/Wiki.js приёмка отдельно подтверждает полную пересборку, restart и ошибку с сохранением старого индекса. Для удаления/неопубликованных страниц использовать контролируемый read-only source fixture/отдельный подготовленный test view; не менять production Wiki.js ради проверки.

## Risks / Trade-offs

- [Простой app во время E5 inference] → предусмотрен SPEC.md; измерить длительность/память на сервере, не требовать одновременную генерацию.
- [Место для нескольких staging DB и модели] → один data filesystem, проверяемые ошибки записи без изменения active; документировать требования к свободному месту.
- [Файловые блокировки/replace на нестандартном filesystem] → целевая приёмка на локальном Linux filesystem; сетевые FS не заявляются поддержанными без проверки.
- [Restart после публикации не удался] → новый валидный индекс остаётся активным, отчёт отделяет публикацию от обслуживания; повторить `docker compose up -d app`.
- [Process kill или power loss] → гарантировать проверяемый old/new исход для process interruption; строгая durability при потере питания и fsync-протокол не входят в заявленную гарантию.
- [Legacy active DB без orchestration metadata] → явный rebuild required, без изменения отдельного semantic/lexical query по этому файлу.
- [Windows рабочая станция] → planning и переносимые pytest доступны локально; Linux lock/script и Compose acceptance требуют целевой среды, непроведённые проверки остаются открытыми.

## Migration Plan

1. Развернуть согласованные изменения app/script/Compose; установить E5 assets заранее, проверить read-only view и environment, задать `INDEX_PATH` на data mount.
2. Сохранить существующий нужный snapshot отдельно административной процедурой; новый активный индекс появляется только после полного `./reindex.sh`. README.md, ROADMAP.md и исторические отчёты не изменять.
3. При ошибке сборки проверить прежний hash, timestamp и retrieval после restart. При первом неуспешном запуске проверить unavailable state и рабочий app-only health.
4. При успехе проверить restart/reopen новым процессом, counts/IDs/metadata и известные semantic/lexical/hybrid запросы. Зафиксировать server acceptance в новом отчёте без secrets и без утверждения Hit@5 ≥90%.
5. Программный rollback: остановить app, вернуть предыдущую совместимую версию; при необходимости восстановить отдельно сохранённый SQLite при остановленном app и затем запустить его. Автоматическое хранение поколений/rollback после успешного commit не добавляется.
