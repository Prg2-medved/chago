# Spec Delta

## ADDED Requirements

### Requirement: Independent validation after holdout exposure
При раскрытом historical holdout независимая оценка SHALL использовать отдельное заранее замороженное package новых вопросов, подготовленное evaluator, не участвующим в выборе решения. Historical corpus/reference/expectations/splits SHALL сохраняться; exposed holdout SHALL использоваться только для отчёта и SHALL NOT называться независимой или слепой проверкой. Новый package SHALL содержать ≥20 новых answerable live single-question случаев с manually reviewed полным evidence из frozen reference, без дубликатов/парафразов старых вопросов и без отбора по historical miss IDs. Prose, команды, таблицы, identifiers и составное evidence SHALL быть представлены. Follow-up и answerless/synthetic cases SHALL показываться отдельно от independent live denominator. Package SHALL проходить существующую structural validation и отдельный semantic review до запуска retrieval.

#### Scenario: Independent package commitment
- **WHEN** evaluator завершил review новых вопросов до independent validation выбранного решения
- **THEN** fingerprints questions/manifest/reference и критерии приёмки фиксируются заранее, закрытые вопросы/expectations не доступны разработчику для выбора policies/configuration

#### Scenario: Relabeled historical questions
- **WHEN** набор состоит из прежнего holdout, его парафразов или вопросов, отобранных по известным misses
- **THEN** он не принимается как независимый validation, независимо от названия split или новых IDs

### Requirement: Locked independent evaluation and honest reporting
До доступа к validation результатам SHALL фиксироваться code revision, model/tokenizer/index fingerprints и выбранные policies/settings. Вскрытие и запуск закрытого package SHALL допускаться только после последовательного успеха lock, frozen v1 ≥11/12 и target-server acceptance, включая обязательные integrity/regression/resource/reproducibility checks. Провал или незавершённость предшествующего gate SHALL сохранять package невскрытым и неиспользованным. Независимая метрика SHALL использовать неизменную protocol v1 semantics полного original evidence coverage top 5, threshold ≥90% (ceil(0.9*N) hits), отдельные numerator/denominator, per-case misses и 95% Wilson interval. Отчёт SHALL раскрывать ограниченность размера выборки и обобщение только на новые вопросы того же source corpus. Повторные идентичные запуски для воспроизводимости SHALL допускаться; изменения решения по результатам validation SHALL требовать новой независимой выборки и нового experiment protocol. Если package/evaluator отсутствует, independent acceptance SHALL оставаться незавершённой без подмены exposed holdout, но development tasks 2–5 SHALL NOT блокироваться после фиксации experiment protocol; подготовка package SHALL допускаться параллельно development.

#### Scenario: Preserve validation package after an earlier failure
- **WHEN** frozen v1 либо обязательный target-server gate не пройден
- **THEN** evaluator не вскрывает и не запускает закрытый package, независимо от его готовности, а independent acceptance остаётся незавершённой

#### Scenario: One-shot validation fails
- **WHEN** зафиксированное решение не достигает ≥90% на закрытом validation
- **THEN** публикуется провал без ретроспективного изменения expectations, исключения трудных cases или подбора следующего кандидата по этой выборке

#### Scenario: Observed threshold and uncertainty
- **WHEN** validation содержит 20 соответствующих live cases и получено 18 полных hits
- **THEN** observed threshold достигнут как 18/20, отчёт показывает interval и не утверждает доказанную population accuracy ≥90%

### Requirement: Separate experiment and evidence protocol versions
Report/lock SHALL отдельно фиксировать experiment protocol v2 и неизменный evidence scorer/corpus protocol v1. Новый development experiment SHALL сохранять denominator 9 с legacy q03 miss, full source-range coverage top-5 и все per-case transitions против legacy/RRF controls; historical holdout SHALL NOT читаться/запускаться или использоваться для выбора в development. Повторяемая development оценка ≥8/9 SHALL открывать только lock consideration после всех mandatory gates и SHALL NOT заменять frozen denominator 12/threshold ≥11/12, actual target-server acceptance либо independent validation ≥90%. Protocol v1/receipt, отрицательный результат 36 комбинаций и frozen inputs SHALL оставаться immutable. Independent evaluator/package SHALL NOT требоваться для development после commitment протокола соответствующей фазы, но SHALL оставаться обязательными для independent acceptance.

#### Scenario: New experiment does not change evidence scoring
- **WHEN** report нового cross-encoder experiment указывает experiment protocol v2
- **THEN** evidence scorer остаётся protocol v1, q02 требует полное покрытие трёх chunks в top-5, q07 одного, legacy q03 остаётся miss и denominator не меняется

#### Scenario: Development succeeds before independent acceptance
- **WHEN** development достигает ≥8/9 и проходит обязательные gates, но evaluator/package отсутствуют
- **THEN** допускаются lock и предшествующие final gates в прежнем порядке, independent acceptance остаётся открытой без обращения к exposed holdout как независимой оценке
