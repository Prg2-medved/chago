# Design

## Context

См. `proposal.md` для мотивации. `app/app/main.py` создаёт FastAPI с lifespan, загружает `RetrievalService`, сохраняет его в app.state и создаёт `ChatService`. `/health` сейчас возвращает ровно `{"status":"ok"}`. Это закреплено в application-bootstrap, grounded-chat-api, local-cpu-runtime и точных assertions `test_health.py`, `test_index_state.py`, `test_active_retrieval.py`.

`ActiveIndex.metadata` уже содержит проверенные `indexed_at`, `document_count`, `chunk_count`; процесс удерживает одно поколение до shutdown. SQLite принадлежит retrieval executor; чтение его connection из HTTP handler недопустимо. E5 encoder создаётся лениво на первом поиске. `ChatService.gate` хранит `generation_uncertain` и `closed`; ни успешный health LLM, ни timeout клиента не доказывают завершение upstream generation. Административная `llm_check health` уже использует GET с timeout 5 секунд, но CLI печатает ошибки и не является готовым безопасным HTTP handler. Dockerfile копирует `app/` целиком; зависимостей FastAPI и стандартной библиотеки достаточно.

## Goals / Non-Goals

**Goals:** один небольшой same-origin экран; read-only диагностика активного состояния; сохранение lazy embeddings и app-only startup; минимальное изменение существующего chat pipeline.

**Non-Goals:** frontend framework/build, streaming, Markdown parser/highlighter, постоянная история, follow-up, authentication, публичный reindex/recovery API, новые health-агенты и мониторинг, диагностика PostgreSQL, изменения retrieval/prompt/LLM flags и исправление post-MVP semantic defects. Финальная интеграционная приёмка продукта остаётся `offline-mvp-acceptance`.

## Decisions

### 1. Статические ресурсы внутри Python app

Добавить `app/app/static/index.html`, `app.css`, `app.js`; отдавать `/` и `/static/*` из package-relative path, не зависящего от cwd. Только локальные ресурсы, относительные `/api/chat` и `/health`; браузер не обращается к LLM. Node build и серверные шаблоны здесь не дают необходимой функциональности. Source links открывают исходную Wiki.js только по явному действию пользователя.

Поле имеет видимый label, форма обрабатывает submit, область ожидания/ошибки доступна через aria-live. Тексты и длинные фрагменты переносятся; `white-space: pre-wrap` сохраняет команды и quotes. Ответ показывается как текст: Markdown-rendering потребовал бы parser/sanitizer без необходимости для MVP. Карточки нумеруются по порядку sources; `[n]` в answer остаются читаемыми и не требуют переписывания текста. Ссылки проверяются через URL API: только абсолютные http/https без username/password; отдельная вкладка — с `rel=noopener noreferrer`. Для пользовательских данных использовать DOM textContent, не innerHTML.

### 2. Один текущий запрос без истории

State содержит только текущий pending/result/error. Session ID создаётся в памяти страницы, например browser crypto с fallback для HTTP LAN, и отправляется в пределах ограничения 128 code points; его не нужно сохранять в storage. На submit удалить старый результат и ошибку, сохранить текущий вопрос в поле и заблокировать отправку до finally. Payload — строго `{session_id, message}`. Повторные клики/Enter во время pending игнорируются. Backend уже игнорирует session_id для контекста; менять это поведение не требуется.

Пустой вопрос отклоняется локально. Ограничение 4096 Unicode code points проверяется без молчаливого сокращения; сервер остаётся источником token validation. Browser fetch не получает короткого искусственного deadline: ожидание application queue плюс generation может занять минуты. Ошибка сети или ухода со страницы не вызывает retry и не объявляется остановкой генерации. Автоматического восстановления вопроса/ответа после reload нет; форму настроить без autocomplete восстановления истории.

Результат HTTP 200 проверяется на ожидаемую структуру до отрисовки. `insufficient_context=true` показывает отдельное обозначение, сохраняя answer и доступные sources. Коды 422/502/503/504 переводятся в фиксированные безопасные русские сообщения; неизвестные ошибки, network failure и malformed response получают свои сообщения. Raw response body и upstream exception не отображаются. После ошибки пользователь может отправить вопрос явно; автоматических повторов нет.

### 3. Расширить именно `/health`

SPEC §20 требует сведения компонентов на `/health`. Дополнительный `/status` сохранил бы точное старое JSON, но не выполнил бы этот контракт. Оставить HTTP 200 и верхнеуровневый status=ok для liveness, добавить диагностические объекты. Не вводить агрегат `ready`: успешная проверка llama.cpp и наличие индекса не подтверждают lazy embedding assets или end-to-end inference.

Пример при подготовленном индексе и неблокированном chat:

```json
{
  "status": "ok",
  "app": {"status": "ok"},
  "index": {
    "status": "ok",
    "available": true,
    "pages": 20,
    "chunks": 123,
    "indexed_at": "2026-11-11T08:00:00Z"
  },
  "llm": {"status": "ok"},
  "chat": {"status": "available"}
}
```

Числа/дата здесь иллюстративны, не evidence. При missing/invalid index counts и дата равны null; валидный пустой индекс — ok с нулями. Формировать immutable metadata snapshot из уже загруженного IndexState без SQLite queries, чтения файла по INDEX_PATH или нового encoder. `index_missing` отображается в missing; прочие невалидные состояния — invalid. `chat.status=available` означает только отсутствие generation_uncertain/closed; UI подписывает это как состояние блокировки генерации, а не «вся система готова». Ошибка embeddings по-прежнему выявляется chat и даёт безопасную 503, health не обещает её обнаружение.

Старые ограничения «только app, никаких проверок» явно заменяются delta specs трёх затронутых capabilities. Заголовок существующего requirement Application-only health endpoint сохраняется для корректного merge. Исторические reports и архивированные changes не переписываются.

### 4. Ограниченная LLM probe вне generation pipeline

Добавить небольшой `app/app/health.py` с безопасной типизированной диагностикой и lifespan-owned probe coordinator. Использовать origin из существующих настроек LLM, но не требовать chat/embedding settings для app-only health. Origin валидировать как HTTP(S) origin без credentials/path/query/fragment; invalid config возвращает configuration_error, не исходное значение.

Выполнять GET только `/health`, без redirects и proxy, с лимитом body 64 KiB и timeout 5 секунд. Блокирующий стандартный HTTP transport запускать в выделенном executor с одним worker, отдельно от retrieval и generation. Одновременные запросы разделяют одну in-flight task; отмена отдельного клиента не отменяет общую probe и не порождает новую до завершения transport. Socket operations ограничены timeout, чтение body также соблюдает конечный бюджет; cleanup executor не ждёт удалённую LLM бессрочно. Не использовать неограниченную очередь executor submissions или detached retries.

HTTP 200 плюс JSON object status=ok даёт ok; connection/HTTP errors включая загрузочный 503 — unavailable, timeout — timeout, malformed/oversize body или status не ok — invalid_response, неверный origin — configuration_error. Redirect не выполнять и отображать как invalid_response. Не выполнять token counting или completion, не запускать CLI subprocess. Административную health команду оставить отдельной; общий transport helper допустим только при необходимости и без изменения её CLI поведения.

После probe считывать текущие flags gate для ответа health. Не брать и не освобождать generation semaphore. При llm=ok и generation_uncertain показывать оба факта; recovery остаётся подтверждённой остановкой прежней LLM → запуск LLM → restart app. Добавить `Cache-Control: no-store` к health и chat response, а также HTML, чтобы приложение не сохраняло результаты через HTTP cache.

### 5. Диагностика на экране без polling

Вызывать health при загрузке страницы и по кнопке «Обновить состояние»; для health использовать отдельный pending флаг. Бесконечный polling не нужен для 2–5 пользователей. Health отображается отдельно от chat и не блокирует отправку вопроса по старому snapshot проверки. Дату показывать с явным часовым поясом (допустимо UTC), counts — только при наличии данных. Ошибка health обновляет только диагностический блок. Показывать, что health не проверяет embeddings и не подтверждает качество ответа. Для generation_uncertain показывать необходимость восстановления оператором без кнопки restart/recovery.

## Risks / Trade-offs

- [Exact JSON compatibility] → обновить точные assertions и документировать расширение; HTTP 200/status=ok сохраняются, но не трактуются как RAG readiness.
- [Probe adds up to 5 seconds to health] → отдельный executor, совместная in-flight probe, отсутствие polling и независимость от generation slot. Не использовать endpoint как доказательство завершения генерации.
- [Lazy embeddings can fail after all shown checks pass] → не вводить общий ready и явно ограничить смысл component statuses; техническая ошибка chat остаётся видимой.
- [HTML/script или опасная ссылка в документации] → только textContent и проверка source URL без Markdown execution/embedded assets.
- [Page closes during request] → сохранить существующий cancellation-safe gate; никаких автоматических повторов, короткого browser timeout или утверждений об остановке LLM.
- [Файл индекса заменён на диске] → health использует metadata удерживаемого поколения; показ времени не считается автоматической freshness-проверкой.

## Migration Plan

1. После review artifacts применить изменения модулей, static assets и относящихся к ним проверок; схему SQLite и `/api/chat` payload не менять.
2. Выполнить targeted pytest для health, index state, active retrieval, chat API/concurrency; проверить браузерные сценарии отдельной процедурой без добавления frontend toolchain.
3. Собрать app из заранее подготовленных зависимостей, проверить включение static assets. На целевом локальном окружении подтвердить UI, источники, app-only errors, metadata и отсутствие внешних runtime requests; сохранить фактический smoke evidence в `docs/minimal-web-ui-and-health.md` без объявления полного MVP pass.
4. Rollback — вернуть app code/image и прежний `/health` JSON; SQLite, модель и runtime settings не мигрируются. Если есть generation_uncertain, соблюдать существующую recovery процедуру; один restart app не считать достаточным.
