# Design

## Context

См. proposal.md для мотивации. Сейчас compose.yaml содержит только app; app/app/config.py читает APP_HOST/APP_PORT, main.py реализует app-only /health, __main__.py запускает один Uvicorn worker. Pytest проверяет этот контракт без внешних сервисов. .gitignore уже исключает models/ и *.gguf. Основной application-bootstrap spec требует один Compose-сервис, поэтому изменение этого контракта включено в delta явно.

Целевой сервер: i5-14400, 15 ГиБ RAM, около 9.7 ГиБ доступно на момент SPEC.md, существующая Wiki.js делит ресурсы с RAG. Наличие свободной памяти нужно измерить заново. Результаты прежнего bootstrap содержат оговорку о непроверенных Docker/offline-критериях; архивирование не заменяет новые реальные проверки.

## Goals / Non-Goals

**Goals:** два простых сервиса, локальный заменяемый GGUF, диагностика из app, воспроизводимый ранний benchmark. Новая внешняя runtime-зависимость и измерение ресурсов требуют этого design.

**Non-Goals:** пользовательский chat endpoint, библиотека providers, RAG prompt, embedding runtime, очередь отдельным сервисом, мониторинговая платформа, новые UI/Swagger, downloader. Полный scope приведён в proposal.md.

## Decisions

### 1. Один CPU llama-server во внутренней сети

Использовать официальный CPU server image `ghcr.io/ggml-org/llama.cpp:server`; при реализации выбрать проверенную сборку и закрепить её digest, записав версию. Не использовать floating tag как окончательный результат. GPU/CUDA-варианты, device mounts и GPU reservations не нужны. Начальные аргументы: локальный `--model`, host 0.0.0.0, port 8080, context 8192, threads и threads-batch 8, parallel 1, gpu-layers 0, device none, no-webui. Проверить поддержку аргументов через --help именно закреплённого образа. Источники: [официальные Docker images](https://github.com/ggml-org/llama.cpp/blob/master/docs/docker.md), [server reference](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md).

App не зависит от готовности llm при старте и не вызывает его из собственного /health. LLM не публикует host port. По умолчанию Compose стартует оба сервиса; `docker compose up --no-deps app` и локальный `python -m app` сохраняют bootstrap-режим. Альтернатива с readiness-gate для app сломала бы независимый health.

### 2. Однозначные пути и environment variables

| Настройка | Начальное значение / смысл |
|---|---|
| LLM_IMAGE | Проверенный CPU server image с digest; точное значение фиксируется после проверки образа |
| LLM_MODEL_PATH | Путь на хосте; default `./models/Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf` относительно корня Compose |
| LLM_MODEL_NAME | `Qwen3-4B-Instruct-2507`; передаётся llama-server через `--alias ${LLM_MODEL_NAME}` и используется как поле `model` запросов `/v1/chat/completions` |
| LLM_BASE_URL | `http://llm:8080`, без `/v1`; передаётся окружению app |
| LLM_CONTEXT_SIZE | 8192, аргумент llm |
| LLM_THREADS | 8, generation и prompt processing threads |
| LLM_MAX_TOKENS | 768, ограничение тестовой генерации |

Монтировать один host-файл в постоянный контейнерный путь `/models/model.gguf` read-only через long bind syntax с отключённым созданием отсутствующего host path. Так отсутствие GGUF не создаёт каталог, а смена host path не затрагивает Python. Полный путь по умолчанию позволяет Compose интерполировать конфигурацию app-only без обязательного наличия модели; сам mount нужен только llm. Не использовать model URL, Hugging Face auto-fetch, router mode или runtime pull. Подготовка образа — отдельный шаг установки, для runtime задать запрет pull. Локальный файл скачивает/копирует оператор вручную; README указывает [выбранный репозиторий GGUF](https://huggingface.co/bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF), точное имя файла, revision и checksum установленного артефакта.

Замена: подготовить совместимый GGUF, изменить LLM_MODEL_PATH и при необходимости LLM_MODEL_NAME, пересоздать llm, повторить health/smoke. Если меняется имя/URL в окружении app, пересоздать и app. Поддержка новой архитектуры GGUF ограничена закреплённым llama.cpp; произвольная модель не обещается. Для проверки пути достаточно копии того же GGUF под другим именем, без скачивания второй большой модели.

Значение `LLM_MODEL_NAME` должно совпадать в аргументе `--alias` llama-server и поле `model` completion-запроса app; имя файла GGUF не подставляется вместо alias. После запуска проверить, что GET `/v1/models` содержит заданный alias в `data[].id`, либо успешный тестовый POST `/v1/chat/completions` с этим alias возвращает то же имя в поле `model` ответа. Один HTTP 200 без проверки имени не подтверждает alias. Повторить проверку при смене `LLM_MODEL_NAME`, пересоздав llm и app с согласованными настройками.

### 3. Минимальная административная диагностика

Предлагаемые команды: `python -m app.llm_check health` и `python -m app.llm_check completion`; в Compose — `docker compose exec app python -m app.llm_check ...`. Это один небольшой модуль со стандартной библиотекой HTTP/JSON, без SDK/provider interface и новых runtime Python-пакетов. Использовать LLM_BASE_URL как корень для `/health` и `/v1/chat/completions`; исключить проксирование локальных запросов через HTTP_PROXY окружения. Новые поля конфигурации имеют defaults, не проверяют наличие модели и не выполняют сеть при импорте/запуске app.

Health: один запрос, timeout 5 секунд; 200/status=ok означает готовность, 503 — загрузка, ошибки соединения/JSON/timeout дают понятный ненулевой exit. Для измерения старта shell-процедура повторяет команду с интервалом 1 секунда и общим пределом 600 секунд. Не считать timeout нормальным результатом загрузки. Семантика readiness сверена с [llama.cpp /health](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md#api-endpoints).

Completion: non-streaming запрос с вопросом «Ответь по-русски в двух коротких предложениях: почему зимой бывает снег?», без system/RAG prompt. Параметры из SPEC.md: temperature 0.2, top_p 0.8, top_k 20, max_tokens из LLM_MAX_TOKENS. Timeout 300 секунд учитывает CPU и ожидание одного слота. Проверить HTTP/JSON, непустой choices[0].message.content, вывести ответ и timings; без retries генерации. Русский язык и осмысленность оценивает человек, не дополнительная модель.

### 4. Один активный запрос

На этом этапе генерация доступна только через диагностические обращения к одному llm. Единственный серверный слот (parallel 1) обеспечивает сериализацию даже для двух отдельных CLI-процессов. Подтвердить двумя одновременными запросами и временными отметками/логами слота, а не только чтением аргумента. Отдельный application semaphore не добавляется, поскольку у FastAPI ещё нет пути генерации; требование §18 для будущего chat API остаётся на его change. Python lock внутри CLI не защитил бы от второго процесса.

### 5. Benchmark без фиктивных чисел

Добавить при реализации `docs/local-cpu-runtime-benchmark.md` с процедурой и явно незаполненными полями до реального запуска. Нужен целевой Linux-сервер, не Windows workstation. Подготовить образы и модель до измерений. Достаточно документированных команд и вывода диагностического модуля, без отдельного benchmark framework.

Процедура:

1. Оставить app и обычные сервисы хоста запущенными; остановить только llm. Записать дату, CPU/RAM, версии Docker/llama.cpp, digest образа, GGUF SHA256/размер, параметры. Снять `/proc/meminfo`/`free -b` и swap; у остановленного llm память обозначить «контейнер остановлен», не выдумывать RSS.
2. Измерять elapsed до первого успешного LLM health с момента команды запуска llm. Назвать величину «start-to-ready», включающую контейнерный startup, загрузку и warmup. Если лог отдельно сообщает load time, записать его отдельно. Указать шаг опроса и состояние файлового кэша; не очищать cache всего хоста ради теста.
3. После readiness снять те же метрики памяти хоста и `docker stats --no-stream` для app/llm. Не приравнивать размер GGUF к RAM или delta свободной памяти к RSS. Записать единицы и источник каждой величины.
4. Выполнить один фиксированный короткий русский запрос; сохранить текст ответа, generated tokens, server generation time, generation tokens/sec и end-to-end время отдельно. Источник скорости — server timings/лог decode; при необходимости вычислить generated tokens / decode seconds. Не делить токены на общее HTTP-время. Подтвердить доступность timings на закреплённой сборке; отсутствие измерения оставляет критерий открытым.
5. Снять память после генерации, наблюдать swap activity и отзывчивость существующей Wiki.js без чтения её corpus или GraphQL. При постоянном thrashing снизить threads/ресурсные лимиты и повторить измерение с записью обоих наборов параметров. Конкретные лимиты Compose выбираются по фактическому запасу памяти; 15 ГиБ нельзя отдавать llm целиком.

Это не проверка E5, индексации или полного RAG и не финальные 10 вопросов из §25. Любая недоступность сервера/метрик оставляет задачу benchmark незавершённой.

### 6. Offline и регрессия

Unit tests используют локальный HTTP stub/подмену транспорта: readiness, 503, connection/timeout, malformed JSON, completion request shape, непустой/пустой ответ и env overrides. Существующие bootstrap-тесты должны проходить без модели и Docker.

Интеграционная проверка после предварительной загрузки образов/модели: ограничить только тестовую Compose-сеть от внешнего доступа (например, временная internal network конфигурация), сохранить app–llm связь, выполнить restart, оба health и completion. `--network none` для llm отдельно не проверяет взаимодействие двух сервисов. Не добавлять production firewall feature. Все временные тестовые изменения сети удаляются после проверки.

## Risks / Trade-offs

- Изменения CLI llama.cpp → pin digest, проверка --help, health/completion/timings на выбранной сборке до завершения задач.
- GGUF около 2.5 GB не определяет общий расход RAM → измерять host и containers, сохранить запас для ОС и Wiki.js.
- Короткий русский ответ не доказывает будущую RAG-корректность → приёмка этого change ограничена runtime.
- Архивированный bootstrap имеет оговорки в тестировании → заново проверить Compose и offline при интеграции, не считать прошлые checkbox доказательством.

## Migration Plan

При apply сначала сохранить рабочий app-only запуск и тесты, подготовить документацию и конфигурацию, вручную установить GGUF/образ, запустить llm и выполнить проверки/benchmark. Изменений данных нет. Откат: остановить llm, вернуть предыдущую Compose-конфигурацию либо запустить только app. Host GGUF сохраняется. Сейчас никаких runtime-файлов, моделей или образов не создаётся и не скачивается.
