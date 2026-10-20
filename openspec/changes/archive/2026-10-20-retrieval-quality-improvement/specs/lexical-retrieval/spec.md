# Spec Delta

## ADDED Requirements

### Requirement: Versioned underscore identifier literals
Система SHALL поддерживать дополнительную явно выбираемую literal policy v2 для полных технических identifiers с underscore, сохраняя spelling, регистр, longest non-overlapping extraction и существующие правила quoted fragments, IP, paths и hyphen identifiers. Совпадение SHALL подтверждаться непрерывным original source range с проверкой границ полного значения; title/heading/generated text сами по себе SHALL NOT давать exact priority. BM25, порядок literal priority, безопасный MATCH и отсутствие morphological expansion/synonyms/rewriting SHALL сохраняться.

#### Scenario: Explicit field names
- **WHEN** вопрос содержит `charge_device_id` и `clear_device_id`, а исходный текст chunk содержит эти полные identifiers
- **THEN** policy v2 распознаёт оба literals и возвращает их проверяемые original source ranges до lexical top-k truncation

#### Scenario: Similar identifier or generated occurrence
- **WHEN** исходник содержит только `charge_device_id_extra` либо полное значение имеется лишь в generated segment
- **THEN** chunk не получает exact priority за `charge_device_id`

### Requirement: Explicit literal policy compatibility
Lexical build SHALL фиксировать выбранную literal policy в metadata отдельного output snapshot. Query SHALL применять именно поддерживаемую policy snapshot; v1 SHALL сохранять прежний ranking, v2 SHALL использовать новое extraction behavior, неизвестная версия SHALL отклоняться без fallback и изменения файла. Literal-only rebuild SHALL сохранять base documents/chunks/provenance и raw embeddings; policy SHALL фиксироваться в report fingerprints/identity. Legacy defaults SHALL сохраняться до явного выбора нового snapshot.

#### Scenario: Reproduce old policy
- **WHEN** старый v1 snapshot открыт новой реализацией
- **THEN** extraction/ranking соответствует v1 без автоматического перехода на v2

#### Scenario: Build new policy or reject unknown policy
- **WHEN** отдельно построен v2 snapshot либо открыт snapshot с неизвестной policy
- **THEN** соответственно применяется v2 с неизменными base/vector bytes либо запрос завершается безопасной ошибкой; inputs и прежние snapshots сохраняются
