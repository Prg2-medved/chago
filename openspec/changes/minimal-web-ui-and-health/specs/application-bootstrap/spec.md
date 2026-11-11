# Spec Delta

## MODIFIED Requirements

### Requirement: Application-only health endpoint
Приложение SHALL отвечать на GET /health кодом HTTP 200 и JSON с верхнеуровневым status=ok и диагностическими полями app/index/llm/chat по rag-operational-status. HTTP 200 и status=ok SHALL подтверждать работу приложения независимо от доступности индекса и LLM; результат SHALL NOT раскрываться как готовность всей RAG-цепочки и SHALL NOT содержать environment variables или secrets. App-only запуск SHALL сохраняться без обязательных моделей и сервисов; health SHALL выполнять ограниченную наблюдательную LLM probe без генерации и загрузок.

#### Scenario: Health request
- **WHEN** клиент отправляет GET /health работающему приложению
- **THEN** получает HTTP 200, JSON content type и объект с status=ok и отдельными состояниями компонентов

### Requirement: Single-service container startup
Проект SHALL предоставлять Dockerfile приложения и compose.yaml с сервисами app и llm. Только app SHALL публиковать HTTP-порт на хосте; llm SHALL использовать локальный read-only mount модели. После предварительной сборки/загрузки образов и подготовки GGUF `docker compose up` SHALL запускать оба сервиса без установки пакетов или загрузки моделей при старте, без GPU и дополнительных сервисов. Самостоятельный app SHALL запускаться без готовности LLM и сохранять HTTP 200 и status=ok health при отдельных недоступных состояниях компонентов.

#### Scenario: Start prepared container
- **WHEN** образы и локальный GGUF предварительно подготовлены и оператор выполняет docker compose up
- **THEN** запускаются app и llm, а GET /health приложения через опубликованный порт возвращает успешный ответ

#### Scenario: Bootstrap without running LLM
- **WHEN** app запускается локально или командой docker compose up --no-deps app при остановленном llm
- **THEN** GET /health приложения возвращает HTTP 200 и JSON с status=ok, отдельными состояниями индекса и LLM и ограниченной LLM health probe без генерации

