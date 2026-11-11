# Proposal

## Why

Grounded RAG уже доступен через API, но пользователю нужен простой локальный экран, а оператору — диагностика индекса и LLM. Этот этап реализует следующий MVP brief из ROADMAP и требования SPEC §7.1, §18–20 без добавления диалоговой истории.

## What Changes

- Русский экран одного вопроса по `/`: поле, отправка, ожидание, ответ и пронумерованные source cards с title, heading, дословным fragment и ссылкой на Wiki.js.
- Следующий вопрос заменяет предыдущий результат; `/api/chat` и обязательный `session_id` сохраняются, история не хранится и не передаётся backend, retrieval или LLM.
- Статические HTML/CSS/JavaScript обслуживаются FastAPI без отдельной сборки frontend, CDN и runtime-запросов в интернет.
- `/health` расширяется состоянием активного индекса, pages/chunks, временем последней успешной индексации, проверкой llama.cpp и состоянием блокировки chat. Экран показывает диагностические сведения и безопасные понятные ошибки.
- **BREAKING**: точное тело `/health` больше не равно только `{"status":"ok"}`; HTTP 200 и верхнеуровневый `status=ok` продолжают означать работающее приложение даже при недоступных зависимостях. Проверки точного равенства JSON необходимо обновить.
- Health не генерирует ответы, не загружает embedding-модель и не снимает `generation_uncertain`; приёмка UI не подменяет последующий `offline-mvp-acceptance`.

## Capabilities

### New Capabilities

- `minimal-web-ui`: локальный экран независимого вопроса, sources, ожидания и ошибок с безопасным отображением данных.
- `rag-operational-status`: диагностические поля health, проверка LLM, метаданные удерживаемого поколения и состояние chat без изменения runtime.

### Modified Capabilities

- `application-bootstrap`: расширение app-only health JSON при сохранении app-only запуска, HTTP 200 и offline runtime.
- `grounded-chat-api`: замена прежнего ограничения app-only health в требовании технических ошибок; контракт chat, коды ошибок и логирование сохраняются.
- `local-cpu-runtime`: согласование отдельной административной LLM health команды с расширенным HTTP health приложения.

## Impact

Изменения реализации планируются в `app/app/main.py`, новом health-модуле, статических ресурсах внутри `app/app/` и тестах health/UI/API. Метаданные уже доступны в `ActiveIndex.metadata`; используются существующие `RetrievalService` и `ChatService.gate`. Dockerfile уже копирует весь `app/`; дополнительные сервисы, Node, Python-зависимости и изменения LLM flags не нужны. Инструкции эксплуатации и фактический smoke report добавляются в отдельный документ `docs/minimal-web-ui-and-health.md`; README, ROADMAP, frozen corpus и исторические evidence не изменяются.
