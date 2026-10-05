# Wiki.js Markdown Ingestion

## Purpose

Обеспечить воспроизводимое получение исходных Markdown-документов Wiki.js через стабильный PostgreSQL view в локальный снимок для последующих этапов обработки, сохраняя источник технически read-only.

## ADDED Requirements

### Requirement: Read-only source access
Система SHALL читать только административно подготовленный versioned RAG view фиксированным SELECT с явными полями в read-only transaction. Отдельная ingestion-роль SHALL иметь только CONNECT к БД, USAGE на нужную schema и SELECT view, без прямого чтения внутренних таблиц, write/DDL permissions и ownership, позволяющего их изменять. Runtime SHALL NOT создавать, изменять или удалять объекты Wiki.js, выполнять миграции, произвольный пользовательский SQL или загрузку assets. LLM SHALL NOT иметь SQL tools или прямой доступ к PostgreSQL.

#### Scenario: Fetch source pages
- **WHEN** оператор запускает ingestion с подготовленным view и отдельной ролью
- **THEN** фиксированный SELECT в read-only transaction получает полный набор строк view без изменения Wiki.js

#### Scenario: Privilege isolation
- **WHEN** администратор проверяет роль реальными SQL-командами независимо от read-only transaction
- **THEN** SELECT view разрешён, а SELECT внутренних таблиц, INSERT/UPDATE/DELETE/TRUNCATE и CREATE/ALTER/DROP запрещены

#### Scenario: Unsafe view identifier
- **WHEN** конфигурация view содержит SQL-выражение вместо допустимого schema.view
- **THEN** ingestion отклоняет настройку до запроса и не изменяет снимок

### Requirement: Isolated configuration and safe failures
Система SHALL получать DB credentials только через environment/secrets, использовать конечные connect/query timeout и проверять ingestion settings только при запуске CLI. Password и DSN с password SHALL NOT попадать в Git, logs, errors, docs, fixtures, snapshots или API responses. Ошибки SHALL содержать безопасную категорию без исходного driver exception или параметров соединения.

#### Scenario: Missing configuration
- **WHEN** обязательная настройка отсутствует или некорректна
- **THEN** CLI завершается ненулевым кодом с названием настройки без её значения и без изменения снимка

#### Scenario: Independent application startup
- **WHEN** PostgreSQL недоступен или ingestion settings не заданы
- **THEN** HTTP-приложение запускается и `/health` сохраняет ответ `{"status":"ok"}`

#### Scenario: Database failure
- **WHEN** подключение или запрос завершается timeout, ошибкой прав либо иной ошибкой БД
- **THEN** CLI возвращает ненулевой код с безопасной категорией и сохраняет прежний снимок

### Requirement: Complete view result and explicit failures
Система SHALL полностью получить и проверить результат view перед публикацией снимка. Отсутствующие поля, NULL, неверные типы, некорректные даты, дубли ID и сбой чтения/завершения transaction SHALL приводить к ошибке всего запуска. Система SHALL NOT публиковать частично прочитанный результат.

#### Scenario: All returned rows processed
- **WHEN** SELECT успешно завершён и возвращает корректные уникальные строки
- **THEN** каждая строка представлена ровно одним документом снимка

#### Scenario: Interrupted result
- **WHEN** после получения нескольких строк fetch или завершение transaction завершается ошибкой
- **THEN** новый снимок не публикуется и команда возвращает ненулевой код

#### Scenario: Invalid result rows
- **WHEN** результат содержит missing/null обязательное поле, invalid type/date или duplicate page ID
- **THEN** весь запуск завершается ошибкой без замены предыдущего снимка

### Requirement: Published Markdown selection
View SHALL возвращать только однозначно подтверждённые Markdown-страницы, опубликованные на единый момент начала read-only transaction согласно проверенной семантике установленной Wiki.js и разрешённые общей аудитории RAG. Черновики, неопубликованные страницы, иной известный формат и страницы вне периода SHALL исключаться view. По fail-closed контракту неизвестные, неоднозначные или неподтверждённые состояния publication/format, включая неподтверждённый период, SHALL NOT попадать в view. Намеренная ошибка SELECT не требуется. PostgreSQL functions, triggers и искусственные механизмы генерации ошибок только ради validation SHALL NOT добавляться.

Администратор SHALL отдельно подтвердить понятность mapping publication/format и отсутствие необработанных состояний потенциального корпуса на реальной схеме до создания view. Если mapping Wiki.js 2.5.307 нельзя однозначно определить, задача 1.1 SHALL оставаться незавершённой и view SHALL NOT создаваться. Runtime SHALL NOT угадывать внутренние имена колонок или применять альтернативный отбор.

#### Scenario: Mixed page set
- **WHEN** источник содержит опубликованный Markdown, черновик, будущую публикацию, истёкшую публикацию и HTML-страницу
- **THEN** view и снимок содержат только действующую допустимую Markdown-страницу

#### Scenario: Ambiguous publication
- **WHEN** потенциальный корпус содержит неоднозначную публикацию, неизвестный формат или неразбираемую дату периода
- **THEN** такая страница не попадает в view и снимок без требования намеренно завершить SELECT ошибкой

#### Scenario: Unresolved administrative mapping
- **WHEN** live-проверка не позволяет однозначно определить mapping publication/format реальной Wiki.js 2.5.307
- **THEN** задача 1.1 остаётся незавершённой и view не создаётся

#### Scenario: Publication boundaries
- **WHEN** момент начала transaction совпадает с границей периода либо граница открыта
- **THEN** view применяет семантику, подтверждённую для установленной Wiki.js административной live-проверкой

### Requirement: Lossless normalized document contract
Каждый документ SHALL содержать `page_id`, `locale`, `path`, `title`, `source_url`, `updated_at`, `markdown` и `content_sha256`. ID SHALL быть положительным integer, устойчивым при rename в том же источнике; boolean SHALL NOT считаться ID. Locale/path/title SHALL быть непустыми строками. URL SHALL указывать на исходную страницу с учётом locale и кодирования пути, используя настроенный доверенный web origin. Updated timestamp SHALL нормализоваться в UTC; title/path/locale SHALL сохраняться. Markdown SHALL сохраняться дословно, включая Unicode, пробелы и CR/LF; hash SHALL вычисляться по UTF-8 этой строки. Missing/null content SHALL отличаться от допустимой пустой строки. Допустимость публикации SHALL гарантироваться view без дублирования publication metadata в документе.

#### Scenario: Technical Markdown preservation
- **WHEN** документ содержит русский текст, заголовки, Bash, fenced code, таблицы, ссылки, изображения и CRLF
- **THEN** JSON round-trip сохраняет исходную строку без изменений и изображения не скачиваются

#### Scenario: Rename and localized paths
- **WHEN** страница переименована либо разные локали используют одинаковый path
- **THEN** идентичность `(source, page_id)` сохраняется, документы не сливаются по path и URL отражают актуальную локаль и путь

#### Scenario: Empty content
- **WHEN** допустимая страница содержит пустую строку Markdown
- **THEN** она включается с длиной 0 и SHA-256 пустой UTF-8 строки

### Requirement: Reproducible complete local snapshot
Ручная команда SHALL сохранять UTF-8 JSON со `schema_version`, source origin и полным массивом документов в стабильном порядке по page_id. Одинаковые данные SHALL давать побайтово одинаковый снимок независимо от порядка строк view. Время запуска SHALL находиться только в отчёте. Новый снимок SHALL атомарно заменять target только после полного успешного получения и проверки данных; при ошибке прежний снимок SHALL сохраняться.

#### Scenario: Repeat and replace
- **WHEN** два успешных запуска получают одинаковые данные в разном порядке
- **THEN** снимки побайтово совпадают и не содержат накопленных дублей

#### Scenario: Source deletion
- **WHEN** следующий полный результат view больше не содержит ранее полученную страницу
- **THEN** новый снимок не содержит эту страницу

#### Scenario: Failed refresh
- **WHEN** чтение, validation или запись/замена файла завершается ошибкой
- **THEN** прежний файл остаётся неизменным, а при первом запуске target не появляется

#### Scenario: Empty selection
- **WHEN** SELECT успешно возвращает пустой результат
- **THEN** сохраняется валидный snapshot с пустым массивом документов и нулевым количеством в отчёте

### Requirement: Manual operation and verification
Система SHALL предоставлять команду `python -m app.ingestion --output <path>` из app/ и эквивалент Compose без зависимости от LLM. После успешной записи команда SHALL возвращать 0 и выводить title/path/length каждого документа, число полученных/сохранённых документов и путь снимка. Length SHALL означать Unicode code points Markdown. CLI SHALL NOT заявлять число исключённых внутренних страниц, невидимых через view. Ошибка SHALL возвращать ненулевой код. Проверки клиента, документов и snapshot SHALL выполняться offline через fixtures/mock DB adapter без реальной Wiki.js/PostgreSQL, Docker и моделей; они SHALL NOT подменять live-проверку view/прав.

#### Scenario: Operator runs ingestion
- **WHEN** оператор выполняет документированную команду с настроенным источником
- **THEN** получает полный локальный снимок и отчёт без chunking, indexing, retrieval или генерации ответов

#### Scenario: Offline regression tests
- **WHEN** разработчик запускает целевые pytest-тесты без внешних сервисов
- **THEN** проверяются validation строк, сохранность Markdown, database failures и воспроизводимость snapshot

#### Scenario: Live verification pending
- **WHEN** фактический PostgreSQL smoke не выполнен
- **THEN** задачи проверки mapping, поведения view и эффективных прав остаются незавершёнными и документация не заявляет совместимость подтверждённой
