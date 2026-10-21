# Grounded chat API: lifecycle и retrieval

На 2026-10-21 реализован слой active retrieval. `POST /api/chat`, LLM client,
prompt и validators ещё не реализованы. Linux-проверка фактической замены
открытого файла (задача 1.3) принята по выводу оператора: 30 passed,
`PATHNAME_REPLACEMENT_OK`. Выполнение остановлено на раннем live-gate 2.1,
обязательном до зависимой реализации.

## Удерживаемое поколение

Lifespan создаёт `RetrievalService` с одним выделенным executor thread.
Этот поток открывает и проверяет SQLite через `load_index_state`, выполняет
поиски и закрывает ресурсы. Существующий `app.state.index` сохраняется;
внутренний `app.state.retrieval` предоставляет асинхронный `search(question)`.
Публичных retrieval/reindex/context override endpoints этот слой не добавляет.

Hybrid view заимствует удерживаемые reader, validated semantic matrix и
snapshot у `ActiveIndex`. Он не открывает pathname повторно и не перечитывает
matrix. Semantic identity encoder проверяется до поиска. Lexical probe
закрывает view, основной reader закрывает `IndexState`. Standalone
`HybridIndex(path, encoder, settings)` и CLI сохраняют прежнее владение.

Одновременные поиски сериализуются в executor. Возвращается tuple
`HybridResult` с `StoredChunk` из того же snapshot: исходный Markdown,
source ranges, title и source URL согласованы с retrieval. Отмена ожидания
не прерывает выполняющуюся SQLite-операцию. Закрытие ставится после уже
отправленных операций и выполняется в том же потоке, включая поиск,
завершившийся ошибкой. Поздние ошибки отменённых ожиданий извлекаются без
необработанных asyncio diagnostics.

Публикация нового индекса не переключает уже работающий процесс. Прежнее
поколение удерживается до restart; новый lifespan загружает новое поколение.
Будущие quotes должны относиться к этому snapshot, а URL откроет текущую
страницу Wiki.js, которая могла измениться после индексации.

## Read-only и lazy assets

Поиск использует прежние semantic/lexical/RRF правила и defaults:
10 semantic candidates, 10 lexical candidates, RRF constant 60, top-k 6.
Environment overrides сохраняются через `load_retrieval_settings`.
Отказ ветки не превращается в молчаливый fallback.

`LocalEncoder` и retrieval settings создаются при первом поиске в executor.
Startup не требует embedding assets, LLM или Wiki.js. Отсутствующий,
повреждённый либо несовместимый индекс остаётся unavailable; индекс не
создаётся автоматически. Запросы не изменяют SQLite, не запускают ingestion
или reindex и не скачивают model assets. Health сохраняет HTTP 200 и JSON
`{"status":"ok"}` без readiness checks. Ошибка lazy encoder не закрывает
удерживаемый reader и не ломает health.

## Граница этапа и проверки

Планируемый chat обрабатывает текущий вопрос независимо. История,
follow-up и query rewriting относятся к следующему change `session-follow-up`.

Temporary SQLite tests сравнивают borrowed view со standalone hybrid,
проверяют model identity mismatch, defaults, сериализацию concurrent searches,
закрытие после ошибки/отмены, app-only startup и согласованность source metadata.

В Windows `os.replace` открытого SQLite может завершаться `PermissionError`.
В этом случае тест проверяет сохранность старого snapshot, отсутствие повторного
открытия и загрузку нового поколения после close, но **не подтверждает подмену
pathname при открытом reader**. Фактический Linux-прогон 1.3 выполнен оператором
и подтверждён в журнале. Команда из каталога `app/` в подготовленном Linux окружении:

```bash
python -m pytest -q -rs tests/test_active_retrieval.py tests/test_index_state.py tests/test_hybrid_retrieval.py tests/test_hybrid_retrieval_cli.py tests/test_health.py
```

В Linux тест не допускает `PermissionError` вместо подмены. После успешного
`os.replace` он требует прежние результаты и provenance до close и новое
поколение при следующем startup. Локальные результаты и оставшиеся gates:
[журнал проверки](grounded-chat-api-server-acceptance.md).
В журнале также приведена одна Docker-команда из корня проекта: отдельный
контейнер с read-only исходниками, SQLite только в tmpfs и явным маркером
`PATHNAME_REPLACEMENT_OK` в успешном Linux-выводе.
