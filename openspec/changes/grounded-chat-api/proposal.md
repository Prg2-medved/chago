# Proposal

## Why

В Chago уже есть локальный CPU runtime Qwen, hybrid retrieval и атомарно публикуемый SQLite-индекс, но нет пользовательского API генерации. Этап 10 ROADMAP.md соединяет их в минимальный read-only поток «вопрос → retrieval → контекст → локальная LLM → grounded answer → sources/citations» с отказом при недостатке evidence.

## What Changes

- Добавить `POST /api/chat` с `session_id`, `message` и ответом `answer`, `insufficient_context`, `sources`. На этом этапе запросы независимы; история и follow-up относятся к следующему change.
- Использовать существующий hybrid retrieval по одному активному SQLite snapshot, конфигурируемый top-k и локальную E5 без изменения ranking, corpus и baseline.
- Добавить строгий русский prompt, недоверенную секцию CONTEXT с chunk IDs, точный LLM token budget и локальный вызов Qwen через llama.cpp.
- Формировать source metadata, ссылки, номера цитат и дословные fragments на backend; проверять IDs и fenced code blocks, безопасно отклонять неподтверждённую генерацию без повторного LLM-вызова.
- Поддержать полный отказ, частичный ответ, короткое уточнение и показ противоречащих источников.
- Сериализовать генерацию application semaphore при одном FastAPI worker; добавить отдельные технические HTTP-ошибки, безопасные timings и проверки на реальной модели.
- Сохранить app-only startup и текущий `/health`; Web UI, расширенный health, session history, retrieval tuning и reindex API не входят в этап.

## Capabilities

### New Capabilities

- `grounded-chat-api`: stateless RAG HTTP API, bounded context, локальная генерация, backend citations/code validation, отказ и runtime isolation.

### Modified Capabilities

Нет. Существующие retrieval/storage/runtime contracts сохраняются; новые HTTP orchestration requirements оформляются отдельной capability.

## Impact

Реализация затронет `app/app/main.py`, lifecycle/index integration в `index_state.py` и `hybrid_retrieval.py`, настройки в `config.py`, новые небольшие модули chat/prompt/LLM client и профильные тесты. Настройки передаются через `.env.example` и `compose.yaml`; дополнительные сервисы и зависимости не планируются. Примеры API и процедура серверной проверки будут в `docs/grounded-chat-api.md`, результаты — в отдельном отчёте. `README.md`, `ROADMAP.md`, frozen evaluation inputs и исторические отчёты не изменяются. Действующий SPEC.md определяет acceptance: Hit@5 ≥90% относится к post-MVP и не блокирует этот этап; известное расхождение с прежним hybrid spec раскрыто в design.
