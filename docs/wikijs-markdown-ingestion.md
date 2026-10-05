# Wiki.js Markdown ingestion

## Статус

Live-проверка Wiki.js 2.5.307 / PostgreSQL 15.12 выполнена 2026-10-01.

Подтверждены фактическая схема Wiki.js, mapping источника, формат Markdown, publication semantics и PostgreSQL permission boundary.

В базе `wiki` административно созданы:

- schema `rag`;
- versioned view `rag.rag_wikijs_pages_v1`;
- отдельная login-роль `chago_rag`.

Роли `chago_rag` явно выданы только:

```text
USAGE ON SCHEMA rag
SELECT ON rag.rag_wikijs_pages_v1
```

Реальным SQL подтверждено:

```text
SELECT rag.rag_wikijs_pages_v1    → разрешён
SELECT public.pages               → permission denied
```

View возвращает 24 ожидаемые публичные опубликованные Markdown-страницы.

Проверены эффективные права через `PUBLIC`, доступные функции `public` и основные варианты publication period. Обнаруженного пути обхода read-only границы Wiki.js нет.

Задачи 1.1–1.3, 4.3 и 5.2 завершены. Фактическое evidence с целевого Linux-сервера
предоставлено пользователем 2026-10-05 и зафиксировано в разделе Live smoke.

---

## PostgreSQL ingestion boundary

Chago не читает внутренние таблицы Wiki.js напрямую.

Путь данных:

```text
public.pages
    ↓
rag.rag_wikijs_pages_v1
    ↓
chago_rag
    ↓
Chago ingestion
```

### Воспроизводимое создание

Административные команды выполняются отдельно от приложения Chago.

Создать ingestion-роль:

```sql
CREATE ROLE chago_rag
    LOGIN
    NOSUPERUSER
    NOCREATEDB
    NOCREATEROLE
    NOREPLICATION
    NOBYPASSRLS;
```

Пароль задаётся отдельно через защищённый административный механизм и не хранится в репозитории, документации или CLI arguments.

Создать schema:

```sql
CREATE SCHEMA rag AUTHORIZATION wikijs;
REVOKE ALL ON SCHEMA rag FROM PUBLIC;
```

Создать view:

```sql
CREATE VIEW rag.rag_wikijs_pages_v1 AS
SELECT
    p.id AS page_id,
    p."localeCode" AS locale,
    p.path AS path,
    p.title AS title,
    p.content AS markdown,
    p."updatedAt" AS updated_at
FROM public.pages AS p
WHERE
    p."contentType" = 'markdown'
    AND p."editorKey" = 'markdown'
    AND p."isPublished" IS TRUE
    AND p."isPrivate" IS FALSE

    AND CASE
        WHEN p."publishStartDate" = '' THEN TRUE
        WHEN p."publishStartDate" ~
            '^[0-9]{4}-(0[1-9]|1[0-2])-([0-2][0-9]|3[01])T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]\.[0-9]{3}\+00:00$'
        THEN p."publishStartDate" <=
            to_char(
                CURRENT_TIMESTAMP AT TIME ZONE 'UTC',
                'YYYY-MM-DD"T"HH24:MI:SS.MS'
            ) || '+00:00'
        ELSE FALSE
    END

    AND CASE
        WHEN p."publishEndDate" = '' THEN TRUE
        WHEN p."publishEndDate" ~
            '^[0-9]{4}-(0[1-9]|1[0-2])-([0-2][0-9]|3[01])T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]\.[0-9]{3}\+00:00$'
        THEN p."publishEndDate" >=
            to_char(
                CURRENT_TIMESTAMP AT TIME ZONE 'UTC',
                'YYYY-MM-DD"T"HH24:MI:SS.MS'
            ) || '+00:00'
        ELSE FALSE
    END;
```

Настроить доступ:

```sql
REVOKE ALL ON rag.rag_wikijs_pages_v1 FROM PUBLIC;

GRANT USAGE ON SCHEMA rag TO chago_rag;
GRANT SELECT ON rag.rag_wikijs_pages_v1 TO chago_rag;
```

Глобальные права `PUBLIC` на database `wiki` и schema `public` не изменяются.

---

## Контракт view

| Поле view | Источник Wiki.js | Контракт |
| --- | --- | --- |
| `page_id` | `pages.id` | положительный уникальный integer |
| `locale` | `pages.localeCode` | непустой text |
| `path` | `pages.path` | непустой text |
| `title` | `pages.title` | непустой text |
| `markdown` | `pages.content` | исходный text; пустая строка допустима |
| `updated_at` | `pages.updatedAt` | непустой ISO 8601 UTC text |

Все поля обязательны и не допускают `NULL`.

`updated_at` сохраняет строковое представление Wiki.js. Parsing и нормализация в ISO 8601 UTC выполняются ingestion-кодом при построении frozen document model.

Publication metadata из view не возвращается: допустимость страницы гарантируется самим view.

### Условия попадания страницы

Страница входит в корпус только если:

```text
contentType = markdown
editorKey   = markdown
isPublished = true
isPrivate   = false
```

и текущий момент входит в разрешённый publication period.

Неизвестные или неподтверждённые состояния исключаются fail-closed.

---

## Проверенный mapping Wiki.js

Источник:

```text
public.pages
```

На момент проверки в таблице находилась 31 страница:

```text
markdown / markdown / published / public — 24
html     / ckeditor / published / public — 7
```

Других состояний потенциального корпуса не обнаружено.

Для всех 24 Markdown-страниц подтверждены:

- уникальный `id`;
- непустые `localeCode`, `path`, `title`, `updatedAt`;
- `content IS NOT NULL`;
- `content` является исходным Markdown.

`updatedAt` хранится как ISO 8601 UTC text с `Z`; все проверенные значения успешно преобразуются PostgreSQL в `timestamptz`.

### Publication period

`publishStartDate` и `publishEndDate` хранятся как строки.

В текущих `pages` и `pageHistory` непустых значений не обнаружено:

```text
publishStartDate = ''
publishEndDate   = ''
```

Исходный код Wiki.js подтверждает:

```text
publishStartDate <= current time
publishEndDate   >= current time
```

Границы включительные, пустая строка означает открытую границу.

GraphQL scalar `Date` использует JavaScript `Date`, UTC и `toISOString()`.

Проверка PostgreSQL-драйвера `pg` показала фактический формат записи:

```text
2026-10-01T12:34:56.789+00:00
```

На контролируемых данных без изменения рабочих страниц проверены:

- открытый период;
- начавшийся период;
- будущий период;
- истёкший период;
- точные start/end boundaries;
- некорректный формат.

Некорректное или неподтверждённое значение исключается из view без ошибки всего `SELECT`.

### Общая аудитория

Системная группа Wiki.js `Guests` имеет `read:pages` и разрешающий `START` page rule от корня без locale restriction.

Все 31 страницы на момент проверки имели:

```text
isPrivate = false
```

PostgreSQL view не наследует Wiki.js Page Rules автоматически, поэтому допустимость общего корпуса должна оставаться административно подтверждённой.

---

## Permission boundary

`chago_rag` не имеет:

```text
SUPERUSER
CREATEDB
CREATEROLE
REPLICATION
BYPASSRLS
```

Роль не является владельцем schema/view и не имеет:

```text
SELECT public.pages
CREATE schema public
CREATE schema rag
```

На `rag.rag_wikijs_pages_v1` у неё только `SELECT`.

Через стандартные PostgreSQL-права `PUBLIC` доступны:

```text
CONNECT database wiki
TEMPORARY
USAGE schema public
```

Эти права не отзываются глобально, поскольку не предоставляют прямого доступа к таблицам Wiki.js или возможности изменять persistent-объекты Wiki.js/RAG.

Проверены также доступные через `public` функции: обнаруженная 31 функция принадлежит расширению `pg_trgm`; ни одна не является `SECURITY DEFINER`.

Итоговая граница:

```text
chago_rag
├── CONNECT database wiki                  разрешено
├── TEMPORARY                              разрешено
├── USAGE schema public                    разрешено
├── SELECT public.pages                    запрещено
├── CREATE schema public                   запрещено
├── CREATE schema rag                      запрещено
├── USAGE schema rag                       разрешено
└── SELECT rag.rag_wikijs_pages_v1         разрешено
```

Приложение Chago не выполняет административный DDL и не пытается исправлять права самостоятельно.

---

## Environment / secrets

| Переменная | Значение |
| --- | --- |
| `WIKI_DB_HOST` | обязательный PostgreSQL host; `db` для целевой Docker-топологии |
| `WIKI_DB_PORT` | integer 1..65535, `5432` по умолчанию |
| `WIKI_DB_NAME` | обязательная БД Wiki.js |
| `WIKI_DB_USER` | отдельная ingestion-роль |
| `WIKI_DB_PASSWORD` | обязательный secret |
| `WIKI_DB_VIEW` | `rag.rag_wikijs_pages_v1` |
| `WIKI_DB_TIMEOUT_SECONDS` | integer 1..2147483, `30` по умолчанию |
| `WIKI_SOURCE_ORIGIN` | HTTP(S) origin Wiki.js |

`WIKI_DB_VIEW` имеет формат `schema.view`; каждый компонент соответствует `[a-z_][a-z0-9_]*` и не длиннее 63 ASCII bytes.

`WIKI_SOURCE_ORIGIN` не содержит credentials, path, query или fragment; trailing slash нормализуется.

DB credentials передаются только через environment/secrets и не записываются в DSN, документацию, fixtures, CLI arguments или логи.

Не выводить resolved environment и `docker compose config` с секретами. Для проверки Compose использовать:

```text
docker compose config --quiet
```

Старые `WIKI_BASE_URL`, `WIKI_TOKEN`, `WIKI_TIMEOUT_SECONDS` новым ingestion не используются.

---

## Docker networks и требования запуска

Wiki.js и PostgreSQL работают в отдельном Compose-проекте. Сеть `wiki_default`
принадлежит этому проекту; PostgreSQL имеет в ней стабильный Docker DNS alias `db`.
Chago подключает только `app` одновременно к двум сетям: своей `default` для связи
с `llm` по `http://llm:8080` и `wiki_default` для PostgreSQL ingestion.
Сервис `llm` остаётся только в default-сети Chago и не получает доступа к Wiki.js network.

В Chago сеть `wiki_default` объявлена с `external: true` и явным именем.
Chago не создаёт эту сеть и не управляет её жизненным циклом: она должна существовать
до запуска Chago, после подготовки отдельного Wiki.js Compose-проекта.
Отсутствие внешней сети препятствует запуску `app`, даже если ingestion не вызывается.

Для ingestion внутри `app` задать `WIKI_DB_HOST=db` и `WIKI_DB_PORT=5432`
через environment/secrets. Docker DNS разрешает alias в актуальный адрес PostgreSQL;
динамический container IP может измениться при пересоздании контейнера и не должен
использоваться в конфигурации. Публиковать PostgreSQL port на host специально для
Chago не требуется. Alias `db` относится к Docker network, а не к локальному Python
процессу на Windows или host Linux.

Сетевая доступность не отменяет PostgreSQL permission boundary: ingestion использует
отдельную роль `chago_rag`, которой разрешён только `SELECT` из
`rag.rag_wikijs_pages_v1`, без прямого доступа к внутренним таблицам Wiki.js.
Реальные credentials остаются только в environment/secrets и не хранятся в репозитории.

После deploy / `git pull` на Linux-сервере из корня Chago проверить актуальный Compose
без вывода resolved secrets, затем пересоздать `app` с подключением к обеим сетям
и проверить разрешение alias из запущенного контейнера:

```sh
docker compose config --quiet
docker compose up -d --build app
docker compose exec -T app python -c 'import socket; socket.getaddrinfo("db", 5432); print("db: DNS OK")'
```

Команды должны завершиться с exit code 0. DNS-проверка не проверяет PostgreSQL
authentication, permissions или CLI ingestion и не закрывает live smoke 5.2.
Эти проверки выполняются реально на целевом Linux-сервере; локальное Windows-окружение
без целевого Docker runtime их не подтверждает.

## Ручной ingestion

Установить зависимости из `app/`:

```text
python -m pip install -r requirements.txt
```

Подготовить каталог `data` в корне проекта (`New-Item -ItemType Directory -Force data`
в PowerShell или `mkdir -p data` в POSIX shell), доступный на запись оператору/контейнеру.
Loader читает переменные окружения текущего процесса; локальный Python не загружает `.env`.
Compose использует `.env` и передаёт те же имена, но HTTP startup не проверяет ingestion settings.
Пароль получить из secret manager в environment без вывода его значения.

Локальный запуск из `app/`:

```text
python -m app.ingestion --output ../data/wiki-documents.json
```

Через Compose:

```text
docker compose build app
docker compose run --rm --no-deps app python -m app.ingestion --output /data/wiki-documents.json
```

Compose передаёт настройки PostgreSQL и монтирует:

```text
./data:/data
```

LLM для ingestion не требуется.

Команда выполняется из корня проекта и подходит для PowerShell и POSIX shell.
Dockerfile задаёт `WORKDIR /app`, копирует Python package в `/app/app` и не имеет
`ENTRYPOINT`: команда `run` заменяет HTTP `CMD` на ingestion CLI.
Все восемь ingestion-переменных передаются через Compose; пустые обязательные
значения разрешены при HTTP startup и проверяются только ingestion loader.

Runtime выполняет только фиксированный `SELECT` явных полей из versioned view в read-only transaction и необходимые transaction/timeout команды.

Нет:

```text
произвольного SQL
schema migrations
fallback к внутренним таблицам Wiki.js
```

Безопасные категории ошибок: `configuration` (с именем переменной), `connection`, `permission`, `query timeout`, `query`, `invalid row`, `output`. CLI возвращает 1; неверный вызов argparse — 2. При ошибке прежний snapshot сохраняется, при первом отказе target не создаётся.

Driver exceptions, credentials и параметры подключения в лог не выводятся.

Автоматических retries нет. После исправления причины повторить ту же команду целиком; ручные запуски выполнять последовательно.

---

## JSON snapshot contract

Snapshot:

```text
schema_version: 1
source
documents
```

Документ:

```text
page_id
locale
path
title
source_url
updated_at
markdown
content_sha256
```

Идентичность документа:

```text
(source, page_id)
```

Переименование страницы не меняет ID.

`source_url` строится с locale и percent-encoding сегментов path.

Markdown сохраняется дословно, включая whitespace, Unicode, CR/LF, code blocks и таблицы.

`content_sha256` вычисляется по UTF-8 исходной строки Markdown.

`updated_at` — ISO 8601 UTC с шестью знаками дробной части и `Z`.
CLI после успешной замены файла выводит title/path/length каждого документа,
UTC-время начала, duration, received/saved counts и output path.
Length — Unicode code points (`len(markdown)`), не bytes и не graphemes.
Время запуска не включается в snapshot. Число исключённых внутренних страниц не выводится.

Изображения и attachments не скачиваются.

`NULL`/missing content — ошибка; пустая строка допустима.

Сериализация:

```text
UTF-8
ensure_ascii=False
sort_keys=True
indent=2
финальная LF
```

Документы сортируются по числовому `page_id`.

Полный fetch, завершение transaction и validation выполняются до записи snapshot.

Запись выполняется через temporary file рядом с target и `os.replace`.
После успешного `os.replace` итоговому файлу выставляются права `0644`, чтобы snapshot был читаем пользователем хоста. При ошибке записи или замены содержимое и права старого snapshot сохраняются; `chmod` не выполняется.

При ошибке частичный snapshot не публикуется. Пустой успешный результат публикует пустой `documents`.

Одинаковые входные данные дают побайтово одинаковый snapshot.

---

## Tests

### Offline

Из `app/`, без Wiki.js/PostgreSQL, Docker и моделей:

```text
python -m pip install -r requirements-dev.txt
python -m pytest tests/test_ingestion_config.py tests/test_wiki_client.py tests/test_ingestion.py
python -m pytest tests/test_config.py tests/test_health.py tests/test_llm_check.py
```

Также выполняются ingestion config tests и существующие health/llm_check regression tests.

Fixtures/mock DB должны покрывать:

- фиксированный `SELECT` и identifiers;
- transaction и timeout;
- connect/execute/fetch/transaction failures;
- permission errors;
- invalid/null/missing/duplicate rows;
- lossless Markdown;
- deterministic snapshot;
- writer/replace failures.

Fixtures используют обезличенные данные без credentials.

Mock tests не доказывают корректность административного view или реальных PostgreSQL permissions.

Проверка реализации 2026-10-01: все 126 offline-тестов config/client/ingestion,
включая запись snapshot и CLI, прошли; 46 regression-тестов config/health/llm_check
прошли. Целевые тесты выполнены вне sandbox после разрешения пользователя:
sandbox блокировал временные каталоги pytest (`WinError 5`). `docker compose config --quiet`
не выполнен: Docker CLI отсутствует. Live CLI smoke не выполнен: необходимые
WIKI_DB_* и WIKI_SOURCE_ORIGIN не заданы в environment текущего процесса.

Повторная проверка 2026-10-02 по задаче 4.3: передача всех восьми переменных,
defaults, mount `./data:/data` и команда запуска сверены с config loader,
HTTP entry point и Dockerfile. Все 126 целевых offline-тестов и 46 regression-тестов
прошли вне sandbox (внутри sandbox временные каталоги pytest блокируются `WinError 5`).
В локальном Windows-окружении Docker CLI отсутствует в PATH и стандартном пути
установки Docker Desktop. По предоставленному пользователем результату на целевом
Linux-сервере выполнены `docker compose config --quiet` и `echo $?`:
Compose завершился с exit code 0 без вывода. Resolved secrets не выводились.
Этот результат относится к прежней версии Compose. По evidence пользователя
от 2026-10-05 актуальный Compose с внешней сетью `wiki_default` проверен на Linux:
`docker compose config --quiet` — exit code 0; `app → db:5432` и `app → llm:8080` —
Docker DNS OK. Задача 4.3 подтверждена. Фактический live smoke 5.2 приведён ниже.

## Live smoke

Для PostgreSQL ingestion boundary выполнены реальные проверки под ролью `chago_rag`.

Подтверждено:

- `SELECT` из `rag.rag_wikijs_pages_v1` разрешён;
- view возвращает 24 ожидаемые публичные опубликованные Markdown-страницы;
- прямой `SELECT` из `public.pages` запрещён;
- `INSERT`, `UPDATE`, `DELETE` и `TRUNCATE` persistent-объекта запрещены;
- `CREATE` в schema `rag` и `public` запрещён;
- `ALTER` и `DROP` чужого persistent-объекта запрещены;
- роль не владеет persistent-объектами или schema;
- роль не состоит в других ролях;
- повышенные атрибуты роли отсутствуют;
- стандартные права `PUBLIC` (`CONNECT`, `TEMPORARY`, `USAGE public`) не дают обнаруженного пути доступа к данным Wiki.js или их изменения;
- доступные через `public` функции относятся к `pg_trgm` и не являются `SECURITY DEFINER`;
- на контролируемых данных проверены открытые, точные, будущие, истёкшие и некорректные значения publication period.

Все потенциально разрушающие проверки выполнялись только на специально созданном одноразовом объекте `rag._chago_permission_smoke`. Рабочие таблицы и страницы Wiki.js не изменялись.

Задачи 1.1, 1.2 и 1.3 завершены.

### Фактический CLI smoke 5.2 на Linux

Результаты предоставлены пользователем 2026-10-05. Smoke фактически выполнен
на целевом Linux-сервере через реальный Wiki.js PostgreSQL после 1.1–1.3;
при фиксации evidence локально не повторялся.

```sh
docker compose run --rm --no-deps app python -m app.ingestion --output /data/wiki-documents.json
```

Первый зафиксированный запуск:

```text
started_at=2026-10-02T13:38:50.633577+00:00
duration_seconds=0.016
received=24
saved=24
output=/data/wiki-documents.json
snapshot_bytes=276756
documents=24
```

При повторном ingestion с неизменным источником SHA-256 полного файла до и после
запуска совпал: snapshot побайтово идентичны. Сам hash полного файла в evidence
не указан.

Прямое сравнение полного `rag.rag_wikijs_pages_v1` со snapshot:
`view_count=24`, `snapshot_count=24`, `errors=0`, `FULL CORPUS MATCH: OK`.
Для всего корпуса сравнивались `page_id`, `locale`, `path`, `title`, `markdown`,
нормализованный `updated_at`, locale-aware `source_url`, `content_sha256`
и длина Markdown в Unicode code points.

Три реальные страницы дополнительно сравнены непосредственно с `public.pages`.
Содержимое, названия и пути здесь не приводятся. Длины source/snapshot и SHA-256
UTF-8 исходного Markdown совпали:

| page_id | Locale | Source/snapshot length | Source/snapshot SHA-256 |
| --- | --- | --- | --- |
| 3 | ru | 1819 | `d4f3e22166fd7927f8d0b1970fe41b23d978bac5fce5d05955b792718f909f56` |
| 4 | ru | 1029 | `94a94d745cefa1e113097b8d4bb76baef476ac9602ef4a64fb1044bfa7ebcd47` |
| 17 | ru | 44912 | `67cffefdd265c6840ae8aa141c2b94e5a54f072e0db89b3736cba8e6a7d73336` |

| page_id | Source updatedAt | Snapshot updated_at |
| --- | --- | --- |
| 3 | `2026-03-05T11:56:15.222Z` | `2026-03-05T11:56:15.222000Z` |
| 4 | `2025-04-09T08:13:00.691Z` | `2025-04-09T08:13:00.691000Z` |
| 17 | `2026-07-17T11:56:12.793Z` | `2026-07-17T11:56:12.793000Z` |

Locale-aware URL корректны для всех трёх страниц: locale `ru` включена,
для страниц 3 и 17 подтверждено percent-encoding русского path.

Live-аудит текущего `public.pages`:

| contentType | editorKey | isPublished | isPrivate | Count |
| --- | --- | --- | --- | --- |
| html | ckeditor | true | false | 7 |
| markdown | markdown | true | false | 24 |

Других комбинаций нет. Locale: `ru=31`. Publication period:
`total_pages=31`, `open_start=31`, `nonempty_start=0`, `open_end=31`,
`nonempty_end=0`. View содержит 24 страницы. Подтверждены однозначный mapping
format/editor/publication, отсутствие дополнительных необработанных состояний
потенциального корпуса и корректный отбор всех 24 Markdown-страниц.

Проверки периода уже реально выполнены в 1.1 на контролируемых данных без изменения
рабочих страниц: открытые границы, действующий период, future start, expired end,
exact start, exact end, malformed period. Malformed и неподтверждённые значения
fail-closed исключаются из view без ошибки `SELECT`. Эти результаты используются
для 5.2; проверки на рабочих страницах не повторялись. Текущий аудит дополнительно
подтверждает отсутствие неизвестных или неоднозначных состояний live-корпуса.

| Runtime | Version |
| --- | --- |
| Wiki.js | 2.5.307 |
| PostgreSQL | 15.12 |
| Docker | 29.3.0 |
| Docker Compose | v5.1.1 |
| Python | 3.12.15 |
| psycopg | 3.3.6 |

Все требования 5.2 подтверждены предоставленным фактическим evidence и ранее
выполненными контролируемыми проверками 1.1. Задача 5.2 завершена.
