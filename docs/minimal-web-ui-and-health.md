# Минимальный Web UI и health

## Запуск и границы

Из `app`, с заранее установленными requirements:

```powershell
../.venv/Scripts/python.exe -m app
```

Открыть `http://127.0.0.1:8000/` (либо настроенные `APP_HOST`/`APP_PORT`).
Для HTTP LAN задать `APP_HOST=0.0.0.0` и открыть адрес машины.
Для подготовленного Compose: `docker compose up -d --no-deps app`; страница
доступна через опубликованный порт app. Отдельный frontend build не нужен:
Dockerfile копирует `app/`, включая `app/static/`.

UI и health запускаются без индекса, embedding assets и LLM. Вопрос при
недоступных зависимостях получает техническую ошибку. Каждый вопрос независим:
API получает только `{session_id,message}`; session ID живёт в памяти страницы,
истории и browser storage нет. Следующая отправка очищает результат, reload —
поле и результат. Ctrl+Enter (или Cmd+Enter) отправляет вопрос, Enter в поле
добавляет новую строку. Во время обработки повторная отправка блокируется.
Автоматического retry и короткого browser deadline нет.

HTML/CSS/JavaScript локальные, без CDN, шрифтов и telemetry. HTTP cache для HTML,
chat и health отключён через `Cache-Control: no-store`. HTML также задаёт CSP:
scripts/styles/connect только same-origin, без inline scripts, embedded assets
и frames. Ссылки на Wiki.js открываются только по действию пользователя.
Это локальное приложение без authentication; этот change не добавляет публичное
развёртывание или административные recovery endpoints.

## Контракт GET /health

HTTP 200 и верхнеуровневый `status=ok` означают liveness приложения.
Это не агрегат readiness, не проверка embeddings и не end-to-end inference.
Probe может занять до пяти секунд; диагностический блок UI загружается
независимо от формы и обновляется вручную, без polling.

Следующий JSON совпадает с assertion `test_health` при отсутствующем индексе
и контролируемом LLM endpoint, возвращающем `{"status":"ok"}`:

```json
{
  "status": "ok",
  "app": {"status": "ok"},
  "index": {
    "status": "missing",
    "available": false,
    "pages": null,
    "chunks": null,
    "indexed_at": null
  },
  "llm": {"status": "ok"},
  "chat": {"status": "available"}
}
```

При подготовленном индексе `index.status=ok`, `available=true`, `pages` и
`chunks` — проверенные document/chunk counts, `indexed_at` — UTC timestamp
последней успешной индексации. Валидный пустой индекс имеет нули и сохранённую
дату. Отсутствующий индекс — `missing`, повреждённый/legacy — `invalid`; у обоих
counts/date равны null. Метаданные берутся из памяти удерживаемого поколения,
без SQLite в event loop, переоткрытия INDEX_PATH, Wiki.js или загрузки encoder.
Замена файла на диске не переключает активное поколение; требуется restart.
Дата не доказывает актуальность относительно текущей Wiki.js.

| Компонент | Значения |
| --- | --- |
| app.status | `ok` |
| index.status | `ok`, `missing`, `invalid` |
| llm.status | `ok`, `unavailable`, `invalid_response`, `timeout`, `configuration_error` |
| chat.status | `available`, `generation_uncertain`, `closed` |

LLM probe делает только GET `/health` настроенного `LLM_BASE_URL`. Допустим
HTTP(S) origin без credentials/query/fragment и непустого path (корневой `/`
допускается). Ошибочная конфигурация не раскрывается в ответе. Только HTTP 200
с JSON object `status=ok` даёт `ok`; HTTP rejection/connection failure —
`unavailable`, redirect/невалидный JSON/envelope/тело свыше 64 KiB —
`invalid_response`, превышение пяти секунд — `timeout`.

Transport работает в отдельном executor с одним worker, без proxy, redirects,
retry, CLI subprocess, token counting и completion. Параллельные клиенты
разделяют один in-flight future; отмена клиента не отменяет transport и не
освобождает возможность поставить второй probe. HTTP ожидание ограничено общим
пятисекундным бюджетом, socket timeout/interrupt ограничивают чтение, shutdown
executor не ждёт удалённую LLM. Системный DNS resolver не исполняется в event
loop; пока его операция не завершена, новые probes не ставятся в очередь.
CLI `python -m app.llm_check health` остаётся отдельной административной командой
со своим прежним exit-code/output контрактом.

`chat=available` означает только отсутствие блокировки генерации. Флаги gate
читаются после probe, generation semaphore не захватывается и не освобождается.
Даже при `llm=ok` значение `generation_uncertain` сохраняется, новые chat requests
получают 503. Восстановление оператором по существующей процедуре: подтвердить
остановку прежней LLM, запустить LLM и затем перезапустить app. Успешный health,
ожидание или один restart app не доказывают завершения старой генерации.

## Проверки Python и HTTP

Команды из `app` (каталог basetemp для повторного запуска должен быть новым):

```powershell
../.venv/Scripts/python.exe -m pytest tests/test_health.py tests/test_web_ui.py tests/test_index_state.py tests/test_active_retrieval.py tests/test_chat_api.py tests/test_chat_concurrency.py tests/test_llm_check.py -q --basetemp=../.tmp/minimal-ui-regression-final
../.venv/Scripts/python.exe -m mypy app/main.py app/health.py
node --check app/static/app.js
node --check tests/browser_ui.mjs
```

Фактически 2026-11-11:

- Первый focused набор health/UI/index/concurrency: **49 passed**, 1 существующее
  предупреждение Starlette о httpx/httpx2. Проверены missing/corrupt/legacy,
  valid-empty, metadata, lazy encoder, content types и доступ из другого cwd,
  64 KiB boundary, timeout, redirects/proxy, совместный probe и отмена клиента,
  ограниченный shutdown, активная и uncertain генерация.
- Расширенный промежуточный набор: 111 passed, 5 failed на старых assertions
  точного health JSON в chat/CLI tests. Assertions обновлены под новый контракт;
  сам CLI transport и chat pipeline не изменялись.
- Итоговый регрессионный набор: **116 passed**, 1 то же предупреждение,
  28.04 s. Включает параллельные HTTP health requests с отменой одного клиента
  и чтением актуального uncertain после probe, прежнюю независимость вопросов,
  validation/errors и отдельный CLI health.
- mypy: **Success: no issues found in 2 source files**. Обе проверки JS syntax
  завершились успешно.
- Дополнительно обновлены два прежних health assertions в
  `test_chat_config.py`/`test_semantic_storage.py`. Проверка
  `../.venv/Scripts/python.exe -m pytest tests/test_chat_config.py tests/test_semantic_storage.py -q --basetemp=../.tmp/minimal-ui-additional`:
  **102 passed**, 1 то же предупреждение, 2.99 s; в том числе запуск без
  numpy/torch/transformers/tokenizers и без валидных chat settings.
- `openspec.cmd validate minimal-web-ui-and-health --strict`: **valid**.

На Windows замена открытого SQLite pathname может быть запрещена ОС:
`test_snapshot_search_after_path_replacement` явно сохраняет это ограничение,
проверяет metadata удерживаемого поколения и загрузку нового после close/restart.
Настоящая замена открытого pathname на POSIX в этом сеансе не проверялась.
Первый sandbox pytest получил WinError 5 на временном каталоге; завершённые
backend runs выполнялись с разрешением вне sandbox.

## Воспроизводимая браузерная матрица

Harness `app/tests/browser_ui.mjs` использует native CDP через установленный
Node >=22 и Chromium, без npm packages. Python test запускает временный HTTP
сервер на LAN IP и отдельный headless browser profile. По умолчанию browser
test пропускается; явный запуск из `app`:

```powershell
$env:RUN_BROWSER_UI = '1'
../.venv/Scripts/python.exe -m pytest tests/test_browser_ui.py -qs --basetemp=../.tmp/minimal-ui-browser-offline-final
Remove-Item Env:RUN_BROWSER_UI
```

`UI_TEST_BROWSER` позволяет выбрать подготовленный executable. На Windows
по умолчанию ищутся Chrome и Edge. Загрузок браузера нет. В test-only CDP Fetch
контролируются `/api/chat` и `/health`, а HTML/CSS/JS обслуживает настоящий app.
В product routes нет test endpoints или switches. Все внешние page requests
блокируются harness; известная инъекция локального антивируса фиксируется
отдельно, прочие внешние запросы считаются ошибкой.
Для повторного запуска использовать новый basetemp. Перед открытием приложения
harness отправляет test-only canary на `https://offline-probe.invalid/` и
проверяет его отклонение через CDP Fetch до сетевой передачи. Та же политика
запрета всех внешних запросов действует во время всей матрицы, LAN origin
приложения разрешён. Системные сеть/proxy/firewall и Kaspersky не меняются.
Глобальный DevTools Offline отключил бы и LAN, поэтому здесь не используется.

Для ручного повторения можно перехватить эти два API endpoint средствами
DevTools/внешнего test harness. Network должен сохранять POST bodies и count;
не менять product API ради подстановки. Проверять следующий порядок:

| Шаг и контролируемый ответ | Ожидаемое поведение | Фактический результат |
| --- | --- | --- |
| Открыть `/`, health с counts/date | Русские labels, отдельная диагностика, UTC | PASS |
| Пустой вопрос, 4097 emoji | Локальная ошибка, 0 POST | PASS |
| Задержать chat; повторить submit/click/Enter | 1 POST, ожидание, disabled; только session_id/message | PASS |
| Ответ `[1] [2]`, 2 sources, многострочный код | Номера и карточки в порядке API; точный whitespace | PASS |
| title/heading/quote с `<script>`/`<img onerror>` | Только текст, без исполнения и подгрузки | PASS |
| Длинный fragment, desktop и viewport 390 px | Перенос без горизонтального overflow | PASS |
| HTTP(S), javascript/data/credential URLs | Только HTTP(S) без credentials кликабельны; noopener noreferrer | PASS |
| Health 503 после ответа | Ответ остаётся, отдельная ошибка health, без chat retry | PASS |
| Следующий вопрос с задержкой | Старый результат сразу удалён, прежний session ID, без истории | PASS |
| insufficient_context, пустые и непустые sources | Результат с обозначением недостатка сведений | PASS |
| Chat 422/502/503/504/500 с секретом в body | Фиксированный русский текст, без raw body; pending завершён | PASS |
| Broken JSON, null, неверный envelope; network failure | Отдельная понятная ошибка, pending завершён, без retry | PASS |
| Health null metadata и uncertain при llm=ok | Нет выдуманных counts/date; предупреждение об операторе | PASS |
| Reload после результата | Пустые поле/результат, нет local/session storage/cookies | PASS |
| Настоящий Ctrl+Enter через CDP Input | Один новый POST и ответ | PASS |
| Внешние запросы приложения отдельно от инъекции Kaspersky | Нет внешних application ресурсов; инъекция заблокирована до transport | PASS: 0 внешних application requests, 2 попытки Kaspersky заблокированы |
| Повтор финального harness с отдельным отчётом об инъекции | Полный успешный итог матрицы | PASS: 1 test, 15 проверок |
| Internet недоступен для вкладки, LAN разрешён | Canary отклонён до transport, вся матрица работает под тем же запретом | PASS: canaryRejected=true, blockedCanaries=1 |
| Физически отключённый интернет на машине | Системный offline runtime | НЕ ПРОВЕРЕНО; системные настройки не менялись |

Среда фактических запусков: Windows 11 build 26200, Chrome **157.0.8103.50**,
Node **24.19.0**, headless. Итоговый разрешённый запуск вне sandbox 2026-11-11:
HTTP `192.168.12.137:57325`, **1 passed in 2.76s**, все **15** проверок PASS,
13 POST за всю матрицу. `secureContext=false`, `crypto.randomUUID` отсутствует:
успешно проверен session-ID fallback для обычного HTTP LAN.

Итоговый network evidence:

```json
{
  "environmentRequests": [
    {"origin": "http://gc.kis.v2.scr.kaspersky-labs.com", "action": "blocked-before-transport"},
    {"origin": "http://gc.kis.v2.scr.kaspersky-labs.com", "action": "blocked-before-transport"}
  ],
  "applicationExternalRequests": [],
  "externalResponses": [],
  "applicationResourcePaths": ["/", "/static/app.css", "/static/app.js", "/health", "/api/chat"],
  "offline": {
    "mode": "browser-target external requests denied; LAN allowed",
    "blockedCanaries": 1,
    "canaryRejected": true
  },
  "browserErrors": []
}
```

Kaspersky пытался внедрить `.../main.js` при первой загрузке и reload; эти две
попытки не считаются запросами приложения и не скрываются в отчёте. Они отклонены
Fetch до передачи в сеть, внешних HTTP responses вкладки нет. CSP сама по себе
не остановила инъекцию окружения. Настройки антивируса не менялись. Пробный
offline canary также относится только к harness, а не к коду приложения.

Итоговый verdict: **PASS для UI без доступа вкладки к интернету при доступном
локальном HTTP сервере и контролируемых API responses**. Это воспроизводимое
подтверждение независимости frontend от интернета без изменения системных
настроек. Оно не доказывает физическое отключение хоста, отсутствие фонового
трафика других процессов/браузерных служб или offline работу настоящего
retrieval/LLM: API в матрице подставлялись через CDP. Реальные успешные ответы LLM
не использовались. Успешные backend-тесты при этом повторно не запускались.

## Compose smoke и оставшаяся приёмка

Операторское evidence от 2026-11-11: пользователь сообщил об обновлении кода
на сервере и передал текст результата UI после инструкции запуска отдельного
smoke app. Ранее его `docker compose ps` показывал работающие `chago-app-1`
(порт `192.168.12.100:8091`) и healthy `chago-llm-1`. Первоначальное сообщение
не включало image ID и browser/version; последующее подтверждение приведено ниже.

В переданном результате видны русский экран, ответ с citations [1]–[4],
четыре source cards страницы «Сервер на объекте» с Wiki.js links и обозначение
недостатка сведений. Health UI показывает app/index/LLM «Работает», отсутствие
блокировки генерации, **24 страницы**, **910 фрагментов**,
`indexed_at=2026-10-20T10:18:41.693Z (UTC)`. Это подтверждает по сообщению
оператора отображение реального результата с источниками и metadata.
Исходный вопрос и raw API/Network evidence отсутствуют; корректность ответа
и source ranges этим сообщением не подтверждена. В частности, фразу об отсутствии
информации о копировании логов нельзя проверить по одному heading источника [4];
в переданном тексте этой карточки не виден содержательный fragment.

После предложенного вопроса «Как настроено системное время на сервере?»
оператор передал второй результат UI: «Не удалось подтвердить ответ по найденным
источникам. Откройте источники ниже», обозначение недостатка сведений и шесть
source cards. Первые три относятся к системному времени; третья содержит
исходный Markdown fragment с `timedatectl`. Остальные относятся к копированию
файлов, сетевой инфраструктуре и cron бекапу PostgreSQL. App/index/LLM остаются
«Работает», генерация не заблокирована, counts/indexed_at прежние.
Зафиксировано отображение неподтверждённого результата с доступными sources.
Точный отправленный вопрос и отсутствие истории в payload отдельно пока
не подтверждены. Очистка старого результата при submit позднее подтверждена оператором.
Причина неподтверждённого ответа и его качество по одному тексту UI не установлены;
наличие `timedatectl` в источниках не подтверждает параметры настройки времени.

После предложенного уточнения «Какой командой проверяют системное время на
сервере?» оператор передал третий результат: «Системное время проверяется
командой: ```bash timedatectl ``` [1]». Показана одна карточка источника из
раздела «8. Настроено системное время» с тем же fragment `timedatectl` и
Wiki.js link. Обозначение недостатка сведений отсутствует. Состояния компонентов,
counts и indexed_at прежние. **Успешный UI ответ с соответствующим показанным
источником подтверждён операторским evidence.** Это проверка конкретного
вопроса, а не общий verdict качества. Мгновенное удаление прежнего результата
при submit позднее подтверждено оператором; raw API payload пока не передан.

В ответ на инструкцию задать вопрос на заведомо отсутствующую в Wiki.js тему
оператор передал четвёртый результат: «В документации недостаточно информации
для ответа на этот вопрос», обозначение недостатка сведений, без source cards.
Health состояния и metadata прежние. **Отображение отказа без источников
подтверждено операторским evidence.** Текст самого вопроса не передан, поэтому
независимо проверить отсутствие темы в корпусе по этому evidence нельзя.
В финальном результате прежние ответ и sources отсутствуют; удаление сразу
при submit позднее отдельно подтверждено оператором.

После инструкции запуска `chago-ui-app-only` на порту 18001 оператор передал
экран с доступной формой и app-only диагностикой: приложение работает,
индекс отсутствует, страницы/фрагменты/indexed_at — «Нет данных», LLM недоступна,
генерация не заблокирована. **Отображение app-only диагностики подтверждено.**
В следующем переданном результате после submit показано: «Сервис временно
недоступен. Проверьте состояние системы или обратитесь к оператору».
App-only диагностика прежняя, ответа и sources нет, текст ожидания отсутствует.
**App-only техническая ошибка в UI подтверждена операторским evidence.**
HTTP status, фактическая доступность кнопки для повторного submit и отсутствие
retry по Network пока отдельно не подтверждены.

После инструкции запуска `chago-ui-llm-unavailable` на порту 18002 с настоящим
индексом и `LLM_BASE_URL=http://127.0.0.1:1` оператор передал результат с тем же
сообщением о временной недоступности сервиса. Диагностика показывает работающие
app/index, 24 страницы, 910 фрагментов, прежний indexed_at, недоступную LLM и
отсутствие блокировки генерации. **Техническая ошибка при валидном индексе и
недоступной LLM подтверждена операторским evidence.** Текста ожидания в результате
нет; HTTP status и отсутствие retry по Network не переданы. Доступность кнопки
после ошибки на странице 18002 позднее подтверждена оператором.

Дополнительное серверное evidence от оператора:

- `docker inspect chago-ui-smoke`: image
  `sha256:e1c3aa13abb701c4fb1a8dc7e2c0731f41b1d547988ba04f0c116bda42ef270e`.
- `docker exec chago-ui-smoke ls -l` подтверждает assets внутри образа/контейнера:
  `/app/app/static/index.html` — 1532 bytes, `app.js` — 7787 bytes,
  `app.css` — 1267 bytes; время в выводе `Nov 11 08:38` (timezone вывода не указан).
- Chrome **157.0.8103.50**, официальная 64-bit сборка.
- Оператор явно подтвердил доступность кнопки после ошибки на странице 18002
  и удаление прежнего ответа сразу при отправке следующего вопроса.
- Скриншот Chrome Network показывает document 200, app.css 200 из memory cache,
  app.js 304 и health 200. Также видны `main.js?attr=...`, `FloatingActionButton.js`,
  `local-storage.js`, другие дополнительные scripts и шрифты Adobe. Полные URL/origins
  в таблице не показаны: происхождение этих запросов нельзя надёжно установить
  по одному имени. В локальной матрице инъекция Kaspersky уже фиксировалась
  отдельно; данный скрин не позволяет автоматически отнести все дополнительные
  requests к приложению или подтвердить отсутствие его внешних requests.
  Строки `/api/chat`, её payload и status на скриншоте нет.
- В следующем сообщении оператор передал payload вопроса «Какие типы очередей
  используются в rabbit?»: ровно `session_id` и `message`, без предыдущих вопросов
  или ответов. **Отсутствие истории в показанном chat payload подтверждено.**
  Значение session ID в отчёт не копируется. Status/count этого запроса не переданы.
- Таблица с Domain содержит 13 XHR к `gc.kis.v2.scr.kaspersky-labs.com`:
  12 `from?get...` и один `wsm.sessionDeactivated`, все HTTP 200,
  initiator `main.js?attr=...:1808`, интервал `2026-11-11T11:20:00.624Z` —
  `11:20:22.717Z`. Это трафик внедрённого Kaspersky script, учитываемый отдельно
  от приложения. В отличие от локального CDP run, в операторской сессии эти
  запросы успешно получали ответы, а не блокировались harness. Настройки
  Kaspersky не изменялись. Данная выборка не содержит строк приложения;
  отсутствие его внешних запросов по ней не подтверждается.

- После исключения Kaspersky оператор передал оставшиеся Network строки с
  Domain: `/static/app.css`, `/static/app.js` и `/health` — HTTP 200,
  `192.168.12.100` (CSS/JS из disk cache). Остальные 14 строк — scripts/fonts
  с идентификатором расширения `efaidnbmnnnibpcajpcglclefindmkaj`, включая
  `FloatingActionButton.js`, `local-storage.js` и AdobeClean fonts. Они учитываются
  как ресурсы расширения браузера, отдельно от app. В показанном traffic
  ресурсы приложения локальные; внешних application requests не выявлено.
  Initiator health указывает на обёртку `main.js?attr=...`; сам endpoint остаётся
  локальным. Настройки расширений и Kaspersky не менялись.

**Итог операторской Ubuntu Compose smoke-проверки: PASS для задачи 3.2.**
Подтверждены образ и assets, успешный ответ с источником, последующие вопросы
с заменой результата и payload без истории, недостаток сведений, оба
app-only/LLM-unavailable UI error сценария, metadata и локальные origins
наблюдаемых ресурсов приложения. Задачи **2.5 и 3.2 выполнены**.

Позднее оператор передал строку `chat`, path `/api/chat`, Domain `192.168.12.100`,
type fetch, status `(pending)`, 0.0 kB. Она подтверждает локальное назначение
chat request. Initiator `main.js?attr=...:4562` относится к наблюдавшейся обёртке
Kaspersky. На момент снимка запрос ещё не завершён. Следующим сообщением
оператор подтвердил его завершение с **HTTP 200**. Длительность и body именно
этого запроса не переданы; pending на промежуточном снимке не был ошибкой.

Ограничения evidence: `/api/chat` payload передан отдельно от Network таблиц;
итоговый HTTP 200 подтверждён сообщением оператора. Полная завершённая Network
строка/count не сохранены. Отсутствие retry и HTTP коды error-сценариев именно
этой серверной сессии отдельно по Network не подтверждены; эти свойства
проверены ранее в локальной browser matrix и backend tests.
Полный HAR и packet capture не собирались. Вывод об origins ограничен
предоставленными запросами, не относится ко всему трафику Ubuntu/рабочей станции
и не означает физического отключения интернета. В операторском браузере
Kaspersky выполнял успешные XHR; локальный CDP run блокировал их до transport.
Сам агент не подключался к серверу: фактические действия и результаты предоставил
оператор. Эти ограничения не подменяют дальнейшую offline-MVP приёмку.

Для воспроизведения в подготовленном окружении собрать app заранее, открыть UI
и повторить success → independent question → insufficient context; отдельно
app-only/LLM-unavailable через тестовые app-контейнеры. Зафиксировать browser/version,
image identity, health JSON, POST payload/count и Network origins без секретов.
Источники должны соответствовать реальному индексу. Локальные fake tests
сами по себе этого не заменяют.
Дополнительные memory/holdout серии не запускались. Весь MVP этим этапом
не объявляется принятым; последующая приёмка — `offline-mvp-acceptance`.

## Подготовленная последовательность команд для Ubuntu

Из корня актуального checkout. Отдельный Compose project `chago-ui-smoke`
использует существующую сеть LLM; production app/llm не пересоздаются.
Данные монтируются read-only, reindex/recovery не запускаются. Пример для
стандартного `./data/index.sqlite3` и embedding path; при других путях
подставить фактические. До вопросов также сверить model/context/token settings
с действующим runtime. Зарезервировать отдельный интервал без production
запросов к общей LLM: независимый smoke app не разделяет её generation gate.

Сборка ниже использует только подготовленные base image и cache layers;
при cache miss остановиться и отдельно подготовить образ. Интернет для сборки
не включать в рамках этой последовательности. Существующие LLM image/flags
и индекс команды не изменяют.

```bash
set -eu
docker compose ps
ui_llm_id="$(docker compose ps -q llm)"
test -n "$ui_llm_id"
export UI_SMOKE_NETWORK="$(docker inspect "$ui_llm_id" | python3 -c 'import json,sys; n=json.load(sys.stdin)[0]["NetworkSettings"]["Networks"]; assert len(n)==1, "Select the LLM network explicitly"; print(next(iter(n)))')"
test -n "$UI_SMOKE_NETWORK"
export UI_SMOKE_DATA="$(realpath ./data)"
test -f "$UI_SMOKE_DATA/index.sqlite3"
docker build --pull=false --network=none -t chago-ui-smoke:local ./app
ui_smoke_dir="$(mktemp -d -t chago-ui-smoke.XXXXXX)"
cat > "$ui_smoke_dir/compose.yaml" <<'YAML'
services:
  ui:
    image: chago-ui-smoke:local
    pull_policy: never
    read_only: true
    ports: ["127.0.0.1:18000:8000"]
    environment:
      APP_HOST: "0.0.0.0"
      INDEX_PATH: /data/index.sqlite3
      EMBEDDING_MODEL_PATH: /data/models/614241f622f53c4eeff9890bdc4f31cfecc418b3
      LLM_BASE_URL: http://llm:8080
      HF_HUB_OFFLINE: "1"
      TRANSFORMERS_OFFLINE: "1"
      PYTHONDONTWRITEBYTECODE: "1"
    volumes:
      - type: bind
        source: ${UI_SMOKE_DATA}
        target: /data
        read_only: true
        bind:
          create_host_path: false
    networks: [existing_llm]
networks:
  existing_llm:
    external: true
    name: ${UI_SMOKE_NETWORK}
YAML
docker compose -p chago-ui-smoke -f "$ui_smoke_dir/compose.yaml" up -d --no-build --no-deps ui
docker image inspect chago-ui-smoke:local --format '{{.Id}}'
curl --fail --max-time 10 -i http://127.0.0.1:18000/health
curl --fail -i http://127.0.0.1:18000/
curl --fail -I http://127.0.0.1:18000/static/app.js
curl --fail -I http://127.0.0.1:18000/static/app.css
```

При необходимости открыть tunnel с рабочей машины:
`ssh -N -L 18000:127.0.0.1:18000 user@ubuntu-host`, затем UI на
`http://127.0.0.1:18000/`. На согласованном интервале выполнить вручную
success с sources → независимый вопрос → insufficient_context; сохранить
browser/version, image ID, health metadata и Network origins/payload/count.
Не начинать вопросы при незавершённой или uncertain генерации общей LLM.

Ошибки проверять отдельными app-контейнерами с недоступным LLM URL,
сохраняя работающую LLM. В первой команде также отсутствует индекс:

```bash
docker compose -p chago-ui-smoke -f "$ui_smoke_dir/compose.yaml" run -d --no-deps \
  --name chago-ui-app-only -p 127.0.0.1:18001:8000 \
  -e INDEX_PATH=/tmp/absent.sqlite3 -e LLM_BASE_URL=http://127.0.0.1:1 ui
docker compose -p chago-ui-smoke -f "$ui_smoke_dir/compose.yaml" run -d --no-deps \
  --name chago-ui-llm-unavailable -p 127.0.0.1:18002:8000 \
  -e LLM_BASE_URL=http://127.0.0.1:1 ui
curl --fail --max-time 10 -i http://127.0.0.1:18001/health
curl --fail --max-time 10 -i http://127.0.0.1:18002/health
# Открыть UI через соответствующий SSH tunnel, проверить понятную 503,
# доступность формы/диагностики и отсутствие retry.
# После проверок убрать только созданные smoke-контейнеры/project:
docker rm -f chago-ui-app-only chago-ui-llm-unavailable
docker compose -p chago-ui-smoke -f "$ui_smoke_dir/compose.yaml" down
```

Health должен показать соответственно missing/unavailable и ok/unavailable.
Readiness к curl может потребовать короткого ожидания старта app. Эта альтернативная
последовательность с отдельным Compose project приведена для воспроизведения;
фактический операторский smoke выше использовал `docker compose run --no-deps`
с именами `chago-ui-smoke`, `chago-ui-app-only`, `chago-ui-llm-unavailable`
и read-only mount существующих данных. Windows fake API matrix и Ubuntu
операторское evidence учитываются отдельно.
