# Tasks

Apply evidence (2026-10-06): targeted chunking/E5/CLI/corpus tests: 87 passed,
1 skipped (Windows symlink privilege). Regression ingestion/evaluation/config/health:
164 passed, 4 skipped (POSIX-only permissions). Mypy: 2 modules passed using
the local tokenizers API stub. OpenSpec strict validation passed. Real pinned
E5 runs, hashes, source coverage, evidence and safe citation selections are in
`docs/markdown-chunking.md`.

Server acceptance for 3.3/3.4: the user reported successful execution of
`docs/markdown-chunking-server-checks.sh` in `~/chago-llm/chago` on the target
Linux server, ending with `PASS: all server checks complete`. Tokenizer asset
SHA-256 checks passed; both Compose fixture runs were identical (1 document,
1 chunk, max body/input 45/67 tokens). App-only startup with no tokenizer files,
Wiki.js, LLM or network returned HTTP 200 with `{"status":"ok"}`. Missing-assets
CLI returned exit 1 and `chunking: tokenizer_assets`, preserving the old output.
The user confirmed README/ROADMAP, compose.yaml, frozen snapshot, evaluation
manifest/questions/fixture and tokenizer assets remained unchanged. This is
user-reported actual server evidence, not an independently repeated agent run.
Both tasks are complete; no verification blockers remain.

## 1. Контракт данных и локальный token budget

- [x] 1.1 Добавить typed chunk/settings/segment модели и validation ingestion snapshot schema_version 1 в `app/app/chunking.py`, сохраняя исходный Markdown и source metadata; проверить целевыми tests пустой snapshot/document, duplicate IDs, неверные types/hash/source_url, CRLF и Unicode offsets.
- [x] 1.2 Добавить минимальную pinned tokenizer-only зависимость и локальный E5 adapter с отключёнными truncation/padding, единым passage formatter и settings validation; при apply проверить реально установленные assets/происхождение и закрепить model ID `intfloat/multilingual-e5-small`, immutable revision (полный commit ID), assets fingerprint и версию pinned Python package `tokenizers` в output. Проверить targeted tests на запись identity/version, запрет плавающего main/branch/tag, missing/corrupt assets, отсутствие runtime network fallback, special tokens, 450/512 boundaries и невозможный metadata budget. Fake counter не считается E5 acceptance.
- [x] 1.3 Начать `docs/markdown-chunking.md`: описать output schema, source/generated distinction, defaults, формат passage, immutable model ID/revision, assets fingerprint/package version и предварительную установку; закрепить требование будущего embedding stage использовать совместимый tokenizer той же model revision. Сверить описание с моделями и фактическим local loader.

## 2. Структура Markdown и упаковка

- [x] 2.1 Реализовать source-preserving scanner для ATX/Setext headings, текста и fenced blocks; добавить fixtures/tests на преамбулу, heading-only, пропуски уровней, backtick/tilde fences, info strings, незакрытый fence и headings внутри кода; проверить правильный heading path и полное покрытие исходных символов.
- [x] 2.2 Реализовать упаковку blocks одного раздела с target/max/full-input проверкой и ограниченным overlap prose; проверить tests на отсутствие overlap между страницами/разделами, стабильное продвижение, уменьшение overlap при длинных metadata, сохранность literals и большую страницу.
- [x] 2.3 Реализовать сохранение короткого code block целиком, деление длинного по строкам/Unicode slices и block/continuation metadata; проверить восстановление исходного блока, CRLF, очень длинную строку, multiline Bash и признаки неполных команд во всех разделённых частях.
- [x] 2.4 Реализовать pipe tables, повторение generated header/separator, split oversized rows/cells и table/row links; проверить tests на escaped pipes/inline code, длинную таблицу/ячейку, точные значения, generated/source separation и явную ошибку невмещающегося header.
- [x] 2.5 Дополнить `docs/markdown-chunking.md` правилами поддерживаемой структуры, lossless fallback, overlap и continuation/citation semantics; проверить описанные примеры через структурные tests.

## 3. Воспроизводимый output и CLI

- [x] 3.1 Реализовать stable chunk IDs, deterministic ordering и versioned chunks JSON с исходными documents; проверить побайтовый повторный output при перестановке documents, изменение IDs при изменении metadata/settings/tokenizer и отсутствие live/synthetic collisions.
- [x] 3.2 Добавить CLI `python -m app.chunking --input ... --output ... --tokenizer-path ...`, controlled diagnostics, counts/maxima и atomic output; проверить subprocess tests на успешный запуск, invalid snapshot/settings/tokenizer, write/replace failure, сохранение старого output и защиту input/tokenizer от перезаписи, включая aliases.
- [x] 3.3 Использовать для Compose CLI assets в `data/tokenizers/<immutable-revision>/` через существующий mount `./data:/data`, без отдельного постоянного tokenizer mount и без изменения Compose configuration; adapter только читает assets. При необходимости описать CLI path в `.env.example`, не добавляя его validation в HTTP settings. Проверить документированный chunking run, обычный container app-only startup/health при отсутствующих tokenizer files и без Wiki.js/LLM; отдельно подтвердить controlled error CLI при отсутствии assets.
- [x] 3.4 Завершить local/Compose команды и recovery/output guidance в `docs/markdown-chunking.md`; выполнить команды как написано на fixture, проверить, что README.md/ROADMAP.md и ingestion snapshots не изменены.

## 4. Интеграционная приёмка на E5 и frozen corpus

- [x] 4.1 Сначала запустить целевые chunking/tokenizer tests; затем regression `tests/test_ingestion.py`, `tests/test_evaluation.py`, `tests/test_config.py`, `tests/test_health.py` и дополнительные tests settings при их изменении. Проверить типизацию изменённых модулей существующими средствами проекта; записать фактические результаты, полный suite запускать только при выявленном межкомпонентном влиянии.
- [x] 4.2 С предварительно установленными настоящими E5 assets проверенной immutable revision выполнить offline CLI дважды на frozen live reference `data/eval/1/wiki-documents.json` и отдельно synthetic snapshot; сравнить bytes/IDs/fingerprints, проверить каждый body <=450 и каждый полный passage <=512 с special tokens. Проверить сохранение model ID, immutable revision, fingerprint фактических assets и версии pinned `tokenizers` в output и записать их вместе с counts/maxima/duration в docs; без реального запуска задачу не отмечать выполненной.
- [x] 4.3 Проверить source slices/union ranges всех документов и все evidence spans/exact_commands `eval/questions.yaml` в chunks соответствующего source set; отдельно показать live/synthetic и tuning/holdout сохранность, проверить hashes reference/manifest/questions до и после. Не менять corpus/holdout, не подбирать параметры по holdout и не заявлять retrieval Hit@5.
- [x] 4.4 Вручную сверить безопасную полную Bash-команду (q02/q03), строки таблицы (q04/q06), части длинного кода (q08) и synthetic injection (q20) с original Markdown/ranges; проверить, что generated обрамление не цитируется как источник, неполные команды обозначены и source_url сохранён. Зафиксировать выбранные безопасные IDs/ranges и итог проверки без secrets/полного Markdown.
- [x] 4.5 Выполнить `openspec validate markdown-chunking --strict` и проверить scoped Git diff; подтвердить отсутствие embeddings/retrieval/SQLite/API изменений, целостность исходных документов и наличие фактических acceptance evidence. Невыполненные реальные проверки оставить `[ ]` с конкретной причиной.
