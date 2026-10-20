# Atomic full reindex: журнал проверки

Дата локальной проверки: 2026-10-20. Рабочая станция: Windows, Python 3.12,
существующее `.venv` проекта. **Серверная приёмка не выполнена.** Docker CLI не
найден; `wsl --list --quiet` не вернул дистрибутивов. Доступ к целевому Linux
серверу, установленной E5 и read-only Wiki.js source в этой сессии не предоставлен.

## Фактически выполнено локально

- Новые metadata/indexer/state tests с mock source/encoder и реальными SQLite/FTS:
  update/delete/empty, точный Markdown/provenance, reopen новым процессом,
  сохранение hash/mtime и hybrid retrieval при отказах, first-run failure,
  corrupt candidate, активный WAL/sidecars и busy checkpoint собственного candidate.
- Startup/shutdown FastAPI на поколениях A/B, failed rebuild с возвратом к A,
  недоступные missing/corrupt/incompatible/legacy files, health без индекса,
  чтение без model libraries/assets и без обращения к Wiki.js.
- Связанный regression-прогон: 342 passed, 28 skipped; последующие дополнительные
  проверки metadata reader/query: 62 passed, 24 skipped.
- Полный `python -B -m pytest -q --tb=short` из `app/`: 797 passed, 31 skipped.
  Skips, включая Linux flock и Bash/signal сценарии, не являются их проверкой.
  Единственное предупреждение — существующая deprecation Starlette/httpx TestClient.
- `python -B -m mypy --follow-untyped-imports app` из `app/`: без ошибок,
  24 source files. `bash -n reindex.sh` через Git Bash: exit 0.

## Остаётся на Linux/сервере

- `docker compose config --quiet` без вывода secrets.
- Настоящие Linux builder flock и host lifecycle/signal tests:
  `python -m pytest tests/test_indexer.py tests/test_reindex_script.py` из `app/`.
- `./reindex.sh` на предустановленной E5 и read-only view; подтверждение
  running/HTTP/restart и UTC counts/time из опубликованного поколения.
- Измерение фактической длительности и peak RAM полного reindex; semantic,
  lexical и hybrid запросы новым процессом с настоящим encoder.
- На изолированном data path/read-only test source: update/delete/empty,
  failed rebuild с сохранением A и retrieval после restart, WAL/SHM отказ,
  first-run failure, конкурирующий запуск, interruption до/после commit,
  подтверждение завершения собственного one-shot и manual recovery,
  failed app recovery при `up=0`.

Серверные counts, latency, RAM и результаты запросов здесь не указаны: измерений
не было. Production Wiki.js не изменялся. Hit@5 ≥90% не является gate этого этапа.
