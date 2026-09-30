# Chago — локальный CPU runtime
FastAPI-приложение с единственным endpoint `GET /health`. Он возвращает
HTTP 200 и `{"status":"ok"}`, подтверждая только работу приложения.
Compose дополнительно описывает CPU llama.cpp с локальной Qwen GGUF.
RAG, интеграция Wiki.js, индекс и Web UI пока не реализованы.
Верхнеуровневые требования находятся в [SPEC.md](SPEC.md).
## Требования
- Python 3.12 для локального запуска и тестов.
- Docker Engine с Docker Compose v2 (Linux containers) для контейнерного запуска.
- Интернет для первоначальной установки пакетов и сборки образа.
App-only запуск не требует модели. Полный запуск требует заранее подготовленных
образов и GGUF; после установки интернет не нужен. При старте ничего не скачивается.
GPU и CUDA не используются.
**Статус проверки:** Python-тесты проходят. На целевом Linux-сервере
с Intel Core i5-14400 и 15 ГиБ RAM запущены app и llm, проверены app health,
LLM health и реальный русский completion. Для llama.cpp получен RepoDigest и
закреплён в LLM_IMAGE файла .env; runtime подтверждён как CPU-only.
Проверенная сборка llama.cpp: 0.5.0-dev, build 11243, commit fc07d781e,
Linux x86_64. Параметры --ctx-size, --threads, --threads-batch, --parallel,
--device, --gpu-layers, --alias и --no-webui подтверждены через --help.
Последовательная обработка двух одновременных completion при --parallel 1
подтверждена на целевом сервере. До завершения change остаются проверки и
фиксация результатов по [методике benchmark](docs/local-cpu-runtime-benchmark.md).
## Локальная установка и запуск
Команды ниже выполняются из корня проекта. Виртуальное окружение не нужно
активировать: используется явный путь к Python.
PowerShell:
```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r app/requirements-dev.txt
cd app
..\venv\Scripts\python.exe -m app
```
Linux / POSIX shell:
```sh
python3.12 -m venv venv
./venv/bin/python -m pip install -r app/requirements-dev.txt
cd app
../venv/bin/python -m app
```
Для запуска без тестовых зависимостей можно установить `app/requirements.txt`.
Сервер по умолчанию доступен на `http://127.0.0.1:8000`; остановка — Ctrl+C.
В другом терминале проверьте:
```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```
```sh
curl --fail http://127.0.0.1:8000/health
```
## Конфигурация
| Переменная | По умолчанию | Локальный процесс | Compose |
|---|---|---|---|
| `APP_HOST` | `127.0.0.1` | Адрес прослушивания | Адрес публикации на хосте |
| `APP_PORT` | `8000` | Порт прослушивания | Порт публикации на хосте |
Локальное приложение читает environment variables, **не загружает `.env`**.
Порт должен быть целым числом от 1 до 65535; неверное значение завершает запуск
с ненулевым кодом и сообщением об `APP_PORT`.
Пример переопределения перед запуском из каталога `app/`:
```powershell
Env: App Host = "127.0.0.1"
Env: App Port = "8010"
..\venv\Scripts\python.exe -m app
```
```sh
APP_HOST=127.0.0.1 APP_PORT=8010 ../venv/bin/python -m app
```
После этого health доступен на `http://127.0.0.1:8010/health`.
Для доступа из LAN задайте `APP_HOST=0.0.0.0` и обращайтесь по IP сервера.
## Тесты
Из каталога `app/`, после установки `requirements-dev.txt`:
```powershell
..\venv\Scripts\python.exe -m pytest
```
```sh
../venv/bin/python -m pytest
```
В активированном окружении эквивалентная команда — `python -m pytest`.
Тесты проверяют health и конфигурацию; Docker и внешние сервисы не нужны.
## Docker Compose: только app
Команды выполнять из корня проекта. При необходимости скопируйте
`.env.example` в `.env` (`Copy-Item .env.example .env` в PowerShell или
`cp .env.example .env` в POSIX shell) и измените адрес/порт.
Без `.env` действуют значения по умолчанию.
Compose использует эти значения для публикации порта на хосте.
Внутри контейнера приложение всегда слушает `0.0.0.0:8000`.
Переменные текущего shell имеют приоритет над `.env`; учитывайте это после
локальных экспериментов с `APP_PORT`.
```sh
docker compose config --services
docker compose build app
docker compose up -d --no-deps app
```
Первая команда должна вывести `app` и `llm`. Команда запуска выше поднимает только
`app` без модели. Проверка HTTP — теми же командами
выше, с выбранным host port. Для просмотра логов и остановки:
```sh
docker compose logs app
docker compose down
```
Обычный `docker compose up` запускает оба сервиса и требует подготовленной модели.
После первоначальной сборки повторный запуск готового образа возможен без
интернета; выполнять повторную сборку для запуска не требуется.
Для отдельной проверки готового образа без сети:
```sh
docker build -t chago-bootstrap ./app
docker run -d --name chago-bootstrap-offline --network none chago-bootstrap
docker exec chago-bootstrap-offline python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health').read().decode())"
docker restart chago-bootstrap-offline
docker exec chago-bootstrap-offline python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health').read().decode())"
docker rm -f chago-bootstrap-offline
```
Перед каждым `docker exec` дождитесь сообщения Uvicorn о готовности в
`docker logs chago-bootstrap-offline`. Это отдельная проверка без опубликованного
порта; штатный запуск через Compose сохраняет HTTP-доступ с хоста.
## Подготовка LLM (вручную, с интернетом)
Выполняйте из корня проекта на Linux-сервере. Compose не скачивает ни образ llm,
ни модель. Для предварительной установки используется официальный server image
`ghcr.io/ggml-org/llama.cpp:server`, без CUDA-суффикса. На целевом сервере после
загрузки образа его точный RepoDigest закрепляется в `LLM_IMAGE` файла `.env`,
поэтому штатный runtime не зависит от floating tag.
```sh
docker pull ghcr.io/ggml-org/llama.cpp:server
docker image inspect ghcr.io/ggml-org/llama.cpp:server --format '{{index .RepoDigests 0}}'
```
Скопируйте полный выведенный `ghcr.io/ggml-org/llama.cpp@sha256:...` в
`LLM_IMAGE` в `.env`. На целевом сервере эта операция уже выполнена: RepoDigest
получен и закреплён. Само значение digest является частью серверной конфигурации и
должно быть перенесено в benchmark-документ как evidence приёмки. Floating tag
используется только для первоначального `docker pull`, а не как окончательная
runtime-конфигурация.
Проверьте закреплённый образ до запуска модели:
```sh
docker compose run --rm --no-deps llm --version
docker compose run --rm --no-deps llm --help
```
Эти Compose-команды используют bind mount, поэтому выполняйте их после подготовки
GGUF ниже. Альтернатива до установки GGUF — `docker run --rm --pull never IMAGE --help`
с полным полученным RepoDigest вместо `IMAGE`.
Сохраните build/version, убедитесь в поддержке аргументов из compose.yaml,
включая `--alias`, `--device none`, `--gpu-layers 0`, `--parallel 1`, `--no-webui`.
На целевом сервере проверена сборка `0.5.0-dev` (build `11243`, commit
`fc07d781e`) для Linux x86_64. Через `--help` подтверждены используемые параметры
`--ctx-size`, `--threads`, `--threads-batch`, `--parallel`, `--device`,
`--gpu-layers`, `--alias` и `--no-webui`. Runtime запускается с `--device none` и
`--gpu-layers 0`; CUDA/GPU-вариант не используется.
Источник образов и аргументов: [llama.cpp](https://github.com/ggml-org/llama.cpp/tree/master/tools/server).
Вручную скачайте **Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf** из
[bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF](https://huggingface.co/bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF/tree/main).
Выберите конкретную revision репозитория, запишите её и опубликованный SHA256
файла. Поместите файл в `models/` либо задайте абсолютный `LLM_MODEL_PATH`.
Для проверки локального файла:
```sh
sha256sum models/Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf
stat -c '%s bytes' models/Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf
```
Сравните checksum с опубликованным значением и запишите оба в benchmark.
Модель не добавляется в Git или образ app. Существующий файл монтируется read-only
в `/models/model.gguf`; ошибочный host path не создаётся автоматически.
Установочных скриптов скачивания модели нет.
## Настройки LLM
| Переменная | Значение по умолчанию |
|---|---|
| `LLM_IMAGE` | Для preload: `ghcr.io/ggml-org/llama.cpp:server`; на целевом сервере в `.env` используется полный закреплённый RepoDigest `ghcr.io/ggml-org/llama.cpp@sha256:...` |
| `LLM_MODEL_PATH` | `./models/Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf`, путь хоста относительно compose.yaml |
| `LLM_MODEL_NAME` | `Qwen3-4B-Instruct-2507`, alias, не имя GGUF-файла |
| `LLM_BASE_URL` | `http://llm:8080`, без `/v1` |
| `LLM_CONTEXT_SIZE` | `8192` |
| `LLM_THREADS` | `8`, для генерации и обработки prompt |
| `LLM_MAX_TOKENS` | `768`, положительное целое |
Compose передаёт `--alias ${LLM_MODEL_NAME}` серверу и то же имя окружению app.
Поле `model` completion-запроса использует этот alias. CLI проверяет совпадение
`model` ответа; дополнительно можно проверить `data[].id` через `/v1/models`.
Из локального Python `http://llm:8080` обычно недоступен: выполняйте диагностику
через `docker compose exec app`, где работает Compose DNS. Локально задавайте URL
уже доступного локального сервера через environment; Python не читает `.env`.
## Запуск и диагностика LLM
После установки образа и GGUF:
```sh
docker compose build app
docker compose up -d
docker compose logs llm
docker compose exec -T app python -m app.llm_check health
docker compose exec -T app python -m app.llm_check completion
```
`health` вызывает `/health` llama.cpp (timeout 5 секунд). Загрузка/503,
недоступность и некорректный ответ дают exit code 1; повторите проверку после
готовности модели. `/health` самого app всегда проверяет только app.
`completion` отправляет один короткий русский вопрос, без RAG/system prompt,
с temperature=0.2, top_p=0.8, top_k=20 и timeout 300 секунд.
Он выводит JSON с вопросом, ответом, alias, usage, доступными timings и HTTP-временем.
Ошибки, пустой ответ и несовпадающий alias дают exit code 1 без повторной генерации.
Осмысленность и русский язык ответа проверяются человеком.
LLM имеет один слот генерации (`--parallel 1`), порт не публикуется на хосте.
На целевом сервере последовательная обработка подтверждена двумя одновременными
completion: один запрос завершился примерно за 3.19 с, второй — примерно за 6.23 с,
при близком decode time около 2.96–2.98 с. Это подтверждает ожидание второго
запроса единственного slot. App запускается независимо от llm.
Смена файла/alias: измените `LLM_MODEL_PATH` и при необходимости `LLM_MODEL_NAME`
в `.env`, затем выполните:
```sh
docker compose up -d --force-recreate llm app
docker compose exec -T app python -m app.llm_check health
docker compose exec -T app python -m app.llm_check completion
```
Python-код не меняется. Новая модель должна поддерживаться закреплённым llama.cpp.
Для проверки пути можно скопировать тот же GGUF под другим именем и задать другой
alias. После проверки верните исходные настройки.
Порядок измерений и offline-проверки двух сервисов описан в
[benchmark](docs/local-cpu-runtime-benchmark.md). Остановка: `docker compose down`;
локальный файл модели сохраняется.