# Proposal

## Why

После завершённого и архивированного `wikijs-markdown-ingestion` доступен deterministic `wiki-documents.json` из 24 реальных Markdown-страниц. До выбора chunking и retrieval нужен фиксированный контрольный набор: совпадение страницы без нужного фрагмента не позволяет объективно оценивать качество будущего RAG.

## What Changes

- Подготовить около 20 контрольных вопросов в `eval/questions.yaml` по прочитанному реальному snapshot согласно SPEC.md §§26–28, включая четыре обязательных стартовых вопроса. Это целевой размер, а не жёсткий schema constraint.
- Зафиксировать ожидаемые страницы, точные фрагменты, 1–3 обязательных факта, дословные команды и все источники составных вопросов независимо от будущих chunk IDs.
- Покрыть follow-up, отсутствие ответа, частичный ответ, неоднозначность, технические identifiers, code blocks, таблицы, противоречия и prompt injection. Для каждой специальной категории сначала проверить весь live reference; synthetic fixture добавлять только для конкретной обязательной категории с подтверждённым отсутствием подходящего материала. Не создавать synthetic дубликаты реальных случаев.
- Зафиксировать версию и fingerprint снимка, tuning/holdout split, offline validation corpus и простой протокол будущей оценки полноты top-5 и grounded answers. Порог MVP Hit@5 ≥90% относится только к answerable live cases с evidence; synthetic результаты и tuning/holdout показываются отдельно.
- Документировать воспроизводимую подготовку и проверки без evaluation-платформы и LLM-судьи.

## Capabilities

### New Capabilities

- `rag-evaluation-corpus`: фиксированный, проверяемый offline набор вопросов и ожидаемых свидетельств для сравнения будущих chunking/retrieval и приёмки ответов.

### Modified Capabilities

Нет. Контракт ingestion и существующие HTTP/LLM возможности сохраняются.

## Impact

При реализации появятся `eval/questions.yaml`, manifest и локальная frozen reference copy snapshot, при необходимости synthetic fixtures, `docs/rag-evaluation-corpus.md`, небольшой типизированный offline validator `app/app/evaluation.py` и целевые тесты `app/tests/test_evaluation.py`. Реальные документы остаются локальными вне Git; версия manifest и разметка отслеживаются отдельно. Для YAML предпочтителен JSON-compatible YAML без новой зависимости. Chunking, embeddings, SQLite, retrieval runner, RAG endpoint, UI и генерация ответов не входят в change. `README.md` и `ROADMAP.md` не изменяются.
