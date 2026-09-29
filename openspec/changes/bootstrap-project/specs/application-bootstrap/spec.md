# Spec Delta

## Purpose

Обеспечить минимальный запускаемый каркас локального HTTP-приложения с проверкой работоспособности, конфигурацией окружения и воспроизводимыми командами разработки и запуска.

## ADDED Requirements

### Requirement: Local application startup
Приложение SHALL запускаться документированной командой из Python-окружения после установки зависимостей, без GPU и без настроенных внешних сервисов.

#### Scenario: Start from installed environment
- **WHEN** разработчик выполняет команду локального запуска из README после установки зависимостей
- **THEN** приложение принимает HTTP-запросы по документированному адресу и порту

### Requirement: Application-only health endpoint
Приложение SHALL отвечать на GET /health кодом HTTP 200 и JSON `{"status":"ok"}`. Ответ SHALL подтверждать только работу приложения, без проверок или статусов индекса, моделей и внешних сервисов и без раскрытия environment variables.

#### Scenario: Health request
- **WHEN** клиент отправляет GET /health работающему приложению
- **THEN** получает HTTP 200, JSON content type и объект `{"status":"ok"}`

### Requirement: Environment configuration
Приложение SHALL поддерживать настройку адреса и порта запуска через `APP_HOST` и `APP_PORT`, со значениями по умолчанию `127.0.0.1` и `8000` для локального запуска. Некорректный порт SHALL приводить к понятной ошибке запуска. `.env.example` SHALL документировать только используемые настройки без secrets; README SHALL объяснять передачу переменных локально и в Compose.

#### Scenario: Defaults without environment file
- **WHEN** приложение запускается локально без APP_HOST, APP_PORT и файла .env
- **THEN** оно слушает 127.0.0.1:8000

#### Scenario: Explicit environment values
- **WHEN** перед запуском заданы APP_HOST=127.0.0.1 и APP_PORT=8010
- **THEN** локальное приложение принимает запрос GET /health по адресу 127.0.0.1:8010

#### Scenario: Invalid port
- **WHEN** APP_PORT содержит нецелое значение или число вне диапазона 1–65535
- **THEN** запуск завершается с ненулевым кодом и сообщением о некорректном APP_PORT

### Requirement: Automated test command
Проект SHALL предоставлять документированную команду pytest, проверяющую health-контракт и конфигурацию без запущенного Docker или внешних сервисов.

#### Scenario: Run tests
- **WHEN** разработчик устанавливает тестовые зависимости и выполняет команду pytest из README
- **THEN** тесты health и конфигурации проходят с кодом завершения 0

### Requirement: Single-service container startup
Проект SHALL предоставлять Dockerfile и compose.yaml ровно с одним сервисом app, публикующим HTTP-порт. После первоначальной сборки `docker compose up` SHALL запускать app без установки пакетов при старте и без дополнительных сервисов, GPU или persistent volumes.

#### Scenario: Start prepared container
- **WHEN** образ предварительно собран и оператор выполняет docker compose up
- **THEN** запускается сервис app и GET /health через опубликованный порт возвращает успешный ответ

### Requirement: Offline runtime
После установки зависимостей или сборки образа приложение SHALL запускаться, перезапускаться и обслуживать /health без доступа в интернет. Скачивание пакетов и образов SHALL ограничиваться установкой или сборкой.

#### Scenario: Offline startup and restart
- **WHEN** интернет недоступен после подготовки окружения или образа, а локальный HTTP-доступ сохранён
- **THEN** приложение успешно запускается, отвечает на /health и сохраняет это поведение после перезапуска

### Requirement: Basic operational documentation
README SHALL содержать требования к Python и Docker Compose, команды установки, локального запуска, проверки /health, pytest, сборки и запуска контейнера, а также описание environment variables и границы установки/runtime.

#### Scenario: Follow bootstrap instructions
- **WHEN** разработчик выполняет последовательность команд README в подготовленной среде
- **THEN** он может запустить приложение локально, выполнить тесты и запустить app через Compose без сведений о будущих RAG-компонентах
