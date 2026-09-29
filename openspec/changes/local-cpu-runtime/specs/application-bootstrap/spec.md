# Spec Delta

## MODIFIED Requirements

### Requirement: Single-service container startup
Проект SHALL предоставлять Dockerfile приложения и compose.yaml с сервисами app и llm. Только app SHALL публиковать HTTP-порт на хосте; llm SHALL использовать локальный read-only mount модели. После предварительной сборки/загрузки образов и подготовки GGUF `docker compose up` SHALL запускать оба сервиса без установки пакетов или загрузки моделей при старте, без GPU и дополнительных сервисов. Самостоятельный app SHALL запускаться без готовности LLM и сохранять существующий health-контракт.

#### Scenario: Start prepared container
- **WHEN** образы и локальный GGUF предварительно подготовлены и оператор выполняет docker compose up
- **THEN** запускаются app и llm, а GET /health приложения через опубликованный порт возвращает успешный ответ

#### Scenario: Bootstrap without running LLM
- **WHEN** app запускается локально или командой docker compose up --no-deps app при остановленном llm
- **THEN** GET /health приложения возвращает HTTP 200 и JSON `{"status":"ok"}` без проверки LLM

### Requirement: Offline runtime
После установки зависимостей или подготовки образов и локального GGUF приложение SHALL запускаться, перезапускаться и обслуживать /health без доступа в интернет. Загрузка пакетов, образов и модели SHALL ограничиваться установкой; модель устанавливается оператором без автоматического скачивания runtime. Самостоятельный app-only запуск SHALL не требовать GGUF.

#### Scenario: Offline startup and restart
- **WHEN** интернет недоступен после подготовки окружения или образов и GGUF, а локальный HTTP-доступ сохранён
- **THEN** приложение успешно запускается, отвечает на /health и сохраняет это поведение после перезапуска

### Requirement: Basic operational documentation
README SHALL содержать требования к Python и Docker Compose, команды установки, локального запуска, проверки /health, pytest, сборки и запуска контейнеров, а также описание environment variables и границы установки/runtime. Документация SHALL отдельно описывать app-only запуск без LLM и полный Compose-запуск с ручной установкой модели, LLM health, тестовой генерацией, сменой GGUF и benchmark.

#### Scenario: Follow bootstrap instructions
- **WHEN** разработчик выполняет последовательность команд README для app-only режима в подготовленной среде
- **THEN** он может запустить приложение локально, выполнить тесты и запустить только app через Compose без модели и сведений о будущих RAG-компонентах

#### Scenario: Follow LLM runtime instructions
- **WHEN** оператор выполняет документированную установку модели и полный Compose-запуск
- **THEN** он может проверить LLM health и генерацию и выполнить процедуру benchmark без добавления RAG-компонентов
