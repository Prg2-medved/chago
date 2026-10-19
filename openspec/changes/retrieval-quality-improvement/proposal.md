# Proposal

## Why

После технически завершённого lexical/hybrid этапа live single-question evidence Hit@5 составляет 6/12 (50%), а обязательный MVP порог ≥90% не достигнут. Диагностика показывает одновременно недостаточный recall, потери при candidate selection и структурный предел q03 (минимум шесть chunks); раскрытый holdout больше не даёт независимой оценки нового решения.

Development v1 завершился отрицательным результатом: все 36 комбинаций дали максимум 6/9 tuning, stop condition 5.2 зафиксирован в `docs/retrieval-quality-result.md`. Расширение после review разрешает ровно один эксперимент final ranking: на legacy inventory при S=120/L=1 и literal v1 evidence q02 и q07 уже покрывается candidate union, но не final top-5. L=20, literal v2 и новый inventory для этого механизма не требуются.

## What Changes

- Первый обязательный gate каждой development фазы — versioned experiment protocol: исходный tuning допускается для выбора, исторический holdout — только для финального отчёта после lock. V1 и его receipt/results сохраняются; новый `docs/retrieval-quality-experiment-protocol-v2.md` отдельно фиксирует единственный cross-encoder experiment. Отсутствие independent evaluator/package не блокирует development, но блокирует independent acceptance.
- Добавить проверку структурной достижимости полного evidence Hit@5, отдельно от branch recall и final ranking. Сохранять protocol v1, все expectations и denominator 12: порог требует минимум 11/12.
- Проверить минимальную общую политику совместной упаковки соседних prose и короткого code block в одном разделе с прежними бюджетами 350/450/512. Это кандидат устранения границы q03, а не обещание его hit.
- Добавить версионированную literal policy для полных underscore identifiers; проверить ограниченную заранее объявленную сетку candidate limits при прежнем RRF. Выбирать минимальный вариант только по разрешённым development данным и ablation, без case-specific правил. Потеря отдельных legacy tuning hits фиксируется, но не исключает кандидата; при равном итоговом качестве предпочтение получает вариант без таких регрессий.
- Создавать отдельные snapshots/reports с fingerprints, полной source provenance, сравнением трёх режимов, регрессиями и измерениями CPU/RAM на целевом сервере. Порядок финальных проверок: lock → frozen v1 → target-server acceptance → independent validation. При провале любого обязательного предшествующего gate закрытый validation package не вскрывается и не запускается; quality acceptance остаётся открытым.
- После закрытой сетки v1 проверить один opt-in локальный CPU cross-encoder `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` на закреплённой revision, FP32, без обучения/quantization/model search. Полный union legacy S=120/L=1 содержит максимум 121 chunk; baseline RRF=60, final k=6 и evidence scorer Hit@5 неизменны. Один кандидат сравнивается с legacy 10/1/60/6 и RRF-контролем 120/1/60/6; никаких новых weights/boosts/literal policies. Остановка при <8/9 либо нарушении обязательных integrity/input/resource/reproducibility gates; ≥8/9 не заменяет финальную приёмку.

## Capabilities

### New Capabilities

Нет: используются существующие границы компонентов.

### Modified Capabilities

- `markdown-chunking`: явный versioned вариант упаковки соседнего prose/короткого code с сохранением структурных границ и жёстких budgets.
- `lexical-retrieval`: дополнительная literal policy для underscore identifiers с воспроизведением legacy policy.
- `hybrid-retrieval`: диагностика достижимости/recall/ranking, явный ограниченный reranking mode с сохранением RRF/defaults, versioned experiments и quality acceptance нового этапа.
- `rag-evaluation-corpus`: методика независимой оценки после раскрытия holdout без изменения frozen corpus v1.

## Impact

Планируемые точки изменения: `app/app/chunking.py`, lexical policy/storage validation, существующие retrieval comparison/evaluation и их ближайшие tests; расширение v2 затрагивает только opt-in final ranking и отчётность. Исторические packing/literal результаты и snapshots сохраняются. V2 использует прежний read-only legacy snapshot без rebuild chunks/embeddings/FTS. SQLite/FTS5, CPU E5, RRF baseline/defaults сохраняются; добавляется один CPU model artifact на существующем PyTorch/Transformers stack, без новых зависимостей, rewriting, словарей под вопросы, внешних сервисов и постоянных процессов. Размер weights около 471 MB не является оценкой runtime RSS или доказательством прохождения latency gate.

Основание: `SPEC.md` §§8, 12.5, 27, этап 4а; `ROADMAP.md` этап 9; `docs/lexical-and-hybrid-retrieval-diagnostics.md`, `docs/lexical-and-hybrid-retrieval.md`, серверная приёмка предыдущего этапа. Это planning change: generation, RAG API/UI, runtime follow-up и atomic-full-reindex вне scope. README, ROADMAP, main specs и архив предыдущего change сейчас не меняются.
