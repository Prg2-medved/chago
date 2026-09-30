# Proposal

## Why

Bootstrap уже запускает FastAPI, но локальная генерация и её ресурсная пригодность ещё не проверены. До реализации RAG нужно запустить выбранную в SPEC.md модель на CPU целевого i5-14400 с 15 ГиБ RAM и записать реальные измерения.

## What Changes

- Добавить llama.cpp server с локальной Qwen3-4B-Instruct-2507 GGUF Q4_K_M, CPU-only, один активный запрос генерации.
- **BREAKING**: обычный Compose-запуск расширяется с одного app до app + llm и требует заранее подготовленного GGUF и образа. Самостоятельный запуск app и его app-only /health сохраняются.
- Монтировать файл модели с хоста read-only, настраивать путь и имя модели без изменения Python-кода. Не скачивать модели автоматически и не хранить их в Git.
- Передавать app адрес LLM через environment; добавить административную CLI-проверку /health llama.cpp и тестового /v1/chat/completions без нового публичного chat API.
- Документировать ручную установку, автономный runtime, смену модели и измерение загрузки, RAM и tokens/sec на одном коротком русском запросе.
- После фактической проверки на целевом сервере записать benchmark; незаполненный шаблон не является выполненной приёмкой.

Исходные требования: SPEC.md §2, §5, §10, §18, §22, §25, §30–31 и application-bootstrap. Начальные параметры: context 8192, threads 8, parallel 1, answer limit 768, temperature 0.2, top_p 0.8, top_k 20. Это ранний LLM benchmark, не итоговый benchmark всего RAG.

Вне scope: E5/embeddings, Wiki.js/GraphQL, SQLite/FTS5, chunking/retrieval, RAG prompt, Web UI, reindex, Swagger, новые provider interfaces и автоматическое скачивание моделей.

## Capabilities

### New Capabilities

- `local-cpu-runtime`: локальная CPU-генерация, диагностика LLM, смена GGUF, offline runtime и проверяемый benchmark целевого сервера.

### Modified Capabilities

- `application-bootstrap`: заменить ограничение одного Compose-сервиса на app + llm, уточнить установку и документацию для двух режимов. Сохранить локальный app-only запуск, health-контракт и автономные pytest.

## Impact

При реализации изменятся compose.yaml, .env.example, README, конфигурация app и тесты; появятся небольшой диагностический Python-модуль и документ benchmark. Существующий .gitignore уже исключает models/ и *.gguf. GGUF не включается в Docker build context app и Git. LLM слушает только внутреннюю Compose-сеть; единственный LAN-порт остаётся у app. SPEC.md и существующий /health не изменяются. Сейчас создаются только planning artifacts.
