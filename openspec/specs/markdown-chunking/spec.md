# markdown-chunking Specification

## Purpose

Преобразовывать локальный Markdown snapshot Wiki.js в детерминированные поисковые chunks с контекстом разделов, ограниченным E5 input и точной привязкой цитируемых фрагментов к исходной странице.

## Requirements

### Requirement: Lossless snapshot processing
Система SHALL принимать полный ingestion snapshot schema_version 1, проверять обязательные поля, уникальность page_id в source, content_sha256 и source identity до публикации результата. Исходный Markdown SHALL сохраняться дословно, включая Unicode, whitespace и CR/LF. Chunking SHALL работать offline без Wiki.js, DB credentials, LLM, embedding inference, retrieval или загрузки изображений. Пустой Markdown SHALL давать ноль chunks с сохранением документа; непустой документ SHALL сохранять весь исходный текст через source ranges.

#### Scenario: Offline source preservation
- **WHEN** корректный snapshot содержит русский текст, CRLF, Bash, ссылки и изображения
- **THEN** chunks сохраняют технические literals и связь с неизменённым Markdown, изображения не загружаются и команды не выполняются

#### Scenario: Empty documents and snapshot
- **WHEN** snapshot пуст либо содержит документ с пустым Markdown
- **THEN** создаётся валидный результат с соответствующим inventory документов и нулём chunks для пустого документа

#### Scenario: Invalid source
- **WHEN** вход содержит неверную версию, тип, hash или duplicate page ID
- **THEN** весь запуск завершается ошибкой без публикации частичного результата

### Requirement: Heading-aware structural chunks
Система SHALL распознавать ATX и Setext headings вне кода, сохранять полный текущий heading path и title страницы и учитывать границы разделов при упаковке текста. Чанк SHALL принадлежать одному heading path; overlap SHALL NOT переносить текст между разделами или страницами. Заголовки внутри fenced code SHALL NOT менять heading path. Нераспознанный Markdown SHALL сохраняться как исходный текст без потери содержимого.

#### Scenario: Nested and skipped headings
- **WHEN** документ содержит преамбулу, вложенные заголовки, пропуски уровней и следующий соседний раздел
- **THEN** chunks имеют актуальные цепочки существующих заголовков, преамбула имеет пустую цепочку и контент разделов не смешивается

#### Scenario: Heading-like code
- **WHEN** fenced Bash block содержит строки с символом #
- **THEN** строки сохраняются как код и не изменяют heading metadata

### Requirement: Source provenance and deterministic identity
Каждый chunk SHALL содержать source origin, page_id, locale, title, path, source_url, updated_at, content_sha256, heading path, порядковый номер в странице и стабильный уникальный ID. Chunk SHALL хранить упорядоченные полуоткрытые source ranges в Unicode code points исходного Markdown, а добавленные для поиска элементы SHALL быть отличимы от дословных source segments. Исходный Markdown SHALL оставаться доступным в output documents. При одинаковых данных, tokenizer fingerprint, algorithm version и settings output SHALL быть побайтово одинаковым независимо от порядка входных документов; source namespaces SHALL NOT сливаться по page_id или path.

#### Scenario: Repeated run
- **WHEN** один snapshot обрабатывается повторно с теми же параметрами, но другим порядком документов
- **THEN** порядок chunks, IDs, source ranges и байты JSON совпадают

#### Scenario: Exact citation
- **WHEN** downstream consumer извлекает цитату из source range chunk
- **THEN** цитата равна указанному срезу исходного Markdown и не включает синтетические заголовки или fences

#### Scenario: Separate source namespaces
- **WHEN** live и synthetic documents имеют одинаковый page_id
- **THEN** их source identity и chunk IDs различаются

### Requirement: Local E5 token budget
Система SHALL считать токены локальным токенизатором intfloat/multilingual-e5-small с учётом special tokens и фиксировать его идентичность/fingerprint в результате. Параметры SHALL задаваться централизованно: target 350 tokens, maximum chunk text 450 tokens, overlap около 50 tokens; target и overlap являются ориентирами структурной упаковки, maximum — жёстким пределом. Полный сформированный embedding input с `passage:`, title, heading path и поисковым текстом SHALL содержать не более 512 tokens; доступный размер тела SHALL уменьшаться при росте metadata. Truncation SHALL NOT использоваться. Tokenizer SHALL загружаться только из предварительно установленного локального пути, без runtime network fallback. Некорректные settings, отсутствующий/повреждённый tokenizer либо metadata, не оставляющие места для очередного исходного фрагмента, SHALL приводить к явной ошибке без потери текста.

#### Scenario: Full input boundary
- **WHEN** passage input с длинным title и heading path превышает 512 tokens
- **THEN** тело делится на меньшие chunks и каждый окончательный input проверяется целиком с special tokens

#### Scenario: Immutable tokenizer identity
- **WHEN** chunking использует локальные tokenizer assets
- **THEN** фиксируются model ID `intfloat/multilingual-e5-small` и конкретная immutable revision (полный commit ID), а output сохраняет их, fingerprint фактически используемых assets и фактическую версию pinned Python package `tokenizers`; плавающий `main`, branch или tag не допускается

Система SHALL проверять и фиксировать эту immutable identity перед успешным chunking. Конкретные revision и fingerprints SHALL определяться при apply после проверки реально установленных assets и их происхождения. Будущий embedding stage SHALL использовать совместимый tokenizer той же model ID и immutable revision, чтобы фактическая токенизация embeddings соответствовала chunking token budget; несовместимость SHALL NOT игнорироваться. Runtime network fallback SHALL отсутствовать.

#### Scenario: Future embedding tokenizer compatibility
- **WHEN** будущий embedding stage использует результат chunking
- **THEN** его tokenizer совместим с сохранёнными identity/assets той же model revision и token budget; несовместимые assets не используются молча

#### Scenario: Impossible metadata budget
- **WHEN** полный input не вмещает metadata и минимальный следующий исходный фрагмент
- **THEN** обработка завершается явной ошибкой без truncation metadata или исходного текста

#### Scenario: Offline tokenizer failure
- **WHEN** локальные tokenizer assets отсутствуют или повреждены
- **THEN** CLI возвращает ненулевой код без обращения к интернету, а app-only startup не зависит от этих assets

#### Scenario: App container without tokenizer assets
- **WHEN** tokenizer assets отсутствуют при обычном Compose/app-only запуске
- **THEN** container app и FastAPI startup/health работают без tokenizer files; assets обязательны только для chunking CLI, отдельный постоянный mount, делающий startup зависимым от их наличия, не используется

### Requirement: Code and command preservation
Короткий fenced code block, помещающийся в жёсткие бюджеты, SHALL оставаться целым даже при превышении target. Длинные blocks SHALL делиться сначала по исходным строкам, а слишком длинные строки — на последовательные дословные фрагменты без потери символов. Части SHALL сохранять block identity, порядок, исходные диапазоны, language/fence context и признаки продолжения. Исходные fences SHALL сохраняться в source; добавленное обрамление SHALL быть отмечено как поисковое. Разделённая строка команды или multiline-команда SHALL NOT представляться полной командой; metadata SHALL позволять downstream consumer определить неполный блок/команду и сослаться на страницу.

#### Scenario: Short Bash block
- **WHEN** Bash block с точными путями/IP и переносами помещается в maximum и полный E5 budget
- **THEN** блок остаётся целым и дословным

#### Scenario: Oversized code and line
- **WHEN** блок превышает budget, включая одну строку длиннее допустимого chunk
- **THEN** последовательность source segments восстанавливает исходный блок, каждый input помещается и разделённые команды помечены неполными

### Requirement: Searchable table splitting
Markdown pipe tables SHALL сохранять header, separator и все значения строк. Длинные таблицы SHALL делиться по строкам с повторением header/separator в поисковом представлении. Строка/ячейка, не помещающаяся с header, SHALL делиться на последовательные исходные фрагменты без потери текста с table/row identity и признаками продолжения. Повторённый header и добавленное обрамление SHALL NOT считаться новой дословной цитатой. Невмещающийся повторяемый header SHALL приводить к явной budget error.

#### Scenario: Table spans several chunks
- **WHEN** таблица превышает maximum
- **THEN** каждый поисковый фрагмент содержит header, все исходные строки доступны через source ranges и input каждого chunk не превышает 512 tokens

#### Scenario: Very long cell
- **WHEN** одна ячейка превышает доступный budget
- **THEN** её текст сохраняется в последовательных связанных частях, без пропуска или изменения identifiers

### Requirement: Reproducible CLI and verification
Система SHALL предоставлять `python -m app.chunking --input <snapshot> --output <chunks> --tokenizer-path <local-dir>` из app/ и документированный Compose эквивалент. Output SHALL включать schema/algorithm version, tokenizer fingerprint, settings, исходные documents и chunks в стабильном порядке, без времени запуска. Публикация SHALL происходить только после полного успеха; ошибка SHALL сохранять прежний output, возвращать ненулевой код и безопасную категорию без полного Markdown. CLI SHALL отклонять output, совпадающий с input либо вложенный в tokenizer assets. Отчёт SHALL показывать document/chunk counts и проверенные token maxima без полного содержимого. Проверки SHALL включать реальные локальные E5 assets и сохранность evidence frozen corpus; source coverage SHALL NOT заявляться как retrieval Hit@5.

#### Scenario: Failed processing or write
- **WHEN** chunking либо запись output завершается ошибкой
- **THEN** прежний output и входной snapshot остаются неизменными, частичный output не публикуется

#### Scenario: Frozen corpus verification
- **WHEN** frozen live reference и synthetic snapshot обработаны локальным E5 tokenizer
- **THEN** проверены все input budgets, source slices и сохранность evidence/команд раздельно по source set и split; corpus и holdout не изменяются, retrieval качество не заявляется
