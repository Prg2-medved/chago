# Spec Delta

## Purpose

Обеспечить ручную полную переиндексацию Wiki.js с атомарной публикацией согласованных данных и восстановлением приложения на новом либо сохранённом рабочем индексе.

## ADDED Requirements

### Requirement: Single administrative reindex operation
Система SHALL предоставлять `./reindex.sh`, который останавливает только Compose service `app`, выполняет one-shot `docker compose run --no-deps app python -m app.indexer` с однозначной identity и контролируемым lifecycle и затем пытается снова запустить `app` после успеха и ошибки индексатора. LLM и Wiki.js SHALL NOT требовать остановки. Команда SHALL сохранять ненулевой код ошибки индексатора; при успешной индексации и ошибке повторного запуска SHALL возвращать ненулевой код и отдельную безопасную диагностику. При ошибке остановки SHALL NOT запускать индексатор. Документация SHALL указывать недоступность чата во время операции и восстановление `docker compose up -d app` после прерывания и подтверждения завершения своего индексатора. Публичный HTTP endpoint переиндексации SHALL NOT добавляться.

#### Scenario: Successful maintenance cycle
- **WHEN** оператор запускает команду с корректной конфигурацией
- **THEN** `app` останавливается до сборки и запускается после публикации нового индекса, команда возвращает 0

#### Scenario: Failed indexer or service operation
- **WHEN** индексатор завершился ошибкой либо остановка/повторный запуск app не удались
- **THEN** команда возвращает ненулевой код, не запускает сборку после неудачной остановки и пытается восстановить app после ошибки сборки, сохраняя код индексатора и отдельно сообщая ошибку восстановления

### Requirement: Confirmed application recovery
Восстановление app SHALL считаться успешным только после проверки в пределах 60 секунд: текущий контейнер service `app` того же Compose project находится в running и его существующий `/health` возвращает HTTP 200 с JSON `{"status":"ok"}`. Probe SHALL выполняться внутри выбранного контейнера с timeout запроса не более 2 секунд; после ответа SHALL подтверждаться тот же container ID/running без restart за время probe. При смене контейнера/restart проверка SHALL повторяться в пределах общего deadline. Код 0 от `compose up -d` SHALL NOT быть достаточным. Timeout, завершение процесса или невозможность проверки SHALL давать отдельную ошибку восстановления с сохранением исходного кода failed indexer. Блокировка операции SHALL удерживаться до результата проверки. HTTP probe SHALL NOT объявляться проверкой готовности LLM или содержимого индекса.

#### Scenario: Compose accepted start but app is unavailable
- **WHEN** `up -d` вернул 0, но app завершился, перезапускается или не прошёл HTTP probe в пределах deadline
- **THEN** восстановление объявляется неуспешным; при успешной публикации новый индекс сохраняется, команда возвращает ненулевой код

#### Scenario: Delayed successful recovery
- **WHEN** текущий app прошёл running/HTTP/identity проверки до deadline после успешной либо неудачной индексации
- **THEN** восстановление подтверждается, итоговый статус сохраняет результат индексатора; health без индекса остаётся допустимым при first-run failure

### Requirement: Own one-shot termination on interruption
До запуска one-shot скрипт SHALL назначать уникальные имя и метку текущей операции и устанавливать обработчики INT/TERM. Только подтверждённый container ID с соответствующими identity/project SHALL быть целью stop/kill/remove; broad service cleanup и остановка только Docker CLI SHALL NOT считаться завершением индексатора. Прерывание во время создания SHALL обрабатываться с reconciliation после завершения launch-команды, включая потерю returned ID. При INT/TERM скрипт SHALL выполнить bounded graceful stop, при необходимости kill и подтвердить terminal state до удаления своего контейнера и освобождения блокировки. Чужие контейнеры SHALL NOT затрагиваться. При невозможности подтвердить identity/завершение SHALL сообщаться ошибка и необходимость ручной проверки, без автоматического запуска app и без заявления об успешном cleanup.

#### Scenario: Signal during creation or indexing
- **WHEN** INT/TERM приходит во время создания контейнера, потери stdout с ID или работы индексатора
- **THEN** скрипт разрешает identity по собственным имени/метке/project, завершает только свой контейнер, подтверждает terminal state и возвращает ненулевой статус сигнала

#### Scenario: Foreign container or unavailable Docker
- **WHEN** найденное имя принадлежит другой операции либо Docker не позволяет подтвердить завершение
- **THEN** чужой контейнер не изменяется, автоматическое восстановление app не выполняется и оператор получает безопасную диагностику для ручной проверки

### Requirement: Exclusive reindex execution
Административная операция SHALL исключать второй одновременный запуск до любых действий с app и удерживать блокировку до завершения восстановления. Индексатор SHALL исключать одновременную сборку/публикацию по одному активному пути, включая прямые CLI-запуски. Конкурирующий запуск SHALL завершаться контролируемой ошибкой без изменения активного индекса. После завершения/аварийного завершения владельца блокировки следующий запуск SHALL быть возможен без ручного удаления stale PID-файла. Прямой запуск индексатора SHALL документироваться как низкоуровневая команда, требующая уже остановленного app.

#### Scenario: Competing administrative commands
- **WHEN** первый reindex выполняется и оператор запускает второй
- **THEN** второй запуск возвращает ошибку занятости до stop/start app и не влияет на первую операцию

#### Scenario: Competing indexers and released lock
- **WHEN** второй индексатор обращается к тому же output во время сборки первого, а затем первый завершается
- **THEN** параллельная сборка отклоняется, а последующий запуск может получить освобождённую блокировку

### Requirement: Complete read-only rebuild
Индексатор SHALL получать полный результат подготовленного Wiki.js read-only view, проверять все строки и завершение чтения/transaction до построения публикуемого поколения. SHALL сохраняться существующие contracts ingestion, deterministic chunking/provenance, local CPU E5, проверка полных inputs ≤512 tokens без truncation и FTS5. Все документы, chunks, embeddings и lexical данные SHALL пересобираться с нуля отдельно от активного состояния; network access SHALL ограничиваться источником Wiki.js, без загрузки models или внешних inference API. DB credentials SHALL браться только из environment/secrets.

#### Scenario: Updated removed and excluded pages
- **WHEN** новый полный результат view содержит изменённую страницу и больше не содержит удалённую либо ставшую неопубликованной страницу
- **THEN** после успеха новый индекс содержит актуальный Markdown первой и не содержит documents/chunks/embeddings/FTS записей второй

#### Scenario: Incomplete or invalid source
- **WHEN** connection, SELECT, чтение всех rows, завершение transaction либо validation любой строки завершается ошибкой
- **THEN** весь reindex отклоняется без публикации частичного результата и изменения рабочего индекса

#### Scenario: Empty published corpus
- **WHEN** полный успешный SELECT возвращает ноль допустимых документов
- **THEN** публикуется валидный пустой индекс с нулём chunks, embeddings и lexical записей; пустота не считается ошибкой чтения

### Requirement: Atomic activation of one complete file
Активный индекс SHALL быть одним SQLite-файлом с documents, chunks, source metadata, embeddings, model/tokenizer identity и lexical extension одного поколения. Новый файл SHALL строиться на том же filesystem рядом с активным, закрываться и проверяться до атомарной замены. Проверка SHALL включать SQLite integrity/foreign keys, provenance, полноту/совместимость embeddings, lexical content/postings и metadata. Все readers/writers кандидата SHALL быть закрыты до замены. Промежуточные файлы SHALL NOT становиться активными. Output SHALL NOT попадать в model assets, включая aliases. Старые отдельные build/query CLI SHALL сохранять прежние contracts.

#### Scenario: Candidate validation and activation
- **WHEN** все этапы завершены и кандидат повторно прочитан с успешными проверками
- **THEN** единственная атомарная замена делает активным весь новый индекс; повторное открытие даёт согласованные данные без зависимости от staging-файлов

#### Scenario: Invalid candidate
- **WHEN** отсутствует embedding, повреждены FTS postings либо несовместимы metadata кандидата
- **THEN** публикация запрещается и прежний индекс остаётся неизменным

### Requirement: WAL safe file replacement
Публикация main SQLite файла SHALL допускаться только при остановленном app, соблюдении builder lock всеми административными владельцами и закрытых handles кандидата. Кандидат SHALL быть полностью checkpointed, в DELETE journal mode, без зависимости от WAL/SHM/journal. У активного пути непосредственно перед replace SHALL отсутствовать WAL/SHM/journal sidecars; WAL-format активного файла либо любой такой sidecar, даже пустой или без main file, SHALL приводить к отказу. Индексатор SHALL NOT checkpoint/нормализовать активную БД либо удалять её sidecars ради замены. Нормализация собственного staging SHALL проверять результаты checkpoint/journal-mode и итоговое отсутствие sidecars; busy/неполный checkpoint SHALL запрещать публикацию. Старое рабочее состояние SHALL сохраняться без изменений при отказе.

#### Scenario: Active WAL or orphaned sidecars
- **WHEN** active использует WAL, имеет committed данные в WAL или рядом найдены WAL/SHM/journal sidecars, в том числе при отсутствии main file
- **THEN** reindex отклоняется без изменения файлов старого состояния и без replace; восстановление WAL выполняется отдельно оператором через SQLite

#### Scenario: Candidate WAL normalization fails
- **WHEN** candidate имеет WAL и checkpoint занят/неполон, DELETE mode не установлен или sidecars остались после закрытия
- **THEN** кандидат не публикуется, активный индекс не меняется

#### Scenario: Standalone candidate replaces clean active
- **WHEN** candidate успешно нормализован/проверен и оба пути свободны от sidecars при соблюдении предусловий
- **THEN** атомарный replace и restart используют новый самостоятельный файл без переноса WAL/SHM старого поколения

### Requirement: Failed rebuild preserves the previous generation
Любая ошибка до успешной атомарной замены, включая chunking, model assets/inference, запись, нехватку места, validation или саму замену, SHALL сохранять прежний активный файл и его metadata неизменными. После ошибки сборки административная команда SHALL восстанавливать app на старом индексе. Если прежнего индекса нет, ошибка SHALL NOT создавать активный частичный файл и отсутствие SHALL обозначаться явно. Временные данные текущего запуска SHALL удаляться при штатном успехе/ошибке; остатки после аварийного прерывания SHALL NOT использоваться как активный индекс или мешать новой сборке. Ошибка запуска app после успешной публикации SHALL NOT представляться как откат публикации.

#### Scenario: Failure with an existing index
- **WHEN** любой этап до публикации либо атомарная замена завершается ошибкой
- **THEN** hash старого файла и время успешной индексации не меняются, а после restart старый индекс читается и обслуживает retrieval

#### Scenario: First rebuild fails
- **WHEN** рабочего индекса ещё нет и сборка завершается ошибкой
- **THEN** активный файл отсутствует, app запускается в состоянии index unavailable без подмены технической ошибки пустой retrieval выдачей

#### Scenario: Interruption around activation
- **WHEN** процесс прерван до или после атомарной замены и app запускается заново
- **THEN** он использует старый либо полностью новый валидный файл; смесь поколений и staging не загружаются

### Requirement: Successful reindex metadata
Готовый индекс SHALL хранить versioned metadata с UTC-временем успешной индексации и counts документов/chunks в том же SQLite-файле. Эти metadata SHALL становиться активными только вместе с новым поколением и проходить проверку формата/согласованности counts до публикации. Ошибка reindex SHALL NOT изменять время предыдущего успеха. CLI SHALL сообщать counts, время и длительности embedding/indexing, логировать начало/завершение и безопасную категорию ошибки без credentials, DSN, полного Markdown или необработанных backend exceptions.

#### Scenario: Successful timestamp survives restart
- **WHEN** завершён полный reindex и приложение перезапущено
- **THEN** сохранённые время и counts доступны из активного индекса и соответствуют загруженным данным

#### Scenario: Failure does not claim freshness
- **WHEN** новая попытка reindex завершается ошибкой
- **THEN** время прежнего успешного reindex остаётся прежним, отчёт не объявляет неудачную попытку успешной

### Requirement: Restart loads a consistent active snapshot
При startup app SHALL заново открывать настроенный активный SQLite путь read-only и загружать embeddings, documents/chunks и metadata из одного проверенного поколения с lexical validation. Несовместимый/повреждённый индекс SHALL NOT использоваться для retrieval. Отсутствующий индекс SHALL NOT создаваться при чтении. Состояние отсутствия, несовместимости или повреждения SHALL быть явно доступно приложению и безопасной диагностике; app-only startup и существующий `GET /health` SHALL оставаться работоспособными без индекса, Wiki.js и model assets. UI, chat и расширение HTTP health SHALL оставаться задачами следующих этапов.

#### Scenario: Restart after success and failure
- **WHEN** app запускается после успешной публикации либо неудачной пересборки
- **THEN** он загружает соответственно новое либо сохранённое старое поколение, связывая matrix rows с его chunk IDs и metadata

#### Scenario: No compatible active index
- **WHEN** активный путь отсутствует, повреждён либо несовместим
- **THEN** index state содержит явную безопасную причину недоступности, никакой пустой/частичный индекс автоматически не создаётся, текущий `/health` остаётся работоспособным
