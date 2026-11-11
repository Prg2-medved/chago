# Spec Delta

## MODIFIED Requirements

### Requirement: Explicit LLM readiness check
Административная команда из окружения app SHALL проверять GET /health llama.cpp по LLM_BASE_URL с конечным timeout и сообщать успех только при HTTP 200 и status=ok. Загрузка, недоступность, некорректный ответ и истечение timeout SHALL давать понятную ошибку и ненулевой exit code. Эта административная команда SHALL сохраняться отдельно от GET /health приложения; расширенный HTTP health SHALL также проверять LLM по rag-operational-status без запуска административной completion команды.

#### Scenario: Ready model
- **WHEN** модель загружена и оператор выполняет проверку LLM
- **THEN** команда подтверждает готовность и завершается с кодом 0

#### Scenario: Loading or unreachable model
- **WHEN** llama.cpp возвращает 503, недоступен или не отвечает до timeout
- **THEN** команда не сообщает готовность и завершается с ненулевым кодом, а app-only /health возвращает HTTP 200 и status=ok с отдельной диагностикой недоступной LLM

