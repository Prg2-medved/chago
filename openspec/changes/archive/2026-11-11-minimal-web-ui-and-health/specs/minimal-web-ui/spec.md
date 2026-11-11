# Spec Delta

## Purpose

Предоставить пользователю простой локальный русский интерфейс независимого RAG-вопроса с ответом, проверяемыми источниками и понятной обратной связью.

## ADDED Requirements

### Requirement: Local single-question screen
Система SHALL предоставлять по `GET /` русский Web UI с полем вопроса, кнопкой отправки, состоянием ожидания, текущим ответом и source cards. Все необходимые ресурсы SHALL обслуживаться тем же приложением без внешних CDN, шрифтов, telemetry и runtime-загрузок из интернета. Экран SHALL работать в подготовленном app-only окружении даже при недоступных RAG-компонентах.

#### Scenario: Open the local screen
- **WHEN** пользователь открывает `/` без доступа в интернет
- **THEN** получает работоспособную форму и локальные ресурсы без обращения к внешним сервисам

### Requirement: Independent question lifecycle
UI SHALL отправлять один `POST /api/chat` с текущим `message` и совместимым непустым `session_id`. Пока запрос выполняется, UI SHALL показывать ожидание обработки, блокировать повторную отправку и SHALL NOT автоматически повторять запрос. При отправке следующего вопроса предыдущие ответ, sources и ошибка SHALL удаляться; экран SHALL содержать только текущий вопрос и его результат. UI SHALL NOT хранить историю в browser storage, cookies, URL или backend и SHALL NOT передавать предыдущие вопросы/ответы в API, retrieval или LLM. Перезагрузка SHALL открывать пустой экран; существующее поле `session_id` SHALL NOT создавать диалоговый контекст.

#### Scenario: Submit twice while waiting
- **WHEN** пользователь отправляет вопрос и повторяет клик или Enter до завершения
- **THEN** выполняется ровно один chat request и остаётся видимое состояние ожидания

#### Scenario: Replace the previous result
- **WHEN** после ответа пользователь отправляет другой вопрос
- **THEN** прежний ответ и sources исчезают до получения нового результата, payload содержит только session_id и новый message, история не сохраняется

#### Scenario: Reload after an answer
- **WHEN** пользователь перезагружает страницу после полученного результата
- **THEN** предыдущие вопрос, ответ и sources не восстанавливаются

### Requirement: Answer and source presentation
UI SHALL показывать `answer` и все `sources` в исходном порядке с номерами, соответствующими `[1]`, `[2]` в ответе. Каждая карточка SHALL содержать title, непустой heading при наличии, дословный quote и ссылку на Wiki.js. Переводы строк, пробелы и команды в answer/quote SHALL сохраняться. `insufficient_context=true` SHALL отображаться как результат с обозначением недостатка сведений, включая доступные sources, а не как техническая ошибка.

#### Scenario: Answer with source fragments
- **WHEN** API возвращает ответ с несколькими источниками и многострочным кодом
- **THEN** пользователь видит ответ, номера и соответствующие карточки с неизменёнными fragments и ссылками

#### Scenario: Refusal or partial answer
- **WHEN** API возвращает HTTP 200 с insufficient_context=true и пустыми либо непустыми sources
- **THEN** UI показывает ответ и признак недостатка сведений, сохраняет доступные sources и не показывает ошибку инфраструктуры

### Requirement: Safe rendering of untrusted content
Вопрос, answer, title, heading и quote SHALL отображаться как текст без исполнения HTML/JavaScript или подгрузки embedded assets. UI SHALL создавать кликабельные source links только для абсолютных HTTP(S) URL без credentials; другие URL SHALL оставаться некликабельными. UI SHALL NOT выполнять команды из ответа или источников.

#### Scenario: HTML and unsafe links in source data
- **WHEN** API возвращает HTML-like fragment либо URL с javascript/data scheme или credentials
- **THEN** fragment виден как текст, не исполняется, а небезопасный URL не становится ссылкой

### Requirement: Understandable errors and operational details
UI SHALL показывать безопасные русские сообщения для пустого/невалидного вопроса, HTTP 422, 502, 503, 504, иных HTTP ошибок, сетевой ошибки и некорректного API response. Технические ошибки SHALL NOT представляться отсутствием информации в документации. После ошибки ожидание SHALL завершаться и повторная отправка SHALL требовать действия пользователя. UI SHALL показывать состояния из `/health`, количество pages/chunks и время последней успешной индексации с обозначением часового пояса, либо явное отсутствие этих данных. Сбой health SHALL NOT скрывать форму или уже полученный chat result и SHALL NOT инициировать chat retry.

#### Scenario: Component or network failure
- **WHEN** chat возвращает 503/504 либо сеть недоступна
- **THEN** UI показывает соответственно временную недоступность/timeout/ошибку связи, не оставляет бесконечное ожидание и не повторяет генерацию

#### Scenario: Inspect index age
- **WHEN** health содержит indexed_at либо сообщает об отсутствии индекса
- **THEN** UI показывает время последней успешной индексации с часовым поясом либо явное сообщение об отсутствии индекса без выдуманной даты

#### Scenario: Health fails independently
- **WHEN** обновление health завершается ошибкой после успешного chat
- **THEN** ответ и sources остаются видимыми, диагностический блок сообщает о недоступности проверки
