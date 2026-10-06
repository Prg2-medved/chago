# Design

## Context

См. proposal.md для мотивации. `app/app/ingestion.py` содержит frozen dataclass Document и snapshot schema_version 1: source плюс documents, отсортированные по page_id. Markdown сохраняется без нормализации, hash вычисляется по UTF-8. `app/app/evaluation.py` уже проверяет frozen snapshot и evidence в полуоткрытых Unicode ranges, но его loader связан с manifest; chunker не должен требовать evaluation package для обычного запуска.

`eval/manifest.json` описывает 24 live страницы (`data/eval/1/wiki-documents.json`) и отдельный synthetic snapshot (`eval/fixtures/wiki-documents.json`). `docs/rag-evaluation-corpus.md` фиксирует реальные code/table/long-code cases и отдельный injection fixture. requirements.txt пока содержит только FastAPI, uvicorn, psycopg: tokenizer и chunking отсутствуют. Compose app имеет data mount, но не tokenizer mount. SPEC §30 группирует chunking и SQLite, тогда как выбранный Brief §5 выделяет chunking отдельно: этот change заканчивается JSON output, хранение и atomic reindex относятся к следующим этапам roadmap.

## Goals / Non-Goals

**Goals:** lossless source mapping, ограниченный E5 passage, стабильный формат для последующего SQLite и проверяемые фрагменты для цитирования. Минимальное typed implementation в новом chunking module с изолированными CLI settings.

**Non-Goals:** общий Markdown renderer/AST framework, интерпретация изображений/HTML, определение смысла shell scripts, изменение frozen corpus и настройка retrieval по holdout. Chunker не выполняет код и не определяет достаточность ответа.

## Decisions

### 1. Локальный tokenizer-only adapter

Использовать минимальную закреплённую зависимость `tokenizers` с локальным E5 `tokenizer.json`, без transformers/sentence-transformers/Torch и без model weights. Adapter загружает только файл из явно заданного каталога, отключает truncation/padding и использует сохранённый E5 special-token postprocessor. Фиксировать model ID `intfloat/multilingual-e5-small` и конкретную immutable model revision (полный commit ID); плавающий `main`, branch или tag не допускается. В output сохранять эту identity, SHA-256/fingerprint фактически используемых tokenizer assets и фактическую версию Python package `tokenizers`, совпадающую с pinned dependency. Конкретные revision и fingerprints определить при apply после проверки реально установленных assets и их происхождения; до подтверждения identity реальные assets не считать принятыми. Установка assets — обслуживаемая предварительная операция; runtime Hub/network fallback отсутствует. Реальный smoke проверяет соответствие assets зафиксированной revision и подсчёт с special tokens.

Будущий embedding stage должен использовать совместимый tokenizer той же model ID и immutable model revision, чтобы token budget chunking совпадал с фактической токенизацией embeddings. Сохранённые identity/fingerprint/package version служат основанием проверки совместимости; несовместимые assets требуют согласования и повторного chunking, а не молчаливого использования старого budget. Embeddings в этом change не реализуются.

Словесный/символьный estimator не обеспечивает лимит E5; полный embedding runtime избыточен на этом этапе. В tests допускается небольшой fake counter для структурных edge cases, но E5 budget acceptance выполняется только настоящими локальными assets.

Формат input единый: `passage: {title}\n{heading path joined with ' > '}\n{search_text}`. Пустой heading path оставляет пустую строку. Подсчёт body включает всё search_text, в том числе повторённые headers/fences; полный input включает special tokens. Settings: target=350, max=450, overlap=50, input_limit=512. Проверять 0 <= overlap < target <= max <= 450; input_limit нельзя поднять выше 512. Нельзя вычитать независимые token counts как точный бюджет: после каждой сборки проверяется весь input. Metadata не обрезается; невозможность поместить metadata плюс следующий минимальный фрагмент — budget error.

### 2. Source-preserving line scanner

Разобрать Markdown через строки с сохранением endings и исходных Unicode offsets. Stateful scanner распознаёт ATX/Setext headings, fenced blocks с backticks/tilde и pipe tables; headings внутри fences игнорируются. Проверять fence character/length, поддерживать info string, незакрытый fence сохранять до конца страницы. У таблиц учитывать escaped pipes и inline code при поиске границ ячеек. Unsupported/nested constructs сохраняются дословно как text, включая indented code и списки; синтаксис не переписывается.

Каждый исходный символ принадлежит хотя бы одному source segment, включая headings, fences и межблочные пробелы. Section heading lines входят в первые source segments своего раздела; heading-only страницы также дают chunks. Heading stack снимает уровни >= нового и не выдумывает отсутствующие уровни. Преамбула имеет пустой path. Не объединять разные heading paths. Полный AST/parser с повторным рендерингом сложнее и рискует изменить команды/whitespace; source scanner покрывает требуемую структуру и оставляет lossless fallback.

### 3. Упаковка и overlap с гарантией продвижения

Упаковывать последовательные blocks одного раздела примерно до target. Целый короткий code block или table row можно оставить выше target, если выполнены оба hard budgets. Oversized prose делить по абзацам/строкам, затем по Unicode boundaries; oversized code — по строкам, затем по Unicode boundaries без decode/re-encode token slices. Не предполагать монотонность BPE counts; проверять кандидаты и окончательный input, гарантировать положительное продвижение и завершение для каждого исходного символа.

Overlap около 50 body tokens брать из suffix обычного текста внутри раздела, с точными source ranges, только если остаётся место для нового контента. Не разрезать fitting code/table ради overlap; не дублировать code/table fragments как overlap. Если overlap мешает прогрессу/лимиту, уменьшить или убрать. Размеры структурных chunks могут быть ниже target — это допустимо. Повторение исходных ranges из-за overlap отличается от добавленного поискового контекста.

### 4. Два представления chunk и связи продолжений

Typed Chunk содержит metadata из spec, source ranges, ordered segments с kind=source/generated и search_text, body/input token counts. Generated segment содержит текст и reason (table_header/fence/separator), source segment — start/end и роль. Дословная цитата берётся только из documents.markdown[start:end]; search_text нельзя целиком выдавать за source quote.

Code fragments хранят block_id, part_index и continuation flags; разрыв внутри строки отмечается отдельно. Для разделённого multiline блока консервативно все его части маркируются как требующие исходного блока для подтверждения полной команды: парсер shell не нужен. Для таблиц хранить table_id, row identity и part order; header/separator повторяются как generated segments после первого появления. Длинную строку/ячейку разделять source slices без потери текста, обрамление частей — generated. Если даже header плюс минимальная часть не помещается, вернуть error, а не выпустить неподписанные значения.

Output schema_version 1 содержит algorithm_version, tokenizer model ID/immutable revision/assets fingerprint/package version, settings, неизменённые documents и chunks. Chunk ID — SHA-256 канонического объекта из source origin, page_id, content hash, metadata, algorithm/settings/tokenizer identity (включая revision, assets fingerprint и package version), chunk ordinal и segment description. Source namespace предотвращает live/synthetic collisions; metadata включена, чтобы rename менял artifact identity. Стабильная сортировка по source/page_id/ordinal, UTF-8 JSON с фиксированным форматированием и без run timestamps. Это versioned производный artifact, не расширение ingestion snapshot.

### 5. Изолированный CLI и воспроизводимая приёмка

Новый `python -m app.chunking` читает snapshot с newline preservation, проверяет schema/hash/types/identity, загружает tokenizer только при запуске CLI, затем пишет проверенный полный JSON через temporary file в output directory и atomic replace. Не импортировать heavyweight tokenizer в HTTP startup. Отказать при совпадении resolved input/output, aliases/hardlinks и output внутри tokenizer directory; не перезаписывать assets. Ошибки имеют controlled category и page_id/ordinal при необходимости без source text.

`docs/markdown-chunking.md` содержит installation assets, local/Compose commands и acceptance evidence. Минимальная схема Compose: хранить assets в `data/tokenizers/<immutable-revision>/`, доступном CLI как `/data/tokenizers/<immutable-revision>/` через существующий `./data:/data`. Отдельный постоянный tokenizer mount в service app не добавлять; Compose configuration менять не требуется. Adapter читает assets без записи, CLI проверяет их наличие и identity при запуске и выдаёт controlled error при отсутствии. Обычный FastAPI startup/health не проверяет tokenizer path и не зависит от tokenizer files; отсутствие assets не должно блокировать запуск container app. `.env.example` при необходимости описывает CLI path, но его validation не входит в HTTP settings. README/ROADMAP не менять.

Проверки используют существующие fixtures и frozen reference без их изменения. Отдельный test/helper проверяет union source ranges, восстановление source blocks, точные команды, generated/source separation и присутствие всех evidence spans в совокупности chunks нужного источника. Структурное пересечение chunks с evidence не является retrieval score. Разделять live/synthetic и tuning/holdout; holdout использовать для итоговой проверки сохранности, не для подбора параметров. В docs записать counts, maxima, fingerprints и вручную проверенные безопасные Bash/table/long-code примеры без полного корпуса и credentials.

## Risks / Trade-offs

- [Локальные E5 assets могут отсутствовать] → документировать предварительную установку; реальную tokenizer acceptance оставлять незавершённой до успешного offline smoke.
- [Сложные Markdown extensions] → lossless text fallback и fixtures на fenced/Setext/escaped-pipe случаи; не обещать полную CommonMark rendering совместимость.
- [Большие metadata/table headers не помещаются] → controlled budget error с неизменным output; никакого скрытого сокращения источника.
- [Части команды могут выглядеть как готовая команда] → continuation metadata и консервативный complete-block flag для downstream citations.
- [Повторный token count длинных страниц может быть дорогим] → кэшировать одинаковые кандидаты, ограничить повторные проходы и измерить время/память на frozen corpus и большой fixture; не добавлять сервисы/очереди.
- [В Markdown reference есть чувствительные данные] → выводить только counts/IDs и безопасные выбранные примеры, производные файлы хранить в ignored data/.

## Migration Plan

После apply установить pinned tokenizer dependency и локальные E5 assets, выполнить targeted tests и CLI сначала на fixtures, затем на frozen reference. Новый output размещать отдельно в data/, не заменять ingestion или corpus. Никакой миграции БД нет. Rollback — удалить производный chunks output и вернуть новые module/config/dependency изменения; исходные snapshots сохраняются.
