# Tasks

## 1. Input contract

- [x] 1.1 Добавить typed storage records и parser chunking output v1 в app/app/index_storage.py без загрузки tokenizer; проверить валидный output, пустой inventory и независимость от assets/credentials целевыми tests/test_index_storage.py.
- [x] 1.2 Реализовать проверки document identity/hash/metadata и chunk IDs, ordinal, segments/ranges/search_text, settings/tokenizer metadata; проверить parametrized rejection tests для неверных типов/версий, orphan chunks, duplicates, mismatched metadata и повреждённой provenance.
- [x] 1.3 Начать docs/sqlite-index-storage.md с input contract, storage-only границами и отсутствием пересчёта E5 counts; проверить соответствие документации parser и spec.

## 2. SQLite persistence and reading

- [x] 2.1 Создать schema v1 с metadata, documents, chunks, PK/UNIQUE/FK и JSON вложенными полями; проверить дословный round-trip Markdown, семантически lossless round-trip вложенных JSON-структур с сохранением порядка массивов, Unicode/CRLF, source slices и code/table/generated segments в tests/test_index_storage.py.
- [x] 2.2 Добавить read-only reader с schema/integrity проверками, стабильным ordering и lookup по chunk ID; проверить close/reopen, неизвестный ID, отсутствующий файл без его создания, повреждённую БД и неподдерживаемую storage version.
- [x] 2.3 Добавить temporary-file writer с transaction, проверкой закрытого snapshot, os.replace и cleanup без WAL; проверить failure injection для записи/check/replace, сохранность старого output/input, удаление stale records и повторный импорт без duplicates.
- [x] 2.4 Дополнить docs/sqlite-index-storage.md схемой, read API, логической воспроизводимостью и правилом пересоздания неподдерживаемой schema; проверить соответствие фактическому storage/read contract.

## 3. Administrative command

- [x] 3.1 Добавить python -m app.index_storage --input --output с input alias protection, безопасными error categories и counts/version report; проверить subprocess tests/test_index_storage_cli.py для успеха, input symlink/hardlink, invalid JSON и filesystem failures.
- [x] 3.2 Документировать рабочие local и
  `docker compose run --rm --no-deps app python -m app.index_storage`
  команды с `/data/storage-snapshot.db` через существующий mount.
  Проверить локальный пример. Реальную Compose-команду проверить в контейнере
  без Wiki.js/LLM/tokenizer assets; при отсутствии Docker в текущем workspace
  оставить container acceptance незавершённым с конкретной причиной

  Проверка local CLI выполнена на изолированных paths в tmp/storage-acceptance:
  documents=1, chunks=1, storage_version=1. Серверная container acceptance
  подтверждена пользователем 2026-10-08 на Linux / Docker Compose:
  реальный Compose CLI завершился с exit code 0, documents=1, chunks=1,
  storage_version=1; SQLite snapshot создан через существующий /data mount.
  PRAGMA integrity_check → ok, PRAGMA foreign_key_check → [].
  Hardlink и symlink aliases отклонены с exit code 1, исходный JSON не изменился.

## 4. Integration verification

- [x] 4.1 Сначала запустить pytest для tests/test_index_storage.py и tests/test_index_storage_cli.py, затем test_health.py и существующие chunking CLI проверки; подтвердить storage round-trip реального chunking output при доступных локальных E5 assets, не меняя frozen corpus, и зафиксировать пропуски assets.
- [x] 4.2 Запустить mypy для app/index_storage.py с существующим typing setup проекта; подтвердить отсутствие новых зависимостей и изменений README.md/ROADMAP.md, сообщить результаты и оставшиеся ограничения.

Проверки: storage/CLI 103 passed, 1 skipped; health/chunking CLI 9 passed,
1 skipped (оба skip — права symlink Windows). Реальный E5 round-trip прошёл,
assets доступны; frozen corpus не изменён. Mypy: no issues found.
Новых зависимостей нет, README.md и ROADMAP.md не изменены.
