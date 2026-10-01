# Wiki.js Markdown ingestion

## Статус

Live-проверка Wiki.js 2.5.307 / PostgreSQL 15.12 для задачи 1.1 выполнена 2026-10-01. Реальная схема и mapping источника подтверждены read-only SQL-запросами и кодом запущенной Wiki.js. PostgreSQL ingestion ещё не реализован; команды CLI ниже остаются целевым интерфейсом после `$openspec-apply-change`.

Предыдущая проверка read-only API позволила прочитать список из 31 страницы, но `pages.single` завершался `PageViewForbidden 6013`. Увеличивать права API-токена запрещено. Источником ingestion поэтому остаётся PostgreSQL Wiki.js → административно созданный versioned view → отдельная роль с SELECT только view → Chago ingestion.

Задача 1.1 подтверждена. Задачи 1.2, 1.3 и 5.2 остаются открытыми: `rag.rag_wikijs_pages_v1` и ingestion-role ещё не создавались, а PostgreSQL permission smoke ещё не выполнялся.

## Проверенный mapping Wiki.js 2.5.307

Проверен работающий экземпляр Wiki.js 2.5.307 с PostgreSQL 15.12.

Источник страниц:

`public.pages`

Проверенный mapping:

| Контракт | Wiki.js |
| --- | --- |
| page ID | `pages.id` |
| locale | `pages.localeCode` |
| path | `pages.path` |
| title | `pages.title` |
| исходный Markdown | `pages.content` |
| format | `pages.contentType` |
| editor | `pages.editorKey` |
| publication state | `pages.isPublished` |
| private state | `pages.isPrivate` |
| начало периода | `pages.publishStartDate` |
| конец периода | `pages.publishEndDate` |
| updated timestamp | `pages.updatedAt` |

`content` подтверждён как исходный Markdown для страниц с:

```text
contentType = markdown
editorKey = markdown
```

На момент проверки в `public.pages` находилась 31 страница. Наблюдались только две комбинации format/editor/publication/private:

```text
markdown / markdown / published / public — 24
html     / ckeditor / published / public — 7
```

Других состояний потенциального корпуса на момент проверки не обнаружено.

Все 24 Markdown-страницы имели уникальный `id` и непустые `localeCode`, `path`, `title`, `content`, `updatedAt`. `content` не был NULL.

`updatedAt` хранится в Wiki.js как строка ISO 8601 с UTC offset `Z`; все 24 проверенных значения успешно приводятся PostgreSQL к `timestamptz`.

Для текущих 31 страниц:

```text
publishStartDate = ''
publishEndDate   = ''
```

То же состояние наблюдается во всей имеющейся `pageHistory`: исторических примеров непустых publication dates нет.

Код запущенной Wiki.js подтверждает семантику периода публикации:

```text
pageIsPublished = isPublished

если publishStartDate задан:
    publishStartDate <= текущий момент

если publishEndDate задан:
    publishEndDate >= текущий момент
```

Границы периода включительные. Пустая строка означает открытую соответствующую границу.

Точный строковый пример непустого `publishStartDate` / `publishEndDate` на этой инсталляции отсутствует, поэтому его сериализованный вид и timezone не выводятся из предположений. Это ограничение необходимо учитывать при контролируемых проверках 1.2 / 5.2.

Для общей аудитории текущая конфигурация Wiki.js также проверена. Системная группа `Guests` имеет `read:pages` и разрешающее `START` page rule от корня без locale restriction. Все 31 текущая страница имеют `isPrivate = false`.

Этого mapping достаточно для проектирования стабильного `rag.rag_wikijs_pages_v1`. Сам DDL view до задачи 1.2 не считается проверенным.

Административный view должен fail-closed исключать состояния format/publication, которые не соответствуют подтверждённому контракту. Контролируемые проверки будущего, истёкшего и некорректного периода, неизвестного формата и отрицательных permission cases выполняются в задачах 1.2, 1.3 и 5.2 без изменения рабочих Wiki.js страниц.

## Административная подготовка источника

1. Первой live-проверкой исследовать фактическую структуру нужных таблиц и mapping: исходный Markdown, editor/format, publication state, publication period, locale/path/title/id/updated timestamp. Проверить смысл открытых и точных границ периода, а также timezone. Отдельно подтвердить понятность mapping publication/format и отсутствие необработанных состояний потенциального корпуса. Если mapping Wiki.js 2.5.307 нельзя однозначно определить, задача 1.1 остаётся незавершённой и view не создаётся.
2. Согласовать корпус для общей аудитории RAG по SPEC §3.1. PostgreSQL view автоматически не наследует Wiki.js Page Rules; администратор должен подтвердить, что выбранный корпус допустим всем пользователям LAN-сервиса.
3. Только после проверки зафиксировать SQL и административно создать `rag.rag_wikijs_pages_v1`. View возвращает только допустимые опубликованные Markdown-страницы на единый момент начала transaction. Draft/unpublished, иной известный формат и будущий/истёкший период исключаются. Fail-closed контракт исключает неизвестные, неоднозначные и неподтверждённые состояния publication/format, включая неподтверждённый период: такие страницы не попадают в view. Намеренная ошибка SELECT не требуется; PostgreSQL functions, triggers или искусственные механизмы генерации ошибок только ради validation не добавляются.
4. Создать отдельную ingestion-роль и выдать только CONNECT к БД, USAGE на schema, SELECT view. Владелец view — другая административная роль; чтение view не требует прямого SELECT внутренних таблиц вызывающим пользователем. Исключить ownership, повышенные атрибуты, membership/PUBLIC grants, TEMP/CREATE и прочие возможности, дающие лишний доступ.
5. Проверить реальные SQL permissions и поведение view, записать безопасный результат и mapping. Административные DDL/grants выполняются отдельно; приложение их никогда не выполняет и не исправляет.

Стабильные aliases контракта (это не имена внутренних колонок Wiki.js):

| Поле view | Контракт |
| --- | --- |
| page_id | положительный уникальный integer, не bool |
| locale, path, title | непустые text |
| markdown | исходный text, пустая строка допустима |
| updated_at | timestamp with time zone |

Все поля обязательны и не допускают NULL. Publication metadata не возвращается: допустимость гарантирует view. Изменения внутренней схемы адаптирует администратор, сохраняя v1 контракт.

## Environment/secrets

Имена должны совпадать в loader, `.env.example`, Compose, tests и этой инструкции:

| Переменная | Значение/правило |
| --- | --- |
| WIKI_DB_HOST | обязательный host PostgreSQL |
| WIKI_DB_PORT | 5432 по умолчанию; 1..65535 |
| WIKI_DB_NAME | обязательная БД Wiki.js |
| WIKI_DB_USER | обязательная отдельная ingestion-роль |
| WIKI_DB_PASSWORD | обязательный секрет, вводится только через environment/secrets |
| WIKI_DB_VIEW | `rag.rag_wikijs_pages_v1` по умолчанию |
| WIKI_DB_TIMEOUT_SECONDS | 30 по умолчанию; integer 1..2147483 |
| WIKI_SOURCE_ORIGIN | обязательный HTTP(S) origin Wiki.js для ссылок |

View — ровно schema.view; каждый компонент соответствует `[a-z_][a-z0-9_]*` и не длиннее 63 ASCII bytes. Origin не содержит credentials, path, query или fragment; trailing slash нормализуется. Адрес БД не используется для web-ссылок. Один timeout задаёт connect timeout в секундах и statement timeout в миллисекундах.

DB credentials хранятся только в защищённом окружении/secret storage и не коммитятся. Пароль не записывается в DSN, документацию, fixtures, CLI arguments, отчёты или логи. Не печатать resolved environment или `docker compose config` с секретами; для проверки структуры использовать `docker compose config --quiet`. Локальный Python не загружает `.env` автоматически. Старые WIKI_BASE_URL/WIKI_TOKEN/WIKI_TIMEOUT_SECONDS для нового ingestion не используются.

## Планируемый запуск

После реализации установить зависимости приложения, включая один PostgreSQL driver, подготовить environment и каталог `data` с правами записи для процесса. Для локального запуска из `app/`:

```text
python -m app.ingestion --output ../data/wiki-documents.json
```

После сборки app image из корня проекта:

```text
docker compose run --rm --no-deps app python -m app.ingestion --output /data/wiki-documents.json
```

Compose должен передавать перечисленные настройки и монтировать `./data:/data`. LLM запускать не требуется. HTTP app не останавливается, поскольку действующий индекс пока не меняется; `/health` независим от настроек и доступности PostgreSQL. Выполнять ручные запуски последовательно.

Runtime выполняет только фиксированный SELECT явных полей из view в read-only transaction и необходимые служебные команды transaction/timeout. Нет произвольного SQL, schema migrations или fallback к таблицам. CLI выводит title/path/length, время запуска, received/saved counts и output path только после успешной записи. Length — Unicode code points. Число исключённых страниц неизвестно роли и не выводится.

При configuration/connection/permission/query timeout/query/invalid row/output error команда возвращает ненулевой код и безопасную категорию, сохраняя старый снимок. Исходные driver exceptions и параметры подключения не выводятся. После устранения причины повторить полный запуск; автоматических retries нет.

## JSON snapshot contract

Объект содержит `schema_version: 1`, `source` (нормализованный WIKI_SOURCE_ORIGIN) и `documents`. Документ содержит page_id, locale, path, title, source_url, updated_at, markdown, content_sha256. Идентичность — `(source, page_id)`; rename не меняет ID. Source URL строится с locale и percent-encoding сегментов path. Updated timestamp нормализуется к ISO 8601 UTC.

Markdown сохраняется дословно, включая пробелы, Unicode, CR/LF, code blocks и таблицы; SHA-256 вычисляется по UTF-8 исходной строки. Изображения/вложения не скачиваются. Null/missing content — ошибка, пустая строка допустима.

Сериализация: UTF-8, ensure_ascii=False, sort_keys=True, indent=2 и финальная LF; документы сортируются по числовому ID. Времени запуска внутри JSON нет. Полный успешный fetch, завершение transaction и validation предшествуют записи temporary file рядом с target и os.replace. Ошибка не публикует частичный snapshot; пустой успешный результат публикует пустой массив. Одинаковые данные дают побайтово одинаковые файлы. Исчезнувшие из view страницы отсутствуют в следующем полном снимке.

## Offline tests после реализации

Из `app/` запускать целевые tests, запланированные change:

```text
python -m pytest tests/test_wiki_client.py tests/test_ingestion.py
```

Также запустить тесты ingestion settings в выбранном при реализации config test module, затем существующие health/llm_check как регрессию. Имена новых config tests зафиксировать здесь при реализации.

Fixtures/mock DB adapter должны покрывать фиксированный SELECT и identifiers, transaction/timeout, сбои connect/execute/fetch/завершения transaction, permission errors, invalid/null/missing/duplicate rows, lossless Markdown, deterministic snapshot и отказы writer/replace. Внешние Wiki.js/PostgreSQL, Docker и модели не нужны. Fixtures используют обезличенные данные без паролей. Mock tests не доказывают корректность административного view или прав роли.

## Live smoke

После задачи 1.1 и административной подготовки:

- Под ingestion-ролью подтвердить реальным SELECT чтение всех aliases view.
- Отдельно от read-only transaction подтвердить запрет SELECT внутренних таблиц, INSERT/UPDATE/DELETE/TRUNCATE и CREATE/ALTER/DROP, включая TEMP и эффективные PUBLIC/member privileges. Проверять на подготовленных администратором одноразовых тестовых объектах, в rollback transactions; не пытаться изменять рабочие Wiki.js объекты. Конкретные команды фиксируются после проверки схемы.
- На контролируемом тестовом источнике проверить draft/unpublished, другие/неизвестные форматы, будущий/истёкший период, точные/открытые границы и некорректные значения. Неизвестные, неоднозначные и неподтверждённые состояния не должны попадать в view; ошибка SELECT для этого не требуется. Отдельно подтвердить понятность mapping publication/format и отсутствие необработанных состояний потенциального корпуса.
- Сверить полный допустимый корпус, исходный Markdown и metadata нескольких страниц с Wiki.js, открыть locale-aware URL, включая русские пути.
- Дважды получить snapshot при неизменных данных и неизменном результате отбора; сравнить байты. Проверить сохранность прежнего файла при отказе.
- Записать версии, дату, mapping, число/объём документов и результаты без секретов и содержимого страниц.

Без фактического PostgreSQL smoke пункты live-задач не отмечаются выполненными. На текущем этапе выполнено только обновление плана; реализация и live-проверки ожидают отдельного запуска apply после review.
