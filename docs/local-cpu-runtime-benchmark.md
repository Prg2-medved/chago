# Проверка local-cpu-runtime

**Статус: не измерено на целевом сервере.** Docker отсутствует в среде разработки;
пользователь выполнит проверку на i5-14400 самостоятельно. Ниже методика и поля для
фактических результатов. Пустые поля не означают успешную приёмку.

## Среда и результат

| Поле | Фактическое значение |
|---|---|
| Дата и оператор | 2026-09-30 |
| CPU / RAM / ОС | Intel Core i5-14400 / 15 GiB RAM / Linux |
| Docker / Compose | Проверено на целевом сервере; `docker compose config` успешен |
| llama.cpp version и image RepoDigest | llama.cpp `0.5.0-dev`, build `11243`, commit `fc07d781e`; `ghcr.io/ggml-org/llama.cpp@sha256:f9115c95639e60abc09d4ea83b26fd4d56c66aa1174594393335a514da00c283` |
| GGUF revision / SHA256 / размер | SHA256=2fde00ce69dd4899c70d020845e2638353015bba0fdf161b3eb965f2bca4464e; revision/размер отдельно не фиксировались |
| Context / threads / parallel | `8192 / 8 / 1`, подтверждено `docker compose config`, `--help`, логами и фактическим тестом двух запросов |
| Start-to-ready, секунды | 2.562 с |
| Отдельный load time из лога, если есть | Не измерено |
| Host MemAvailable/Swap до старта, байты | MemAvailable=9898754048 B; Swap used=1980219392 B |
| Host MemAvailable/Swap после readiness, байты | MemAvailable=6712406016 B; Swap used=1983627264 B |
| app/llm memory после readiness, единицы docker stats | app=31.21 MiB; llm=2.838 GiB |
| Host и app/llm memory после генерации | MemAvailable=6761922560 B; Swap used=1986772992 B; app=31.21 MiB; llm=2.848 GiB |
| Generated tokens / decode ms / tokens/sec | 60 / 3066.685 ms / 19.239 tok/s |
| HTTP elapsed, секунды | 3.485 с |
| Русский ответ / alias | Успешно. Исходный alias `Qwen3-4B-Instruct-2507`; override `cpu-alias-check` также успешно подтверждён после пересоздания `llm` и `app` |
| Одновременные запросы / slot log evidence | Два одновременных completion: ≈ `3.195 s` и ≈ `6.226 s`; подтверждена последовательная обработка при `parallel=1` |
| Wiki.js отзывчивость / swap activity | `vmstat`: `si=0`, `so=0` во время генерации; отзывчивость Wiki.js ещё проверить |
| Offline restart, health, completion | Не проверено |

Проверьте образ и подготовьте модель по README; сеть разрешена на установке.
Весь дальнейший benchmark выполняется на целевом сервере из корня проекта.
Не отключайте Wiki.js и не очищайте page cache хоста.

## 1. Baseline и готовность модели

```sh
date -Is
lscpu
docker version
docker compose version
docker compose config
docker compose up -d --no-deps app
docker compose stop llm
free -b
cat /proc/meminfo
docker stats --no-stream $(docker compose ps -q app)
```

Сохраните вывод, checksum/revision GGUF и `llm --version` из README.
Память остановленного llm обозначайте «остановлен», а не «RSS=0».
Замерьте время монотонными часами с момента запуска llm до успешного health:

```sh
python3 - <<'PY'
import subprocess, time
started = time.monotonic()
subprocess.run(['docker', 'compose', 'up', '-d', '--no-deps', 'llm'], check=True, timeout=60)
deadline = started + 600
while time.monotonic() < deadline:
    result = subprocess.run(
        ['docker', 'compose', 'exec', '-T', 'app', 'python', '-m', 'app.llm_check', 'health'],
        capture_output=True, text=True, timeout=15)
    if result.returncode == 0:
        print(f'start_to_ready_seconds={time.monotonic() - started:.3f}')
        break
    time.sleep(1)
else:
    raise SystemExit('FAIL: llm not ready within 600 seconds')
PY
free -b
cat /proc/meminfo
docker stats --no-stream $(docker compose ps -q app llm)
docker compose logs --no-color llm
```

Это start-to-ready: контейнерный startup + загрузка + warmup, с погрешностью опроса
и CLI Docker. Если в логе есть отдельное время загрузки, запишите его отдельно.
Укажите, был ли файл в файловом кэше (если неизвестно — так и запишите).
Не приравнивайте GGUF size, docker stats и разницу MemAvailable к одной метрике.
Логи должны подтверждать CPU backend, отсутствие GPU offload и один слот.

## 2. Один короткий запрос

```sh
docker compose exec -T app python -m app.llm_check completion
docker compose logs --no-color --since 5m llm
free -b
docker stats --no-stream $(docker compose ps -q app llm)
vmstat 1 10
```

Вопрос фиксирован: «Ответь по-русски в двух коротких предложениях: почему зимой
бывает снег?» Сохраните JSON результата, текст ответа и связанные строки лога.
Убедитесь, что ответ связный, на русском и поле model равно LLM_MODEL_NAME.

Если response timings содержат `predicted_n` и `predicted_ms`, вычислите
`tokens/sec = predicted_n * 1000 / predicted_ms` при положительном времени.
Можно использовать серверный `predicted_per_second` с записью исходных timings.
Если timings отсутствуют (`null`), берите decode/eval time и количество generated
tokens из server log, отдельно от prompt evaluation. Наличие этих полей на
закреплённом образе ещё **не проверено**. Если нет достоверного decode time,
скорость остаётся «не измерено»; не делите токены на http_elapsed_seconds.

В браузере проверьте обычную отзывчивость Wiki.js во время запроса; corpus/API
читать не требуется. Запишите наблюдения и swap-in/swap-out из vmstat. Постоянный
thrashing блокирует приёмку: уменьшите threads и повторите замер. Не выделяйте
LLM всю RAM сервера; лимиты Compose подбираются по измеренному запасу.

## 3. Сериализация, alias и смена пути

```sh
docker compose exec -T app python -m app.llm_check completion > /tmp/chago-first.json &
first_pid=$!
docker compose exec -T app python -m app.llm_check completion > /tmp/chago-second.json &
second_pid=$!
wait "$first_pid"
wait "$second_pid"
docker compose logs --no-color --since 5m llm
```

Оба процесса должны завершиться успешно; подтвердите по логам единственного slot,
что генерации не перекрываются. Сохраните evidence, а не только аргумент parallel=1.
Для смены пути скопируйте тот же GGUF под другим именем, измените LLM_MODEL_PATH
и задайте LLM_MODEL_NAME=cpu-alias-check. Пересоздайте llm и app по README.
Успешный completion проверяет model ответа на равенство alias автоматически.
Верните исходные настройки и повторите health. Отдельно проверьте отсутствующий
и некорректный файл: llm должен завершиться ошибкой без загрузки замены; app health
должен оставаться работоспособным. После негативных проверок восстановите файл.

## 4. Offline restart двух сервисов

Образы app/llm и GGUF должны уже находиться на сервере. Временный override создаёт
внутреннюю сеть только для данного Compose project, без изменения firewall хоста:

```sh
cat > /tmp/chago-offline.yaml <<'YAML'
networks:
  default:
    internal: true
YAML
docker compose down
docker compose -f compose.yaml -f /tmp/chago-offline.yaml up -d --pull never --no-build
docker compose -f compose.yaml -f /tmp/chago-offline.yaml exec -T app python -m app.llm_check health
docker compose -f compose.yaml -f /tmp/chago-offline.yaml exec -T app python -m app.llm_check completion
docker compose -f compose.yaml -f /tmp/chago-offline.yaml restart
```

Дождитесь готовности llm и повторите обе команды после restart. App health можно
проверить через loopback внутри app:

```sh
docker compose exec -T app python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health').read().decode())"
docker network inspect $(docker inspect $(docker compose ps -q app) --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}')
```

В inspect убедитесь, что единственная сеть internal=true. Сохраните результаты.
Если LLM ещё загружается, health правильно вернёт ошибку — это не успех проверки.
Восстановление обычной конфигурации:

```sh
docker compose -f compose.yaml -f /tmp/chago-offline.yaml down
docker compose up -d --pull never --no-build
rm /tmp/chago-offline.yaml
```

Проверки app-only и pytest из README также должны пройти. До получения реальных
результатов не отмечайте серверные задачи change выполненными.
