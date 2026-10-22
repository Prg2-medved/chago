# Proposal

> Review draft, 2026-10-22: пересмотр критериев по решению владельца о переносе
> семантического качества генерации в post-MVP. Реализация продолжится только
> после согласования обновлённых SPEC и planning artifacts.

## Why

В Chago реализован минимальный read-only поток «POST /api/chat → hybrid retrieval → исходный контекст → локальная Qwen → backend validation → answer/sources». Prompt, LLM client, точный token counter, packing и generation gate реализованы; задачи 1.1–7.1 проверены. Оставшаяся работа этапа — live-приёмка стабильности и безопасности в существующей архитектуре, с явным учётом непройденной семантической приёмки.

## What Changes

- Сохранить реализованный `POST /api/chat` с `session_id`, `message` и ответом `answer`, `insufficient_context`, `sources`. На этом этапе запросы независимы; история и follow-up относятся к следующему change.
- Использовать существующий hybrid retrieval по одному активному SQLite snapshot, конфигурируемый top-k и локальную E5 без изменения ranking, corpus и baseline.
- Сохранить реализованные строгий русский prompt, недоверенную секцию CONTEXT с chunk IDs, точный LLM token budget и локальный вызов Qwen через llama.cpp.
- Формировать source metadata, ссылки, номера цитат и дословные fragments на backend; проверять IDs и fenced code blocks, безопасно отклонять неподтверждённую генерацию без повторного LLM-вызова.
- Поддержать полный отказ, частичный ответ, короткое уточнение и показ противоречащих источников.
- Сохранить сериализацию генерации application semaphore при одном FastAPI worker, реализованные технические HTTP-ошибки и безопасные timings; завершить оставшиеся проверки на реальной модели.
- Сохранить app-only startup и текущий `/health`; Web UI, расширенный health, session history, retrieval tuning и reindex API не входят в этап.
- Приоритет оставшейся приёмки: диагностика global OOM и стабильность LLM, memory series последовательных запросов, Compose concurrency/cancellation/timeout/generation_uncertain, ручной recovery, offline/app-only/isolation/SQLite, затем итоговая live-приёмка MVP. Текущая архитектура и закреплённый runtime сохраняются.
- Перенести полноту фактов, семантический выбор kind и entailment citations в явно открытые post-MVP цели SPEC §27. Правила prompt, validators, fail-closed, exact commands, unanswerable/conflict/injection safety и read-only остаются обязательными. Эксперимент `parts` не реализуется; внутренний формат остаётся `{kind, answer}`.
- Разделять stability, safety и semantic quality verdicts. Известные q13 (неоднозначный объект) и q18 (противоречие) потенциально блокируют safety: их нельзя автоматически отнести к неблокирующему качеству. Раскрытый holdout не используется для настройки; прежние failures сохраняются.

## Capabilities

### New Capabilities

- `grounded-chat-api`: stateless RAG HTTP API, bounded context, локальная генерация, backend citations/code validation, отказ и runtime isolation.

### Modified Capabilities

Нет. Существующие retrieval/storage/runtime contracts сохраняются; новые HTTP orchestration requirements оформляются отдельной capability.

## Impact

Реализованы route/service, lifecycle/index integration, chat/prompt/LLM client и профильные tests. Настройки уже передаются через `.env.example` и `compose.yaml`; примеры API и серверная процедура описаны в `docs/grounded-chat-api.md` и acceptance docs. Текущий пересмотр затрагивает только SPEC и planning artifacts; дополнительных сервисов и зависимостей нет. `README.md`, `ROADMAP.md`, frozen evaluation inputs и исторические отчёты не изменяются. Действующий SPEC.md определяет acceptance: Hit@5 ≥90% относится к post-MVP; известное расхождение с прежним hybrid spec раскрыто в design.

Пересмотр planning не меняет код, модель/image, runtime flags, sampling, timeout,
retrieval ranking, prompt/messages и frozen evaluation inputs. Прежняя 7.2 не пройдена:
старые fail verdicts сохраняются с исходными критериями. Stability, safety и semantic
quality verdicts публикуются отдельно; MVP требует pass первых двух. Завершение технической приёмки не означает исправления
семантических дефектов. Результаты уже выполненных проверок не переписываются.
