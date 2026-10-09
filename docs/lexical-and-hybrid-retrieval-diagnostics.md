# Диагностика evidence retrieval и передача quality acceptance

Дата: 2026-10-09. Change: `lexical-and-hybrid-retrieval`.

## Результат и решение владельца

Hybrid live single-question evidence Hit@5 — **6/12 (50%)**, tuning 6/9,
holdout 0/3. Follow-up — 0/1 в каждом split, synthetic — 1/1; они не входят
в основной denominator. Miss IDs: **q02, q03, q04, q07, q08, q18**.
Обязательный MVP порог **≥90% не достигнут**, quality acceptance не пройден.

Техническая реализация завершена, фактическая серверная приёмка подтверждена
[отчётом оператора](lexical-and-hybrid-retrieval-server-acceptance.md#фактический-серверный-отчёт-2026-10-09).
По принятому решению владельца технический change завершается отдельно от
качества. Историческая задача 5.5 «подтвердить ≥90%» не была выполнена и
оставалась открытой до этого решения. Её актуальный критерий — документировать
провал, диагностику и передачу достижения ≥90% следующему самостоятельному
этапу `retrieval-quality-improvement` в [ROADMAP](../ROADMAP.md).
[SPEC](../SPEC.md) §§12.5, 27 и этап 4а сохраняют обязательный порог MVP.
Закрытие tasks и архивирование технического change не означают достижения
quality acceptance; новая функциональность требует отдельного proposal/design.

Перед архивированием OpenSpec подтвердил `all_done`, 25/25 актуальных критериев
tasks. [Архивированный change](../openspec/changes/archive/2026-10-09-lexical-and-hybrid-retrieval/tasks.md)
сохраняет первоначальный невыполненный критерий 5.5 и основание его пересмотра;
delta specs синхронизированы с main specs. Следующий минимальный шаг — создать
новый proposal по brief этапа 9 ROADMAP, а не менять этот архив.

## Артефакты и метод проверки

Основание — неизменённый [comparison baseline](lexical-and-hybrid-retrieval-baseline.json),
`data/hybrid-final-1.json`, `data/hybrid-final-2.json`, существующие frozen
`eval/questions.yaml`, `eval/manifest.json`, `data/eval/1/wiki-documents.json`
и `data/hybrid-live.db` (24 pages, 910 chunks). Выбранная до final holdout
конфигурация — **10 semantic / 1 lexical / RRF 60 / query top-k 6**.
API defaults остаются 10/10/60/6. Evaluation запрашивает и учитывает top 5.

| Вход | SHA-256 |
| --- | --- |
| Questions / expectations | `916c65e0e589a27e86b9afafdc91c6cad6c4b3ecbad8ab941f5af87bd1e14181` |
| Manifest | `9cea48706b1d4118c0a57cd88cce009f3f1ee6576c8b9c3d0dbd84bcec06c3a3` |
| Frozen live reference | `63ad12fec898ef6c73c5c37a66d18e0d1327c91f1f79102dfa646cadd8c9f95f` |
| Hybrid live snapshot | `87fa5e9b2af30044a509d19c16440db2545d5941f0eab3d3795a9e6af7d2fa44` |
| Сохранённый comparison baseline | `d616ab6b53722654edb2aba53ba7bf979383200a5692f4cbaf6bf39a41353a69` |

Saved reports содержат только top-5, поэтому глубокие позиции ниже восстановлены
диагностически на тех же сохранённых embeddings, прежней локальной E5 и
действующей lexical policy. Полные branch rankings вычислялись только для
прослеживания evidence; при fusion применялись зафиксированные limits 10/1
и RRF=60. Top-5 и scores точно совпали с baseline во всех **18 case/mode
сравнениях**. Ни конфигурации-кандидаты, ни новый tuning по holdout не запускались.
Сетевые соединения в диагностическом процессе запрещены, индекс открыт read-only.

Frozen package прошёл validation. Для каждого evidence проверены точный Markdown
slice, page/locale/path/content hash и source namespace. Все указанные chunks
присутствуют в base inventory, FTS и embeddings; отсутствующего индексированного
evidence нет. Минимальное число chunks найдено проверкой всех комбинаций chunks,
пересекающих обязательные spans, с объединением только исходных source ranges.
Generated text не засчитывается. Fingerprints входов и snapshots не изменились.

JSON baseline сохраняет `quality_acceptance.accepted=false`. Его исторический
`verification.target_server.completed=false` предшествует отдельной фактической
серверной приёмке, записанной в документации; baseline не исправлялся задним числом.
Серверные глубокие ranks этим исследованием не измерялись: таблицы ниже относятся
к development snapshot. Предоставленная серверная сводка подтверждает тот же
aggregate и miss IDs, но не заменяет development diagnostics.

## Сравнение причин

| Case / split | Минимум chunks для полного hit | Потеря evidence | Основная причина |
| --- | ---: | --- | --- |
| q02 / tuning | 3 | Ни один нужный chunk не входит в branch candidates: S35/S112/S15, lexical matches отсутствуют | Semantic retrieval и lexical vocabulary gap; candidate limits исключают evidence до RRF |
| q03 / tuning | **6** | Только команды Netplan входят в semantic candidates, но имеют H8; остальные исключены | **Chunking относительно состава evidence: полный Hit@5 структурно невозможен**, дополнительно слабое ранжирование |
| q04 / holdout | 1 | Нужная таблица S95, lexical match отсутствует | Semantic retrieval и сопоставление пользовательской лексики с `device_type`; chunking не разделил нужные данные |
| q07 / tuning | 1 | Нужная таблица S6/L14 есть только в semantic candidates и получает H7 | Literal priority и lexical limit 1 лишают её второго contribution; RRF добавляет preceding chunk |
| q08 / holdout | 2 | Начало первого JSON S12 исключено, продолжение S10 остаётся на H10 | Semantic retrieval выбирает prose и другие части примеров; chunking разделяет обязательный JSON |
| q18 / holdout | 2 | Оба источника в semantic candidates, но получают H6/H8; lexical L20/L11 исключены | Candidate limits и RRF при обязательном двухисточниковом evidence, усиленные literal priority |

## Source ranges и полная трассировка

Ranges — полуоткрытые Unicode offsets `[start,end)` исходного Markdown, end
исключён. Chunk IDs сокращены до уникальных в snapshot первых 12 символов.
S/L — полные semantic/lexical ranks; `∅` означает отсутствие lexical match
во всём inventory, а не позицию за candidate limit. H — позиция в полном RRF
union **до** final truncation; H>5 не даёт Hit@5, H>6 не входит и в default query.
`—` в H означает отсутствие chunk в union.

| Case | Page | Обязательные source ranges, покрываемые chunk | Chunk prefix / ordinal | S | L | В S≤10 | В L≤1 | H |
| --- | ---: | --- | --- | ---: | ---: | --- | --- | ---: |
| q02 | 3 | `[26,132)`, `[134,299)` | `5fa14fd9b8a4` / 0 | 35 | ∅ | нет | нет | — |
| q02 | 3 | `[454,505)` | `8c85ac63277c` / 2 | 112 | ∅ | нет | нет | — |
| q02 | 3 | `[697,725)` | `ca1438980e10` / 5 | 15 | ∅ | нет | нет | — |
| q03 | 43 | `[2782,2807)` | `8bf353aa811b` / 37 | 13 | 103 | нет | нет | — |
| q03 | 43 | `[3437,3473)` | `3752320d65b2` / 41 | 8 | 116 | да | нет | 8 |
| q03 | 43 | `[4382,4445)` | `9df59f583b56` / 64 | 104 | 13 | нет | нет | — |
| q03 | 43 | `[4705,4738)` | `58d5dc365c50` / 66 | 135 | 83 | нет | нет | — |
| q03 | 43 | `[6504,6579)` из обязательного `[6504,6595)` | `086e958d035e` / 92 | 34 | 113 | нет | нет | — |
| q03 | 43 | `[6579,6595)` из обязательного `[6504,6595)` | `92c05caf71f3` / 93 | 26 | 55 | нет | нет | — |
| q04 | 23 | `[1228,1264)`, `[1265,1341)` | `2b03b944e499` / 3 | 95 | ∅ | нет | нет | — |
| q07 | 17 | `[4695,4738)`, `[5424,5516)`, `[5517,5686)` | `ffa4e13a9ecb` / 22 | 6 | 14 | да | нет | 7 |
| q08 | 19 | `[549,1372)` из обязательного `[549,2159)` | `b16a926f583c` / 5 | 12 | 44 | нет | нет | — |
| q08 | 19 | `[1372,2159)` из обязательного `[549,2159)` | `9412e59cbdf9` / 6 | 10 | 46 | да | нет | 10 |
| q18 | 27 | `[2745,2805)`, `[3375,3439)` | `2cf2f3b33c34` / 19 | 5 | 20 | да | нет | 6 |
| q18 | 17 | `[16799,16845)`, `[17230,17274)` | `293994d5b010` / 75 | 7 | 11 | да | нет | 8 |

### q02: общая формулировка и морфология

Lexical query terms — «как», «настроить», «сервер». Title page 3 — «Пользователи
сервера», в нужном prose есть «сервере»; unicode61 не выполняет морфологическое
сопоставление. Нужные команды сами не содержат query terms. Lexical top-1
`7c97b6770501` (page 43, ordinal 108) описывает настройку времени копирования
файлов, а не необходимые spans. Semantic top-5 включает page 3 ordinal 6,
но совпадение страницы не заменяет обязательные ranges. Ни расширение final k,
ни изменение одной RRF constant не добавляет отсутствующее evidence.

### q03: доказательство структурной невозможности

Шесть перечисленных chunks — единственные пересекающие нужные spans на page 43.
Пояснение автоматического запуска и `Power On` в span `[6504,6595)` разделены
границей 6579 между prose и code block. Каждый из шести chunks покрывает часть,
которую не покрывают остальные. Проверка всех комбинаций дала minimum=6;
**даже идеальный ranking пяти chunks не может дать полный hit**. Default query
top-k=6 не меняет evaluation Hit@5. Это ограничение исходного snapshot, а не
основание удалять обязательный факт, менять expectations или считать partial hit.

### q04: таблица есть, query terms отсутствуют

Один chunk содержит header и всю строку `device_type`. Его title — `br-config`,
heading — «типы узлов и устройств», значения — `conveyor`, `lift`, `charger`,
`shuttle`, `rack_conveyor`. Query «Какое оборудование используется в складе?»
не даёт lexical match. Semantic S95 показывает разрыв между общим вопросом и
форматом конфигурационной таблицы. Увеличение lexical limit не может помочь
chunk, не участвующему в этой ветке вообще.

### q07: literal priority вытесняет нужные поля

Raw BM25 rank таблицы — **3**, итоговый lexical rank — **14**. Вопрос содержит
`charge_device_id` и `clear_device_id`, но literal policy v1 не выделяет эти
underscore identifiers. Она извлекает `br-route-plan`; в source ranges таблицы
нет такого полного отдельного literal. Heading path участвует в BM25, но
не служит source-backed literal evidence. Lexical L1 `c518aa36060c` (page 17,
ordinal 21) содержит описание очереди и literal в producer. Он добавляется
в union, и semantic S6 таблицы становится H7. RRF работает по своему контракту.

Сохранённая tuning grid уже содержит q07 hit при 10/20/60, но такой вариант
даёт 5/9 вместо выбранных 6/9: теряются q11 и q19. Это историческое измерение,
а не новый tuning или рекомендация заменить выбранную конфигурацию.

### q08: релевантное prose не покрывает первый JSON

Общий S1/L1 `4c1543e92f5d` (page 19, ordinal 4) покрывает `[187,549)` и
содержит описание действий перед JSON. Его source ranges заканчиваются точно
на начале обязательного `[549,2159)`, не покрывая ни одного символа evidence.
JSON разделён между двумя chunks; начало исключено S limit, продолжение
остаётся H10. Другие части примеров в top-5 не заменяют требуемый первый JSON.

### q18: два конфликтующих источника и одноветочный RRF

Нужно одновременно показать `br-plc.{id}.commands` из page 27 и
`br-plc.{queue_name_callback}.command_status` с producer/consumer из page 17.
Оба chunks есть среди S candidates. Таблица page 27 имеет raw BM25 rank **5**,
но не получает source-backed literal `br-motion` только за title и оказывается
L20. Page 17 получает этот literal и поднимается с raw BM25 **102** до L11.
Оба всё равно исключены limit=1. Lexical L1 `e927e6ef5f2e` (page 22, ordinal 7)
содержит другое упоминание `br-motion`; его одноветочный score `1/61` сдвигает
S5 первого источника в H6. Второй получает H8. Первый входит в default query
top-6, но не в evidence Hit@5, а второго нет даже там. Один источник не
удовлетворяет принятому `report_conflict`.

## Направления для следующего proposal/design

Ниже гипотезы, а не выбранная архитектура или подтверждённые исправления.

| Причина | Минимальное направление исследования | Что оно само по себе не доказывает |
| --- | --- | --- |
| q02/q04: vocabulary gap и слабый recall | Сопоставление терминов, морфологии и контекста раздела | Увеличение candidate limits не гарантирует релевантный top-5 |
| q03: minimum 6 chunks | Структурные границы коротких prose/code фрагментов; минимум одна необходимая пара должна стать совместно доступной в пределах пяти результатов | Устранение структурной невозможности не исправляет ranking остальных частей |
| q07: literal priority и limits | Полные технические identifiers и баланс lexical candidates | Историческое улучшение одного case уже сопровождалось aggregate regressions |
| q08: split code evidence | Сохранение связи раздела с последовательными source parts примера | Найденное prose не становится evidence JSON без фактического покрытия его ranges |
| q18: составной evidence ниже final cutoff | Ранжирование по содержанию вопроса и сохранение релевантных разных источников | Source diversity или новая RRF constant сами по себе не гарантируют оба нужных фрагмента |

Новый change должен обосновать совместимость и разрешённые изменения требований,
отдельные outputs/reports, provenance, CPU/RAM и regression checks. Frozen
corpus, expectations, source reference и прежние baseline сохраняются. Уже
раскрытый holdout не используется для выбора решений или tuning; до экспериментов
нужен явно определённый допустимый development/validation protocol. Диагностика
holdout misses не является независимым доказательством качества нового решения.

Приёмка следующего этапа требует реально измеренного ≥90% по неизменной evidence
метрике, отдельного раскрытия splits/follow-up и воспроизводимости на целевом
сервере. Отсутствие этого результата оставляет общий quality acceptance MVP
незавершённым. Retrieval code, corpus, settings и baseline при этой передаче
не изменялись; unit tests повторно не запускались, использованы сохранённые
implementation checks и read-only диагностические проверки.
