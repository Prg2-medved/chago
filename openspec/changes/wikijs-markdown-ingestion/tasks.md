# Tasks

## 1. Live-контракт и административная подготовка

- [x] 1.1 Первой live-задачей проверить реальную Wiki.js 2.5.307 / PostgreSQL 15.12: структуру нужных таблиц, raw Markdown, editor/format, publication state/period, точные и открытые границы, locale/path/title/id/updated timestamp, возможность stable view и доступа роли только к нему. Зафиксировать проверенный mapping и обезличенные примеры в docs; до проверки не фиксировать DDL view или внутренние имена колонок. Отдельно подтвердить понятность mapping publication/format и отсутствие необработанных состояний потенциального корпуса. Если mapping реальной Wiki.js 2.5.307 нельзя однозначно определить, оставить задачу 1.1 незавершённой и не создавать view. Проверка завершения — реальные read-only SQL результаты и документированный однозначный mapping, не предположения.
- [x] 1.2 Создать versioned PostgreSQL-границу ingestion:
  `rag.rag_wikijs_pages_v1` и отдельную login-роль `chago_rag`.

  Выдать ingestion-роли только необходимые права для чтения ingestion-интерфейса:
  `USAGE` на schema `rag` и `SELECT` на view.

  Проверить, что роль:
  - не является владельцем persistent-объектов;
  - не имеет повышенных атрибутов роли;
  - не имеет прямого доступа к внутренним таблицам Wiki.js;
  - не имеет write/DDL-прав на persistent-объекты Wiki.js и RAG.

  Стандартные PostgreSQL-права, получаемые через `PUBLIC`
  (`CONNECT`, `TEMPORARY`, `USAGE` на schema `public`), не требуется
  глобально отзывать, если они не дают доступ к данным Wiki.js и не позволяют
  изменять данные Wiki.js.

  Проверить доступные роли исполняемые функции и убедиться, что они не создают
  путь для повышения привилегий или изменения данных Wiki.js.

  Документировать:
  - определение view;
  - семантику периода публикации;
  - выданные роли права;
  - влияние унаследованных прав `PUBLIC`.

  Граничные случаи и некорректные значения периода публикации проверять на
  контролируемых тестовых данных без изменения рабочих страниц Wiki.js.

- [x] 1.3 Выполнить реальный SQL smoke test прав от имени `chago_rag`.

  Проверить, что:
  - `SELECT` из `rag.rag_wikijs_pages_v1` разрешён;
  - прямой `SELECT` из внутренних таблиц Wiki.js запрещён;
  - `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`, `CREATE`, `ALTER` и `DROP`
    не позволяют изменять persistent-объекты Wiki.js/RAG;
  - роль не владеет persistent-объектами и не имеет повышенных атрибутов;
  - права, получаемые через `PUBLIC`, и доступные non-system функции
    не позволяют получить доступ к данным Wiki.js или изменить их.

  Право `TEMPORARY` может оставаться доступным, поскольку временные объекты
  существуют только в рамках сессии и не нарушают read-only границу относительно Wiki.js.

  Проверки отказа для потенциально разрушающих операций выполнять только на
  заранее подготовленных тестовых объектах и не изменять рабочие объекты Wiki.js.

  Не отмечать задачу выполненной только на основании mock-тестов.

## 2. Конфигурация и транспорт

- [ ] 2.1 Добавить отдельный ingestion settings loader и `.env.example`: WIKI_DB_HOST/PORT/NAME/USER/PASSWORD/VIEW/TIMEOUT_SECONDS и WIKI_SOURCE_ORIGIN согласно design. Проверка — offline config tests для defaults, обязательных полей, диапазонов, schema.view, origin, secret repr и безопасных ошибок; HTTP settings не требуют этих переменных. В docs синхронизировать имена и правила environment/secrets без значений пароля.
- [ ] 2.2 Добавить один psycopg 3 driver и небольшой `app/app/wiki_client.py`: фиксированный SELECT явных aliases, безопасный Identifier, read-only transaction, конечные connect/statement timeout, полное чтение и закрытие соединения. Проверка — offline mock DB tests подтверждают запрос, отсутствие SQL из ввода/DDL/миграций, timeout и transaction lifecycle; не вводить DB framework.
- [ ] 2.3 Добавить безопасные категории connection/permission/query/timeout/invalid row errors. Проверка — mock failures на connect, execute, fetch после нескольких строк и завершении transaction не дают частичного успеха и не раскрывают credentials/DSN/driver exception; docs перечисляют категории и способ повторить полный запуск.

## 3. Документы и контракт результата

- [ ] 3.1 Реализовать frozen document model и validation полного view result: обязательные поля/типы, NOT NULL, уникальный положительный ID (не bool), UTC updated_at, source URL. Проверка — offline fixtures для invalid/null/missing/duplicate rows, rename, locale и русских путей; любая ошибка прерывает весь запуск. Описать aliases view и поля документа в docs.
- [ ] 3.2 Сохранить lossless Markdown и SHA-256 UTF-8, определить length как Unicode code points. Проверка — fixture round-trip для русского текста, CRLF, пробелов, fenced Bash, таблиц, ссылок, изображений и пустой строки; missing/null content ошибочны, assets не загружаются. Fixtures не содержат secrets или внутренние документы.

## 4. Snapshot и CLI

- [ ] 4.1 Реализовать полный deterministic JSON snapshot, уникальный temporary file рядом с target и os.replace после успешного чтения/завершения transaction/validation. Проверка — файловые offline tests на побайтовую повторяемость при разном порядке строк, удаление исчезнувших страниц, пустой корпус, отказ fetch/validation/write/replace, сохранность старого файла и отсутствие нового target при первом отказе. Обновить JSON contract в docs.
- [ ] 4.2 Добавить CLI `python -m app.ingestion --output <path>` с отчётом title/path/length, временем запуска, received/saved counts и output path только после записи. Проверка — offline CLI tests на exit codes, безопасную диагностику и отсутствие ложных counts исключённых страниц; документировать локальный запуск и последовательные ручные вызовы.
- [ ] 4.3 Передать одинаковые переменные через Compose без обязательной ingestion-валидации при старте app, добавить `./data:/data`; описать подготовку data, environment/secrets, Compose ingestion и offline pytest. Проверка — `docker compose config --quiet` в тестовом окружении и сверка команды с Dockerfile, без печати resolved secrets. README.md и ROADMAP.md не менять.

## 5. Интеграционная проверка

- [ ] 5.1 Запустить целевые config/client/ingestion tests, затем health/llm_check как регрессию общих настроек. Проверка — всё проходит offline без Wiki.js/PostgreSQL, Docker и моделей, `/health` сохраняет контракт без ingestion environment.
- [ ] 5.2 Выполнить live CLI smoke после 1.1–1.3: сравнить исходный Markdown и metadata нескольких страниц, locale-aware URL, полный допустимый корпус и отбор; проверить действующий/будущий/истёкший период, точные/открытые границы и исключение неизвестных, неоднозначных и неподтверждённых состояний из view без требования ошибки SELECT; отдельно подтвердить понятность mapping publication/format и отсутствие необработанных состояний потенциального корпуса. Повторить snapshot при неизменном источнике, сравнить байты, записать версии, объём и результат без secrets/содержимого страниц в docs. Без фактического PostgreSQL smoke оставить задачу незавершённой.
