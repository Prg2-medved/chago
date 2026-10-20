# Spec Delta

## ADDED Requirements

### Requirement: Versioned adjacent prose and code packing
Система SHALL предоставлять явно выбираемый новый вариант chunking для совместной упаковки непосредственно соседних pending prose и целого короткого fenced code block одного heading path. Объединение SHALL выполняться только при body ≤450 tokens и полном E5 input ≤512 tokens; target 350 SHALL оставаться ориентиром. При смене раздела/страницы или недостаточном budget SHALL сохраняться раздельная выдача. Tables, длинные blocks и их continuation semantics SHALL сохранять существующий контракт. Policy SHALL NOT зависеть от evaluation ID, page ID, пути, evidence offsets или текста конкретного вопроса.

#### Scenario: Adjacent explanation and command fit
- **WHEN** непосредственно предшествующий prose и короткий code block в одном разделе совместно помещаются в жёсткие budgets
- **THEN** новый вариант выдаёт один chunk с дословными source segments обоих блоков и metadata целого code block

#### Scenario: Budget or structural boundary prevents packing
- **WHEN** объединение превышает body/input limit либо соседний блок имеет иной heading path или страницу
- **THEN** блоки остаются раздельными без truncation, переноса текста между разделами или потери evidence

### Requirement: Reproducible alternative chunk inventory
Новый вариант SHALL сохранять source namespace, неизменные documents, Unicode ranges и различение source/generated segments, фиксировать отдельную algorithm identity и создавать воспроизводимые IDs с учётом этой identity. Явный legacy вариант SHALL воспроизводить прежние chunks/IDs на прежних inputs. Новый output SHALL храниться отдельно; изменение inventory SHALL требовать новых соответствующих embeddings, без использования старых vectors по прежним IDs. Полное source coverage SHALL NOT заявляться как retrieval hit.

#### Scenario: Legacy and new variants coexist
- **WHEN** один frozen reference обрабатывается legacy и новым вариантом
- **THEN** outputs различаются versioned identity, прежний вариант воспроизводим, reference не меняется, каждый новый passage проверен реальным совместимым локальным tokenizer

#### Scenario: Structural improvement is insufficient
- **WHEN** новое inventory позволяет покрыть evidence пятью chunks, но поисковая выдача не содержит их все среди top 5
- **THEN** структурная проверка успешна, а retrieval case остаётся miss
