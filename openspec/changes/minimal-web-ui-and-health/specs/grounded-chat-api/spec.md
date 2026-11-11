# Spec Delta

## MODIFIED Requirements

### Requirement: Technical errors and app-only compatibility
Отсутствующий/невалидный индекс, несовместимые или недоступные embedding assets, ошибки retrieval и недоступная LLM SHALL давать безопасную HTTP 503; timeout LLM SHALL давать HTTP 504; некорректный transport response LLM SHALL давать HTTP 502. Некорректный формат содержимого генерации SHALL обрабатываться как неподтверждённый ответ HTTP 200 с исходными fragments. Технические ошибки SHALL NOT представляться отказом по отсутствию сведений в Wiki.js. App-only startup SHALL сохраняться без готовности индекса, embedding assets или LLM. `GET /health` SHALL сохранять HTTP 200 и верхнеуровневый status=ok, расширяя JSON диагностикой app/index/llm/chat по rag-operational-status, без генерации, загрузок и изменения generation slot. Система SHALL логировать query, retrieval, LLM wait и generation durations и безопасные категории ошибок, без credentials/DSN, raw exceptions, полного prompt/документов, session_id или message.

Штатный запуск SHALL обеспечивать INFO query/retrieval/wait/generation records
logger `app.chat`, без ручного включения его уровня тестом или оператором.
Исправление этого выявленного deployment logging defect SHALL оставаться
обязательной задачей MVP 7.7 по SPEC §24. Локальная проверка SHALL использовать
штатную logging configuration; фактические безопасные records SHALL быть
подтверждены на предусмотренных запросах следующей Compose приёмки 7.3.
Отсутствие этих records в принятой 7.6 SHALL раскрываться отдельно и SHALL NOT
требовать повтора 20 запросов только ради логов. Unit checks SHALL NOT заменять
live logging evidence 7.3; 7.7 SHALL NOT закрываться до обоих видов проверки.

#### Scenario: Missing index or model
- **WHEN** app запущен без готового индекса либо embedding assets
- **THEN** health возвращает HTTP 200 и status=ok с диагностикой недоступных компонентов, chat возвращает техническую HTTP 503 без создания индекса или загрузок

#### Scenario: App timings in the normal startup configuration
- **WHEN** приложение запускается штатно и выполняет предусмотренные проверки 7.3
- **THEN** Docker logs содержат безопасные query/retrieval/wait/generation timings без дополнительного включения INFO; для cancellation допускается поздняя отдельная generation record

#### Scenario: LLM failures
- **WHEN** LLM недоступна, превышает timeout либо возвращает сломанный HTTP JSON/envelope
- **THEN** chat возвращает соответственно 503, 504 либо 502 с безопасным сообщением, без утверждения об отсутствии информации в документации

#### Scenario: Malformed generated content
- **WHEN** transport envelope валиден, но модель вернула непарсируемое содержимое вместо согласованного формата ответа
- **THEN** backend не показывает сырой output, возвращает неподтверждённый ответ с исходными fragments и не повторяет генерацию

