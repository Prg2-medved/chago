# Design

## Context

См. proposal.md и SPEC.md §6–8, §30. По предоставленной live-проверке Wiki.js 2.5.307 read-only API token выполняет `pages.list`, но `pages.single` возвращает `PageViewForbidden 6013`. Расширять права до manage/delete/Full Access нельзя. Change ещё не реализован; старый GraphQL-дизайн заменяется целиком.

Существующий HTTP startup и `/health` остаются независимыми от ingestion и доступности источника. Реальная схема PostgreSQL 15.12 и mapping проверены административно; результаты и определение view приведены в docs/wikijs-markdown-ingestion.md.

## Goals / Non-Goals

**Goals:** технически read-only доступ, lossless документы и all-or-nothing локальный snapshot для будущего chunker.

**Non-Goals:** миграции Wiki.js, универсальный DB/provider framework, публичный ingestion endpoint, автоматический запуск, SQL из пользовательского ввода и доступ LLM к БД. Административная подготовка источника отделена от runtime.

## Decisions

### 1. Фиксированный SELECT из versioned view

Небольшой `wiki_client.py` использует один PostgreSQL driver psycopg 3. Единственный запрос данных выбирает явно перечисленные поля из настроенного versioned view, без LIMIT, пагинации, SELECT * и пользовательского SQL. Имя schema/view проверяется и компонуется средствами SQL Identifier драйвера, никогда строковой интерполяцией. Служебные команды ограничены началом/окончанием read-only transaction и установкой query timeout. Миграций, DDL, write-запросов и fallback к внутренним таблицам нет.

Connect timeout и серверный statement timeout конечны. Данные читаются одним SELECT целиком в read-only transaction; при ошибке execute, fetch или завершения транзакции результат не публикуется. Соединение закрывается. Автоматических retries нет: оператор повторяет полный запуск. Диагностика содержит безопасную категорию (configuration, connection, permission, query timeout, query, invalid row, output), при необходимости page ID, но не сырые исключения драйвера, параметры соединения, пароль, DSN или содержимое строк.

Роль принадлежит только ingestion: CONNECT к Wiki.js database, USAGE к выделенной schema и SELECT только на view. Нет прямого SELECT таблиц, INSERT/UPDATE/DELETE/TRUNCATE, CREATE/ALTER/DROP и иных write/DDL возможностей. Администратор проверяет эффективные права, включая PUBLIC, membership, ownership, TEMP/CREATE и привилегированные атрибуты. Ingestion-роль не владеет объектами и не наследует повышенных прав; read-only transaction — дополнительная защита, не замена ограничениям роли. View должен работать без прав вызывающего пользователя на внутренние таблицы; владелец view — отдельная административная роль. Приложение не исправляет grants автоматически.

Альтернативы: расширенный API token нарушает read-only ограничение; прямое чтение внутренних таблиц связывает Chago со схемой Wiki.js. Versioned view изолирует эту зависимость.

### 2. Изолированная конфигурация и ручной запуск

Отдельный типизированный loader в config.py вызывается только CLI, не `load_settings()` HTTP app. Набор имён одинаков в config, `.env.example`, Compose, tests и docs:

| Переменная | Контракт |
| --- | --- |
| `WIKI_DB_HOST` | обязательный непустой host |
| `WIKI_DB_PORT` | integer 1..65535, default 5432 |
| `WIKI_DB_NAME` | обязательное непустое имя БД |
| `WIKI_DB_USER` | обязательная отдельная ingestion-роль |
| `WIKI_DB_PASSWORD` | обязательный непустой секрет, исключён из repr |
| `WIKI_DB_VIEW` | default `rag.rag_wikijs_pages_v1`; ровно schema.view, каждый компонент `[a-z_][a-z0-9_]*`, не более 63 ASCII bytes |
| `WIKI_DB_TIMEOUT_SECONDS` | положительный integer, default 30, максимум 2147483; connect timeout в секундах, statement timeout в миллисекундах |
| `WIKI_SOURCE_ORIGIN` | обязательный HTTP(S) origin для ссылок без credentials/path/query/fragment; trailing slash нормализуется |

DB credentials поступают только из environment/secrets. Передавать драйверу отдельные параметры, не публичный DSN. Ошибка конфигурации называет переменную, но не её значение; секреты не попадают в repr, exception chain, snapshot, docs или fixtures. Старые WIKI_BASE_URL/WIKI_TOKEN/WIKI_TIMEOUT_SECONDS не используются. Локальный Python не загружает `.env` автоматически. Compose передаёт настройки без обязательной валидации при старте HTTP app и монтирует `./data:/data`.

CLI из app/: `python -m app.ingestion --output ../data/wiki-documents.json`. Из корня через Compose: `docker compose run --rm --no-deps app python -m app.ingestion --output /data/wiki-documents.json`. Output обязателен. Существующий HTTP app не останавливается: этот этап не меняет индекс. Полный reindex orchestration относится к следующему этапу.

### 3. Контракт view и отбор

Выбран вариант 1: view возвращает только допустимые опубликованные Markdown-страницы. Это уменьшает раскрываемый ingestion-роли корпус и исключает дублирование правил отбора в Python. Допуск для общей LAN-аудитории проверяется администратором по SPEC §3.1; права Wiki.js автоматически через PostgreSQL не наследуются.

Публичные aliases view: `page_id` (положительный integer), `locale`, `path`, `title`, `markdown` (text), `updated_at` (ISO 8601 text с timezone). View сохраняет исходный `pages.updatedAt`, проверенный как UTC text с `Z`; parsing и нормализация в UTC выполняются Python при построении документа. Это имена контракта Chago. Все поля NOT NULL на уровне контракта, пустой markdown допустим; locale/path/title непустые. ID уникален. Стабильное имя по умолчанию `rag.rag_wikijs_pages_v1`.

Первая live-задача проверяет фактические таблицы, raw Markdown, editor/format, publication state/period, locale/path/title/id/updated timestamp и mapping в aliases. Только после этого администратор фиксирует определение view. Один SELECT оценивает публикацию на единый момент начала его read-only transaction в БД. Точные границы периода и открытые границы устанавливаются по реальной Wiki.js, не угадываются.

Контракт fail-closed: view возвращает только страницы с однозначно подтверждёнными Markdown-форматом, действующей публикацией и допуском общей аудитории RAG. Draft/unpublished, иной известный формат и недействующий период исключаются. Неизвестные, неоднозначные или неподтверждённые состояния publication/format, включая неподтверждённый период, также не попадают в view. Обычный PostgreSQL VIEW не обязан намеренно завершать SELECT ошибкой. PostgreSQL functions, triggers и искусственные механизмы генерации ошибок только ради validation не добавляются.

Административная live-проверка отдельно подтверждает понятность mapping publication/format и отсутствие необработанных состояний потенциального корпуса. Если mapping реальной Wiki.js 2.5.307 нельзя однозначно определить, задача 1.1 остаётся незавершённой и view не создаётся.

Python валидирует каждую возвращённую строку и полное завершение чтения. NULL, отсутствующее поле, неверный тип, некорректная дата, duplicate ID — ошибка всего запуска. Boolean не принимается как integer ID. Полнота ограничена корпусом view. Клиент не может обнаружить ошибочно отфильтрованные строки: корректность view проверяется административным smoke. Счётчиков исключённых внутренних страниц в CLI нет, поскольку роль их не видит.

### 4. Frozen document model и lossless Markdown

В ingestion.py frozen dataclass содержит `page_id`, `locale`, `path`, `title`, `source_url`, `updated_at`, `markdown`, `content_sha256`. Publication metadata не дублируется в документе: допустимость гарантирует view. Идентичность — `(source, page_id)`, где source — нормализованный WIKI_SOURCE_ORIGIN. Rename не меняет ID.

Updated timestamp нормализуется к ISO 8601 UTC с единым форматом. URL строится из доверенного origin, locale и path с percent-encoding сегментов, сохранением разделителей и проверяется live для русских путей и locale. Path никогда не становится локальным filename. Markdown не trim-ится, не нормализуется по Unicode и не меняет CR/LF; SHA-256 считается по UTF-8 исходной строки. Length — число Unicode code points. HTML/AST extraction и Markdown parser не нужны.

### 5. Детерминированный JSON snapshot

Формат: `{"schema_version": 1, "source": "<origin>", "documents": [...]}`. UTF-8, ensure_ascii=False, sort_keys=True, indent=2, одна финальная LF; документы сортируются по числовому page_id. Время запуска и duration только в отчёте, не в файле. Одинаковые данные view дают побайтово одинаковый результат; наступление границы публикации закономерно меняет корпус.

Полностью получить данные, успешно завершить read-only transaction и проверить документы, затем записать уникальный temporary file рядом с target, закрыть и заменить target через os.replace. При ошибке удалить только собственный temporary file, сохранить предыдущий snapshot; первый неудачный запуск не создаёт target. Пустой успешный результат — валидный пустой snapshot. Весь небольшой корпус хранится в памяти. Ручные запуски выполняются последовательно; блокировка полного reindex относится к следующему этапу.

### 6. Проверяемость и документация

Offline fixtures/mock DB adapter проверяют форму фиксированного SELECT, безопасные identifiers, read-only transaction, connect/query timeout, полное fetch и безопасные ошибки. Чистые тесты покрывают validation и lossless Markdown; файловые — повторяемость, пустой корпус, удаление исчезнувшей страницы и отказы чтения/записи/replace. Тесты не требуют Wiki.js/PostgreSQL, Docker или моделей. Mock не заменяет проверку эффективных прав и поведения view.

CLI печатает success только после записи: title/path/length в стабильном порядке, время запуска, число полученных/сохранённых документов и output path. Ошибка — exit 1, argparse — 2 при неверном вызове. Нет выдуманных счётчиков исключений.

Docs описывают административную подготовку view/роли, environment без секретов, локальную и Compose команды, snapshot, offline tests и отдельный live smoke. Live проверяет реальные SQL permissions, семантику fail-closed отбора и границ, понятность mapping и отсутствие необработанных состояний, исходный Markdown, metadata, URL, полноту и повторяемость. Проверки не отмечаются выполненными без реального smoke.

## Risks / Trade-offs

- Непроверенная схема и правила публикации → задача 1.1 блокирует финальное определение view и live compatibility; SQL DDL до неё не фиксируется.
- View не применяет Wiki.js ACL автоматически → администратор ограничивает общий корпус по SPEC §3.1 и перепроверяет после изменения политики доступа.
- Унаследованные права → проверка effective grants и реальные запреты SQL отдельно от read-only transaction.
- Обновление Wiki.js → повторная проверка mapping и сохранение v1 контракта администратором; runtime не мигрирует источник.
- Большие страницы → измерить объём и память на smoke, не усекать Markdown.

## Migration Plan

Сначала проверить установленную схему, затем административно создать и проверить view/роль. После реализации установить driver, настроить environment/secrets и каталог data, собрать app image, выполнить offline tests и live CLI smoke. Runtime миграций нет. Откат приложения — прекратить CLI и вернуть прежний image; удаление административных объектов при необходимости выполняется отдельно администратором. README.md и ROADMAP.md не меняются.
