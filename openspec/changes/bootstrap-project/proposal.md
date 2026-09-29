# Proposal

## Why

В проекте есть верхнеуровневый SPEC.md, но пока нет приложения, тестов и способа запуска. Нужен минимальный проверяемый Python-каркас для последующей реализации локальной RAG-системы без преждевременных интеграций.

## What Changes

- Создать минимальную структуру Python-проекта с FastAPI и запуском одним процессом.
- Добавить GET /health, возвращающий HTTP 200 и JSON `{"status":"ok"}` исключительно как подтверждение работы приложения.
- Настроить запуск через environment variables с документированными значениями по умолчанию и `.env.example`.
- Добавить pytest и проверки health/configuration.
- Добавить Dockerfile и корневой compose.yaml ровно с одним сервисом app.
- Написать базовый README с установкой, локальным запуском, тестами и запуском Compose.
- Обеспечить запуск и работу без интернета после установки зависимостей или сборки образа.

Это ограниченный подготовительный этап SPEC.md (§5, §18–22, §30–31). Полный /health с index/LLM и второй сервис llm остаются требованиями будущих changes; этот change не объявляет весь MVP реализованным.

Не входят: Wiki.js, GraphQL, llama.cpp, Qwen, embeddings, SQLite, FTS5, chunking, retrieval, RAG, Web UI и reindex. Не создавать заглушки, настройки, каталоги или абстракции для этих функций заранее.

## Capabilities

### New Capabilities

- `application-bootstrap`: запуск минимального FastAPI-приложения локально и через Compose, environment configuration, app-only health, pytest и автономная работа после установки.

### Modified Capabilities

Нет: существующих OpenSpec capabilities пока нет.

## Impact

При реализации появятся Python-пакет приложения, зависимости и тесты, Dockerfile, compose.yaml, .env.example и README. Runtime-зависимости ограничены HTTP-приложением и его сервером; pytest и HTTP test client нужны для разработки. Существующие сервисы Wiki.js и верхнеуровневый SPEC.md не изменяются. GPU, модели, хранилища и внешние сервисы не требуются. Сейчас создаются только OpenSpec artifacts.
