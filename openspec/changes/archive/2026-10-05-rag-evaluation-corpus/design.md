# Design

## Context

См. proposal.md — Why. `openspec/changes/archive/2026-10-05-wikijs-markdown-ingestion/tasks.md` полностью завершён; `docs/wikijs-markdown-ingestion.md` фиксирует live corpus из 24 страниц, 276756 bytes и повторяемость snapshot. Полный fingerprint в evidence не приведён. Реальные названия, пути и содержимое snapshot в доступных документах отсутствуют, `data/wiki-documents.json` локально отсутствует. Поэтому этот план не придумывает вопросы с несуществующими цитатами: получение reference и чтение всех 24 страниц — конкретная первая задача apply, без повторной разработки ingestion.

`app/app/ingestion.py` уже сохраняет schema_version=1, source и documents, сортирует page_id, сохраняет lossless Markdown и SHA-256 UTF-8. Документы содержат page_id/locale/path/title/source_url/updated_at/markdown/content_sha256. `data/` исключён из Git. Существуют offline pytest и stdlib JSON; YAML parser отсутствует. Chunking, индекс и retrieval ещё не реализованы. Новых требований к ingestion нет; число «около 20 страниц» в SPEC является оценкой, фактические 24 не противоречат ей.

## Goals / Non-Goals

**Goals:** фиксировать ожидания в координатах исходного Markdown, сохранять сопоставимость при изменении chunking, отличать integrity от семантической ручной проверки, обеспечить offline validation.

**Non-Goals:** определять chunk IDs, строить chunking/retrieval/индекс, измерять несуществующую систему, выполнять LLM calls, создавать полноценный evaluation framework или изменять runtime приложения.

## Decisions

### 1. Версионированный пакет и frozen reference

Отслеживать `eval/questions.yaml`, `eval/manifest.json` и `eval/fixtures/wiki-documents.json` при необходимости (только подтверждённо отсутствующие обязательные специальные категории). Сохранить byte-for-byte reference live snapshot в `data/eval/<corpus-version>/wiki-documents.json`, отдельный от текущего `data/wiki-documents.json`. Manifest: schema_version=1, corpus_version (начально 1), live snapshot SHA-256 bytes, source, document_count=24 и перечень page_id/locale/path/content_sha256; при наличии synthetic snapshot он имеет собственный fingerprint и source namespace `synthetic`. Версия questions обязана совпадать с manifest. Пути reference передаются явно, без machine-specific абсолютных путей в Git.

Не коммитить полный live snapshot; для повторения на другой машине передавать ту же reference copy локально по существующему доверенному каналу. Минимальные реальные вопросы/paths/цитаты нужны для corpus, но credentials/DSN/password в них запрещены; выбирать безопасные фрагменты. Если нужное свидетельство содержит secret, не заменять его фиктивной цитатой: выбрать другой вопрос/безопасный достаточный диапазон и записать ограничение. Альтернатива — обращаться к текущей Wiki.js при каждом запуске — делает сравнение невоспроизводимым. Архивный evidence не заменяет реальную reference copy.

### 2. Простой YAML-compatible формат без зависимости

Использовать JSON syntax в UTF-8 `questions.yaml` (JSON-compatible YAML), читать через stdlib `json`, документировать этот поддерживаемый поднабор. Это удовлетворяет требуемому пути и избегает установки YAML parser ради одного списка. Произвольный block-style YAML не поддерживать и выдавать понятную ошибку формата. Расширение до полного YAML — отдельная потребность, не часть этапа.

Верхний объект: schema_version, corpus_version, questions. Каждая запись: id, question, tags, split (`tuning`/`holdout`), source_set (`live`/`synthetic`), answerable (bool), expected_behavior (`answer`, `partial_answer`, `refuse`, `clarify`, `report_conflict`), previous_question для follow-up, required_facts, missing_information для partial_answer, clarification для clarify и evidence. Полностью неизвестные и clarification-only вопросы: answerable=false, facts/evidence пустые; partial_answer и report_conflict: answerable=true и непустые evidence/facts. Предыдущий вопрос хранить строкой, без зависимости от tuning case; прошлый ответ не является источником.

Evidence: стабильный id, page_id/locale/path/content_sha256, heading_path при наличии и spans. Span: start/end (полуоткрытые индексы Unicode code points в decoded Markdown без newline normalization), exact_text. Минимум один span; heading locator помогает чтению, но не заменяет диапазон содержащих ответ сведений. Факт связывается с одним или несколькими evidence IDs; обязательные команды дополнительно хранят exact_commands. Повторяющиеся цитаты различать диапазоном. Для таблицы фиксировать header и нужную строку; для длинного блока — необходимые последовательные spans с привязкой к исходному блоку. Это позволяет позднее проверить содержимое нескольких chunks, не требуя весь длинный блок в одном chunk. Полные команды сохранять отдельно дословно; части не считать полной командой.

Альтернативы: page-only labels слишком слабы; фиксированные chunk IDs привязывают оценку к одному chunker; substring без диапазона неоднозначен при повторениях.

### 3. Ручная разметка и coverage

Около 20 вопросов — целевой размер corpus, включая необходимые synthetic cases, а не жёсткий schema constraint. Само по себе отклонение от цели, включая выход за диапазон 18–24, не вызывает structural validation failure. Validator сообщает фактический count и жёстко проверяет обязательное coverage, evidence, IDs, split и остальные инварианты. 3–5 полностью unanswerable `refuse` cases; clarify и partial_answer не подменяют эту квоту. Несколько follow-up означает минимум два. Категории могут пересекаться. Четыре вопроса SPEC §28 сохранять дословно и размечать по прочитанным страницам; не считать все четыре answerable заранее. Проверить отсутствие ответа во всём reference, а не только на выбранной странице. Составные вопросы и противоречия перечисляют все evidence.

Для каждой обязательной специальной категории сначала проверить весь live reference: code/table/identifier/long-code/conflict/injection. Зафиксировать в coverage таблице найденные live evidence либо подтверждённое отсутствие подходящего материала конкретной категории. Synthetic fixture разрешён только для такой отсутствующей категории; synthetic дубликат существующего подходящего реального случая запрещён. Использовать минимальные synthetic страницы отдельного snapshot с тем же document shape и уникальными IDs внутри synthetic namespace; URL вида `https://wiki.example/ru/...` явно обозначать тестовым. Не добавлять документы в рабочую Wiki.js или live ingestion. Synthetic corpus используется отдельным будущим прогоном chunking/retrieval. Он не увеличивает live corpus до фиктивного числа страниц. Если всё обязательное coverage обеспечено live материалом, synthetic cases и snapshot не создаются, synthetic fingerprint в manifest не требуется. Это правило относится к evaluation corpus; вымышленные данные unit tests остаются допустимыми.

Семантику вопросов, необходимые факты и ожидаемое поведение проверяет разработчик по Markdown; спорные случаи передаются владельцу документации для проверки, не требуют заранее полного эталонного ответа. До разрешения спора конкретный case не считается принятым. Набор остаётся небольшим, ручная таблица coverage предпочтительнее генерации вопросов LLM.

### 4. Offline validator с явными inputs

Планируемый модуль `app/app/evaluation.py` запускается из `app/`:

```sh
python -m app.evaluation --questions ../eval/questions.yaml --manifest ../eval/manifest.json --snapshot ../data/eval/1/wiki-documents.json --fixtures ../eval/fixtures/wiki-documents.json
```

При отсутствии synthetic cases параметр `--fixtures` опускается; при их наличии snapshot и его fingerprint обязательны. CLI только читает файлы, не импортирует DB transport для выполнения запросов и не требует ingestion environment. Типизированная validation проверяет schema/types (bool не integer), nonempty/unique IDs, versions, split, обязательное coverage без жёсткого общего count вопросов, snapshot schema/source/положительные уникальные IDs и hashes, соответствие manifest, references, диапазоны и exact_text/commands. Применять существующий document contract; не переделывать ingestion ради общей абстракции. Не выполнять Markdown parser, tokenization или semantic judging. Успех: counts по категориям, source_set и split и fingerprints; ошибка: категория и case ID без полного source текста. Тесты используют synthetic reference и mutation inputs, а не рабочие документы.

Альтернативы: pytest-only проверки затрудняют проверку реального локального snapshot; новая платформа и LLM-судья не нужны. Validator необходим для выявления drift и ошибочной разметки, но не доказывает истинность фактов.

### 5. Фиксированный split и протокол следующих этапов

Заранее назначить не менее четырёх holdout cases, включая answerable и unanswerable; tuning также имеет answerable случаи. Holdout помечен в файле, организационно не используется для настройки. Это не технический контроль доступа. Synthetic и live результаты публикуются отдельно.

В `docs/rag-evaluation-corpus.md` определить будущий live Hit@5 = число answerable live cases с evidence, для которых совокупность top-5 покрывает все обязательные spans с правильной source identity, / число соответствующих answerable live cases с evidence. Synthetic cases не входят ни в числитель, ни в знаменатель основной live метрики. Partial cases проверяют только доступную часть; clarify/refuse исключены. Разбиение длинного evidence между chunks допустимо лишь при полном покрытии нужных spans в пределах top-5; metadata heading/repeated table header не заменяет исходные данные. Сопоставление по исходным диапазонам или ручной сверке exact text, без фиксированного chunk ID. Порог MVP Hit@5 ≥90% относится только к соответствующим answerable live cases. Приводить числитель/знаменатель общего live набора и раздельно live tuning/holdout. Synthetic edge cases и их результаты показывать отдельно, также раздельно tuning/holdout; synthetic успех не компенсирует live misses. Не утверждать, что порог достигнут до retrieval.

Шаблон будущего отчёта: corpus/reference hash, split/source_set, chunking/retrieval versions и параметры, case ID, покрытые/пропущенные evidence, hit/miss, ручные факты/citations/commands/refusal/conflict/injection checks. Ни scorer, ни retrieval runner на этом этапе не реализуются. При финальной проверке все полностью unanswerable должны отказаться от выдуманного содержательного ответа. Набор допускает явную версионированную доработку перед приёмкой, но смена reference или holdout после просмотра результатов фиксируется и требует нового сравнения.

## Risks / Trade-offs

- [Live snapshot недоступен локально] → Получить именно frozen полный файл на apply и прочитать страницы; не отмечать corpus готовым по одному evidence ingestion.
- [Структурная проверка пропускает неверный смысл] → Ручная сверка всех фактов и absent-answer labels; спорные примеры подтверждает владелец.
- [Документы обновляются] → Snapshot хранится отдельно, manifest проверяет fingerprint; refresh только новой версией с повторной разметкой.
- [Малый holdout и видимые вопросы] → Фиксировать split до tuning, публиковать counts и ограничение малого набора; успех не гарантирует качество любых будущих вопросов.
- [JSON syntax менее удобен для ручного YAML] → Документировать supported subset и Unicode pretty formatting; сохранить stdlib-only решение.
- [Sensitive текст в разметке] → Использовать минимальные безопасные свидетельства, исключить credentials и не коммитить полный live snapshot.

## Migration Plan

Миграций runtime и БД нет. На apply получить и отдельно сохранить reference, составить/проверить разметку, добавить validator/tests/docs и выполнить offline CLI дважды. Зафиксировать ручной review и fingerprint без полных документов. Повторить проверку после передачи reference на другую машину при необходимости. Откат — убрать новые corpus/validator файлы; ingestion и приложение работают как прежде. Все implementation tasks остаются незавершёнными до фактического исполнения.

## Open Questions

Конкретные live page paths, quotes, наличие реальных конфликтов и специальных Markdown-примеров определяются чтением 24 страниц на apply. Это выбор содержимого внутри фиксированного coverage-контракта, не изменение архитектуры; synthetic fallback применяется только для конкретной обязательной категории после подтверждения отсутствия подходящего материала во всём live reference, без дублирования реальных случаев. Местонахождение доступной reference copy на целевом сервере нужно уточнять при apply, если файл не предоставлен в workspace.
