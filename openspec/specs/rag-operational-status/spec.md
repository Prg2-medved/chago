# rag-operational-status Specification

## Purpose

Обеспечить безопасную диагностику работающего приложения, удерживаемого RAG-индекса, локальной LLM и блокировки генерации без изменения обслуживаемого состояния.

## Requirements

### Requirement: Operational health response
`GET /health` SHALL возвращать HTTP 200 с верхнеуровневым `status="ok"`, `app.status="ok"`, объектами `index`, `llm` и `chat`. HTTP 200 и status SHALL подтверждать работу приложения, а не готовность всей RAG-цепочки. `index` SHALL содержать `status` (`ok`, `missing`, `invalid`), `available: boolean`, `pages`, `chunks`, `indexed_at`; `llm.status` SHALL принимать `ok`, `unavailable`, `invalid_response`, `timeout` или `configuration_error`; `chat.status` SHALL принимать `available`, `generation_uncertain` или `closed`. `chat.status=available` SHALL означать только отсутствие блокировки генерации, а не проверенную готовность retrieval/embeddings/LLM. Health SHALL NOT объявляться end-to-end проверкой качества или работоспособности embedding-модели.

#### Scenario: Healthy dependencies
- **WHEN** приложение удерживает валидный индекс, LLM отвечает корректно и chat не заблокирован
- **THEN** health возвращает HTTP 200, status=ok и соответствующие отдельные состояния компонентов

#### Scenario: App-only operation
- **WHEN** приложение работает без индекса, embedding assets и запущенной LLM
- **THEN** UI и health доступны, index и llm обозначены как недоступные, health не вызывает startup failure или загрузок

### Requirement: Metadata from the active generation
Health SHALL брать pages/chunks и UTC indexed_at из проверенных метаданных активного поколения, используемого retrieval. При отсутствующем или невалидном индексе available SHALL быть false, а pages/chunks/indexed_at SHALL быть null. Валидный пустой индекс SHALL иметь status=ok, available=true и нулевые counts. Health SHALL NOT переоткрывать заменённый на диске файл, переключать поколение или проверять актуальность Wiki.js.

#### Scenario: Replace the index path
- **WHEN** файл по пути индекса заменён при работающем приложении
- **THEN** health продолжает показывать counts и время удерживаемого поколения до штатного restart

#### Scenario: Invalid or empty index
- **WHEN** индекс повреждён либо валиден и пуст
- **THEN** повреждённый индекс имеет status=invalid и null metadata, пустой имеет status=ok и нулевые counts с сохранённым indexed_at

### Requirement: Bounded observational LLM check
Health SHALL проверять только `GET /health` настроенного локального llama.cpp с конечным timeout не более 5 секунд, ограниченным размером response не более 64 KiB, без redirects, machine proxy и retries. Только HTTP 200 с JSON object и status=ok SHALL давать llm.status=ok. HTTP ошибки/недоступность, сломанный response, timeout и неверная конфигурация SHALL отражаться безопасными категориями. Проверка SHALL NOT блокировать event loop, ожидать generation slot, вызывать token counting/completion, загружать модели или обращаться к Wiki.js и внешнему интернету. Одновременные health requests SHALL NOT создавать неограниченное число probes: допускается одна выполняющаяся LLM probe на процесс с совместным ожиданием её результата.

#### Scenario: Loading or unresponsive LLM
- **WHEN** llama.cpp отвечает 503 либо не отвечает до timeout
- **THEN** health возвращает соответственно llm.status=unavailable либо timeout, сохраняя app status и не отправляя генерацию

#### Scenario: Invalid response or redirect
- **WHEN** LLM возвращает некорректный/слишком большой JSON, status не ok или redirect
- **THEN** health не объявляет LLM готовой, не следует redirect и не раскрывает upstream body

#### Scenario: Concurrent health during chat
- **WHEN** несколько клиентов запрашивают health во время активной генерации
- **THEN** health не ждёт освобождения generation slot, использует максимум одну одновременную LLM probe и не запускает completion

### Requirement: Diagnostic safety and generation uncertainty
Health SHALL NOT раскрывать secrets, DSN, credentials, environment values, абсолютные пути, raw exceptions, тексты вопросов, документов и ответов. При `generation_uncertain` chat SHALL оставаться заблокированным независимо от llm.status=ok; чтение health SHALL NOT освобождать слот, выполнять recovery, restart или повторную генерацию. Диагностическое состояние SHALL формироваться по текущему состоянию chat после завершения probe.

#### Scenario: LLM healthy but generation blocked
- **WHEN** LLM отвечает status=ok после transport failure с неопределённым завершением
- **THEN** health показывает llm.status=ok и chat.status=generation_uncertain, новые chat запросы продолжают получать 503 без нового completion

#### Scenario: Secret-bearing configuration failure
- **WHEN** конфигурация LLM содержит некорректное значение с credentials либо возникает backend exception
- **THEN** health возвращает безопасную категорию без исходного значения и traceback
