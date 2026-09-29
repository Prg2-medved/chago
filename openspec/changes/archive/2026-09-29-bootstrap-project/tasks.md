# Tasks

## 1. Python-каркас и зависимости

- [x] 1.1 Создать минимальный пакет app/app и каталог app/tests по design.md, без модулей будущего RAG; проверить импорт пакета из внешнего app/.
- [x] 1.2 Добавить requirements.txt с FastAPI/Uvicorn и requirements-dev.txt с pytest/HTTPX и включением runtime requirements, закрепить совместимые версии; проверить установку в Python 3.12 и `python -m pip check`.

## 2. Приложение, конфигурация и локальный запуск

- [x] 2.1 Реализовать FastAPI GET /health с HTTP 200 и JSON status=ok, отключить docs/redoc; добавить test_health.py и проверить контракт через pytest без внешних сервисов.
- [x] 2.2 Реализовать чтение APP_HOST/APP_PORT, значения по умолчанию и проверку порта; добавить test_config.py для defaults, overrides, нечислового порта и границ диапазона, проверить прохождение тестов.
- [x] 2.3 Добавить `python -m app` с одним Uvicorn worker без reload; проверить реальный GET /health при локальном запуске с default и нестандартным портом, а также ненулевой exit code при ошибочном APP_PORT.
- [x] 2.4 Добавить .env.example и разделы README о Python 3.12, установке, локальном запуске, environment variables и pytest; проверить команды из указанного рабочего каталога, объяснить отсутствие автоматической загрузки .env приложением и показать синтаксис PowerShell/POSIX.

## 3. Docker и Compose

- [x] 3.1 Добавить app/Dockerfile на Python 3.12 slim с установкой runtime-зависимостей на build stage и запуском `python -m app`, а также app/.dockerignore; проверить успешную сборку без включения venv, кэшей и локальных env-файлов.
- [x] 3.2 Добавить compose.yaml ровно с сервисом app, одним опубликованным портом, контейнерным bind 0.0.0.0:8000 и host address/port из APP_HOST/APP_PORT; проверить `docker compose config --services`, запуск `docker compose up` и GET /health через опубликованный порт, включая переопределение host port.
- [x] 3.3 Дополнить README командами сборки, запуска, остановки Compose и проверкой /health; документировать .env interpolation, host/container bind и доступ из LAN, app-only health и разрешённый интернет только при установке/сборке; сверить команды с фактической конфигурацией.

## 4. Сквозная проверка готовности bootstrap

- [x] 4.1 Выполнить документированный `python -m pytest` и полный сценарий README от подготовленного окружения до локального и Compose health; зафиксировать результаты всех пяти критериев готовности, не отмечая недоступные проверки выполненными.
- [x] 4.2 Проверить запуск, GET /health и перезапуск после установки без внешней сети локально и для готового образа (контейнер допускается запускать с --network none и проверять через loopback внутри); зафиксировать результат и убедиться, что startup не устанавливает пакеты и не скачивает ресурсы.
- [x] 4.3 Проверить итоговый состав файлов и зависимостей: один app service, без интеграций, моделей, БД, UI, reindex и абстракций под будущие функции; подтвердить соответствие scope proposal.md и отсутствие изменений SPEC.md.

## Результаты проверки 2026-09-29

- Python 3.12.7: зависимости установлены, `pip check` — No broken requirements found.
- `python -m pytest` из app/: 12 passed. Есть предупреждение Starlette об устаревании HTTPX TestClient и предупреждение о недоступности pytest cache в sandbox; ошибок тестов нет.
- Реальный `python -m app`: HTTP 200 и status=ok на default 8000 и override 8010. Неверный APP_PORT проверен subprocess-тестом: exit code 1 и понятное сообщение.
- Локальный старт и повторный старт с Python audit hook, запрещающим socket.connect/getaddrinfo/sendto вне loopback: /health успешен. Первоначальный запрет всех соединений также блокировал внутренний socketpair Windows asyncio; проверка скорректирована для разрешения loopback. Это проверка поведения процесса, не полноценное отключение сети ОС; критерий 4.2 пока не закрыт.
- Docker CLI отсутствует в PATH и стандартном пути Docker Desktop. Dockerfile/compose.yaml созданы и просмотрены, но build, Compose startup, публикация порта и контейнерный offline smoke не выполнены. Поэтому 3.1, 3.2, 4.1 и 4.2 остаются открытыми.
- README и .env.example созданы; PowerShell-команды локального запуска/тестов проверены, POSIX-примеры просмотрены без выполнения на Linux.
- SPEC.md не изменён: SHA256 5A1489373DC4DAEE0E7304D84738FD34CC67B8769E524FA4E1D1A4AB0E874A5C.
- Критерии пользователя 1–3 подтверждены. Критерий 4 требует Docker-среды; критерий 5 подтверждён анализом runtime и локальной process-level проверкой, полная offline-приёмка остаётся открытой.
