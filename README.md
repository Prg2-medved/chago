# Chago — минимальный Python-каркас

FastAPI-приложение с единственным endpoint `GET /health`. Он возвращает
HTTP 200 и `{"status":"ok"}`, подтверждая только работу приложения.
RAG, Wiki.js, модели, индекс и Web UI пока не реализованы.
Верхнеуровневые требования находятся в [SPEC.md](SPEC.md).

## Требования

- Python 3.12 для локального запуска и тестов.
- Docker Engine с Docker Compose v2 (Linux containers) для контейнерного запуска.
- Интернет для первоначальной установки пакетов и сборки образа.

После установки/сборки запуск и работа приложения не требуют интернета,
GPU, базы данных, моделей или других сервисов. При старте ничего не скачивается.

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
$env:APP_HOST = "127.0.0.1"
$env:APP_PORT = "8010"
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

## Docker Compose

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
docker compose up -d
```

Первая команда должна вывести только `app`. Проверка HTTP — теми же командами
выше, с выбранным host port. Для просмотра логов и остановки:

```sh
docker compose logs app
docker compose down
```

Обычный `docker compose up` запускает приложение с выводом логов в терминал.
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
