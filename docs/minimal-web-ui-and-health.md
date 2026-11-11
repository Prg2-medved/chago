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

**НЕ ПРОВЕРЕНО:** подготовленный app image, включение static assets в собранный
образ, реальный успешный UI вопрос с sources, следующий независимый вопрос,
реальный отказ и LLM-unavailable в целевом Compose окружении, его metadata и
отсутствие внешних runtime requests. Docker недоступен в PATH текущей среды;
целевое окружение для этого запуска не предоставлено. Задача 3.2 остаётся открытой.
Задача **2.5 выполнена** по итоговому browser run и описанной выше offline
проверке вкладки. Задача **3.2 открыта до реальной Compose-проверки на Ubuntu**.

В подготовленном окружении собрать app заранее, открыть UI в браузере и повторить
сценарии success → independent question → insufficient context; отдельно
app-only/остановленная LLM. Зафиксировать browser/version, image identity,
health JSON, POST payload/count и Network origins без секретов. Источники должны
соответствовать реальному индексу. Локальные fake tests этого не заменяют.
Дополнительные memory/holdout серии не запускались. Весь MVP этим этапом
не объявляется принятым; последующая приёмка — `offline-mvp-acceptance`.

## Серверные команды для Ubuntu (ещё не выполнялись)

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
Readiness к curl может потребовать короткого ожидания старта app. Эта процедура
ещё не выполнялась: задача 3.2 остаётся открытой; Windows fake API matrix
не заменяет Ubuntu Compose evidence.
