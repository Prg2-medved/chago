# rag-evaluation-corpus Specification

## Purpose

Предоставить воспроизводимый контрольный набор реальных вопросов и проверенных исходных фрагментов Wiki.js для сравнения будущих вариантов chunking/retrieval и ручной приёмки grounded answers.

## Requirements

### Requirement: Frozen reference corpus
Corpus SHALL содержать версию формата, версию набора и manifest фиксированного полного ingestion snapshot с source origin, SHA-256 файла, количеством документов и их page_id/locale/path/content_sha256. Reference snapshot SHALL сохраняться локально независимо от перезаписываемого ingestion output. Начальная live reference SHALL включать подтверждённые 24 Markdown-страницы. Последующие изменения источника SHALL требовать явной новой версии и повторной проверки разметки; validation SHALL NOT автоматически обновлять reference или ожидания.

#### Scenario: Repeated offline validation
- **WHEN** одинаковый corpus проверяется с той же reference copy без Wiki.js, моделей и интернета
- **THEN** результат и fingerprint совпадают и reference не изменяется

#### Scenario: Reference drift
- **WHEN** изменён Markdown, metadata, состав страниц или байты snapshot без обновления версии manifest
- **THEN** validation завершается ненулевым кодом с диагностикой несовместимости

### Requirement: Real questions and source evidence
Около 20 вопросов SHALL быть целевым размером, а не жёстким schema constraint; отклонение от цели или диапазона 18–24 само по себе SHALL NOT приводить к structural validation failure.
`eval/questions.yaml` SHALL содержать вручную составленные вопросы с целевым размером около 20 после чтения реальных страниц, со стабильными уникальными IDs, вопросом на русском, категориями и ожидаемым поведением. Answerable вопросы SHALL хранить ожидаемые source page/path с locale и идентичностью источника, короткий дословный фрагмент либо heading locator и 1–3 обязательных факта. Каждое необходимое свидетельство SHALL иметь однозначно проверяемый текстовый диапазон в исходном Markdown. Команды SHALL храниться дословно. Составной вопрос SHALL перечислять все обязательные свидетельства. Реальные paths, факты и цитаты SHALL NOT выдумываться или подменяться synthetic примерами.

#### Scenario: Source evidence validation
- **WHEN** для вопроса указан источник и обязательный фрагмент
- **THEN** проверяются identity, locale/path, hash и соответствие указанного диапазона исходному Markdown

#### Scenario: Wrong fragment on correct page
- **WHEN** найденная страница совпадает, но нужные сведения отсутствуют в найденном фрагменте
- **THEN** такой результат не считается успешным retrieval

### Requirement: Required question coverage
Набор SHALL включать обычный текст, точные технические названия, code block, Markdown table, несколько follow-up с предыдущим вопросом, 3–5 полностью unanswerable вопросов с `answerable: false`, частичный ответ, неоднозначный вопрос с ожидаемым уточнением, длинный code block, похожие identifiers и prompt injection из документа. Частичный ответ SHALL отделять подтверждённые факты от отсутствующих сведений. Набор SHALL включать «Как работает роутплан?», «Как настроить сервер?», «Как настроить сервер на объекте?» и «Какое оборудование используется в складе?» после проверки их ожидаемых источников; отсутствие сведений SHALL отражаться честной разметкой отказа/частичного ответа/уточнения без фиктивных citations.

#### Scenario: Follow-up record
- **WHEN** вопрос зависит от предыдущего обращения пользователя
- **THEN** corpus хранит предыдущий вопрос и проверенные источники нового вопроса, не используя прошлый ответ как свидетельство

#### Scenario: Missing or ambiguous information
- **WHEN** вопрос не имеет ответа, имеет только часть ответа или допускает несколько неразрешённых трактовок
- **THEN** ожидание соответственно требует отказа, явно ограниченного частичного ответа или короткого уточнения

### Requirement: Explicit synthetic edge cases
Для каждой обязательной специальной категории разработчик SHALL сначала проверить весь live reference и зафиксировать найденные live evidence либо отсутствие подходящего материала. Synthetic fixture SHALL добавляться только для конкретной обязательной категории с подтверждённым отсутствием подходящего live материала. Synthetic дубликаты существующих подходящих реальных случаев SHALL NOT создаваться. При полном live coverage synthetic cases и snapshot не требуются.
Corpus SHALL включать противоречащие источники, если они существуют в reference; иначе SHALL предоставлять контролируемые synthetic fixtures с двумя противоречащими источниками. Отсутствующие в live corpus материалы для длинного кода, похожих identifiers или prompt injection SHALL покрываться synthetic fixtures. Synthetic cases SHALL быть явно помечены, иметь отдельное пространство источников и воспроизводимые Markdown/hash/metadata. Они SHALL NOT изменять Wiki.js, заявляться live evidence или незаметно смешиваться с live retrieval метрикой.

#### Scenario: No live contradiction
- **WHEN** после чтения reference не обнаружено подходящего реального противоречия
- **THEN** отдельный fixture case ожидает сообщение о расхождении и оба фрагмента без выбора правильной версии

#### Scenario: Existing live edge case
- **WHEN** подходящий материал обязательной специальной категории найден в полном live reference
- **THEN** corpus использует реальный случай без synthetic дубликата

#### Scenario: Injection fixture
- **WHEN** документ содержит попытку изменить правила ответа
- **THEN** ожидание требует трактовать её как данные и сохранить grounded поведение без выполнения действий

### Requirement: Offline integrity and coverage validation
Система SHALL предоставлять документированную offline CLI-проверку corpus/reference/fixtures без DB credentials, Docker, retrieval или LLM. Проверка SHALL выявлять неверный формат/версию/типы, duplicate IDs, отсутствующие категории, неверный split, missing sources, hash mismatch, неверные диапазоны и недословные команды. Она SHALL возвращать 0 только при валидной структуре, coverage и привязках, иначе ненулевой код с case ID и категорией ошибки без полного содержимого документов или secrets. Семантическая верность фактов и отсутствие ответа SHALL дополнительно проверяться человеком, а спорные примеры — владельцем документации.

#### Scenario: Invalid evidence
- **WHEN** запись ссылается на отсутствующую страницу или текст вне проверенного диапазона
- **THEN** CLI возвращает ненулевой код и идентифицирует проблемный case

#### Scenario: Structural success is not semantic approval
- **WHEN** offline validation проходит
- **THEN** отчёт подтверждает integrity и coverage, а ручная проверка фактов остаётся отдельным условием готовности набора

#### Scenario: Target size is not a structural limit
- **WHEN** count выходит за диапазон 18–24, но обязательное coverage, evidence, IDs, split и остальные инварианты соблюдены
- **THEN** count сам по себе не вызывает validation failure и отчёт показывает фактический размер

### Requirement: Stable comparison and acceptance protocol
Основная метрика live Hit@5 SHALL включать только соответствующие answerable live cases с evidence: полные hits в числителе и эти cases в знаменателе. Порог MVP Hit@5 ≥90% SHALL относиться только к live метрике. Synthetic cases SHALL NOT входить в её числитель или знаменатель; их результаты SHALL показываться отдельно. Tuning и holdout SHALL показываться раздельно для live и synthetic cases.
Каждый вопрос SHALL заранее принадлежать tuning или holdout split; часть вопросов SHALL сохраняться для финальной проверки и SHALL NOT использоваться при подборе параметров. Протокол SHALL фиксировать corpus/reference version, вариант chunking/retrieval и параметры, разделять live/synthetic и tuning/holdout результаты. Для будущего retrieval полный hit SHALL означать присутствие всех необходимых свидетельств в совокупности top 5 chunks с правильными источниками; отдельный page hit недостаточен. Требование MVP SHALL быть не менее 90% полных hits среди соответствующих answerable live вопросов с необходимыми свидетельствами. Отказы и вопросы только на уточнение SHALL оцениваться отдельно от retrieval denominator. Ручная приёмка SHALL проверять 1–3 обязательных факта, подтверждение цитатами, дословность команд, обозначение пробелов, оба противоречащих источника и отсутствие неподтверждённых утверждений; все unanswerable cases SHALL требовать отказа от выдуманного ответа. Этот change SHALL задавать протокол без заявления о достигнутом retrieval/answer качестве.

#### Scenario: Composite retrieval result
- **WHEN** top 5 содержит только один из двух необходимых фрагментов составного вопроса
- **THEN** вопрос считается retrieval miss независимо от совпадения страниц

#### Scenario: Holdout and unavailable retrieval
- **WHEN** завершена подготовка corpus до реализации retrieval
- **THEN** holdout зафиксирован, integrity проверена, а retrieval и answer метрики отмечены как ещё не измеренные

#### Scenario: Synthetic success cannot mask live misses
- **WHEN** synthetic cases проходят, но live Hit@5 ниже 90%
- **THEN** порог MVP не считается достигнутым, synthetic результаты показаны отдельно, tuning/holdout разделены
