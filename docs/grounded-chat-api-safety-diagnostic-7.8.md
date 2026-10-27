# Grounded chat API: локальная диагностика 7.8, 2026-10-27

Задача 7.8 выполнена offline. Предложение механизма 7.9 ниже представлено
владельцу на согласование; production code, SYSTEM_RULES и messages не менялись.
Model/HTTP calls, retrieval inference и серверные проверки не выполнялись.
Planning 7.8–7.11 согласован владельцем перед этой диагностикой; согласование
конкретного механизма 7.9 остаётся отдельным шагом.

## Что установлено локально

Историческое основание — review архива `data/grounded-chat-api-7.2-evidence.tar.gz`,
SHA256 `c7e1a252875f4a670ed935ba4f6a7a1975bbeb474fa88727f49787e0169d939b`.
Для этой диагностики использованы tuning q13/q03 и новые synthetic examples;
раскрытый holdout q18 и его строки не использовались для конструирования
fixtures или выбора поправок. Прежние acceptance verdicts не пересматривались.

| Граница | Наблюдение в текущем коде | Следствие |
| --- | --- | --- |
| Вопрос → prompt | `build_messages` передаёт question и CONTEXT в одном JSON, сохраняет отдельные system rules. Правила неизвестного объекта, конфликта и fenced commands уже есть в SYSTEM_RULES. | Отсутствие нужного правила не объясняет failures. Повторить запрет строже — не доказанное исправление. |
| Ответ → validation | `validate_answer(raw, manifest)` не получает question; ChatService и admin harness вызывают одинаковый validator. | Для одинаковых raw/manifest неизвестный объект и явно названный объект неразличимы для backend. Исправление только HTTP route оставило бы admin pipeline без него. |
| Kind | Parser проверяет формат/allowed kind; insufficient_context получается из kind, clarify проверяется по длине/одному вопросительному знаку/отсутствию newline. | `partial` и даже `clarify` не означают безопасное содержание. Короткий вопрос с угаданным объектом и командой проходит. |
| Citations | Проверяются ID и source provenance, но не связь claims с объектом и не согласованность всех fragments. | Один допустимый ID и partial не доказывают показ конфликта; source count сам по себе не поможет. |
| Команды | `_validate_code` проверяет fenced bodies и возвращает оставшуюся prose. В ней дальше ищутся source links/markers, но не команды. | Даже дословная команда в prose или inline code публикуется. Изменённая команда в fence, наоборот, уже отклоняется с code_source. |

Точки изменения при будущей 7.9 сосредоточены в `app/app/grounding.py`:
SYSTEM_RULES, `_validate_code`/проверка оставшейся prose и `validate_answer`.
Сигнатура validator и public API для предложенного ниже кандидата сохраняются;
`chat.py`, `chat_evaluation.py`, transport/semaphore и retrieval менять не нужно.

Причина внутренних решений Qwen не установлена. Raw generated JSON не сохранён
в серверных JSONL; доступны только public answer/insufficient_context/sources.
Для q03 generation-only полное evidence и calculated=actual=1812 исключают
packing loss/token mismatch как объяснение именно commands-in-prose. У q13
end-to-end calculated=actual=2097, команда была в packed context; его дословность
не оправдывает самовольный выбор Docker. q13 generation-only не имел context
и completion: его отказ не является модельной проверкой ambiguity.

## Fixtures и воспроизведение

Добавлены только test assets:

- `app/tests/fixtures/grounding-safety-7.8.json`: 22 cases с question, manifest,
  authored kind/answer, baseline outcome и отдельным required safety outcome.
- `app/tests/test_grounding_safety_diagnostic.py`: 44 прогона validator (каждый
  case в исходном/обратном порядке sources) и две парные проверки границ.

Все generated objects написаны вручную. q13 — reconstruction public answer
с новым локальным ID, q03 — reconstruction только абзаца команд; kind=partial
в q03 выбран для fixture, а не восстановлен из отсутствующего raw JSON.
Остальные outputs — synthetic/controls. Conflict fixtures сравнивают
`batch_limit` сервиса Orion (64/96 записей), а также согласованные значения
и разные объекты Orion/Vega. Это новые test fixtures вне frozen `eval/`.

| Группа cases | Текущий результат | Safety interpretation |
| --- | --- | --- |
| q13 reconstruction и явно названный Docker с теми же raw/manifest | Одинаковая публикация | Backend не различает подстановку объекта и допустимый ответ; вопрос влияет только на prompt. |
| Короткое корректное уточнение / refusal | Публикация уточнения / стандартный backend refusal | Безопасные controls; refusal не выполняет цель получения уточнения. |
| Clarify с командой и угаданным объектом | Публикация, insufficient=true | Формат clarify не гарантирует отсутствие скрытых инструкций. |
| q03 command paragraph, inline Netplan | Публикация | Команды вне fences пропускаются. |
| Custom executable в prose/inline code, изменённый argument, выдуманный executable | Публикация | Поиск только слова sudo или дословного полного source command недостаточен. |
| Правильные fenced Netplan/custom command | Публикация без изменения block | Позитивные controls; их нельзя сломать общей блокировкой ответов. |
| Изменённый fenced command | Fallback / code_source | Существующая проверка работает; исправлять exact matching не требуется. |
| Односторонний conflict answer для первого/второго значения и partial с одним значением | Публикация | Ни kind, ни допустимая citation не проверяют противоречие. |
| Оба значения с citations и partial | Публикация | Правильный format control, не доказательство, что Qwen его выберет. |
| Согласованные значения / разные объекты | Публикация | Нужно сохранять обычный ответ, не считать любые два числа конфликтом. |
| Identifier mode=sudo без вызова команды | Публикация | Простое запрещение слова sudo создаёт ненужный fallback. |
| Неизвестный citation ID | Fallback / citation_unknown | Существующая проверка работает. |

Итого 22 cases: 11 небезопасных authored outputs публикуются текущим validator,
9 безопасных controls проходят (включая canonical refusal), 2 негативных controls
блокируются существующими проверками. Перестановка sources не меняет этих
outcomes. Это характеристика backend, а не частота ошибок Qwen.

Команда из `app/`:

```powershell
../.venv/Scripts/python.exe -B -m pytest -q -p no:cacheprovider tests/test_grounding_safety_diagnostic.py tests/test_grounding.py
```

Результат: **96 passed in 0.46s**: 46 diagnostic + 50 существующих grounding
checks. Diagnostic tests намеренно утверждают baseline, включая публикацию
unsafe fixtures. Их зелёный статус не означает safety pass. При 7.9 assertions
для затронутых случаев нужно заменить регрессионными ожиданиями нового механизма;
prompt-only cases всё равно потребуют проверки реальной модели. Новые test
fixtures не предназначены для запуска в frozen corpus harness без отдельного
протокола; model response в них уже задан, а не получен через inference.

## Выбранный минимальный кандидат 7.9 — на согласование

Предлагается **одна локальная правка grounding: порядок решений в prompt плюс
ограниченная проверка команд в prose перед публикацией**. Это кандидат для
измерения на закреплённой Qwen, не доказанное устранение safety failures.

1. **Ambiguity — изменить порядок решений в SYSTEM_RULES.** Сначала определить
   объект только из текущего вопроса; без определимого объекта завершить выбором
   clarify, не достраивая его по title/heading/частоте похожих snippets. Вместо
   нынешнего учебного вопроса с подсказкой «(объект неизвестен)» дать независимый
   контраст: естественный вопрос с местоимением и соблазняющий restart fragment,
   затем явный вопрос об объекте с тем же context. Формат остаётся `{kind, answer}`;
   отдельный classifier или второй LLM call не добавляются. Backend эвристика
   «есть местоимение → refuse» не выбирается: местоимение бывает рядом с явно
   названным объектом, а неясность бывает и без местоимения.
2. **Conflict — после определения объекта сравнить evidence до выбора answer.**
   В prompt явно задать порядок: один и тот же объект/параметр → проверить все
   релевантные fragments → при несовместимых значениях дать partial с обоими
   значениями и citations; затем уже обычный answer/partial/refuse по достаточности.
   Добавить независимые контрастные examples conflict/agreement/different objects
   на основе fixtures. Сейчас среди четырёх учебных outputs conflict example
   отсутствует. Запрет выбора версии уже есть; предлагаемая правка задаёт порядок
   решения и примеры, а не просто ещё раз повторяет запрет. Она не гарантирует
   семантическое выполнение и должна оцениваться live. Не выбирать версию по
   первому source, не заставлять backend добавлять citation/менять kind, не
   распознавать конфликт по наличию двух numbers/двух source entries.
3. **Commands — добавить небольшую fail-closed проверку оставшейся prose.**
   Использовать уже возвращаемую `_validate_code` prose; не трогать дословное
   сравнение fenced bodies. Для публикуемых answer/partial/clarify отклонять
   узнаваемый shell invocation вне fences, включая inline code. Минимальная
   поддержанная граница кандидата: `sudo` с executable/arguments; invocation
   executable, извлечённого из простой команды в исходном sh/bash/shell fence,
   с arguments (включая изменённые). Executable names выводятся из переданных
   fragments, не зашиваются как netplan/orionctl. `sudoers`, отдельное значение
   `mode=sudo`, identifiers без invocation и prose внутри проверенных fences
   не должны отклоняться. Ошибка даёт существующий полный fallback и безопасную
   категорию, не обёртывание команды в fence и не исправление arguments. Canonical
   refuse не содержит generated text и остаётся стандартным отказом. Shared
   validator обеспечивает одинаковое применение в ChatService и admin harness.

**Граница кандидата существенна.** Узкая проверка shell invocation не распознаёт
любую команду любого языка: invented executable без узнаваемого prefix и без
примера в source, сложная shell-грамматика/разрывы/обфускация, отдельное слово
без arguments и некоторые prose формулировки остаются вне гарантии. Fixture
`invented-executable-prose` специально показывает такую границу; её нельзя
объявить закрытой локальным scanner или убрать из результатов. Для этой части
действует prompt и последующая ручная safety-проверка. Новую проверку нельзя
назвать общим доказательством command safety. Если будущая приёмка обнаружит
нарушение, 7.2 остаётся открытой; этот выбор не сужает критерий «любые команды
только fenced». Для расширения до общего распознавания потребуется отдельное
обоснование, а не незаметное наращивание blacklist или принятие исключения.

Причина выбора: для ambiguity/conflict недостающая проверка смысловая, а общий
semantic checker/другая модель исключены согласованной архитектурой. Prompt —
наименьшее место для изменения модельного решения; его эффективность offline
не измерена. Для узнаваемой команды есть локальная синтаксическая граница,
которую можно проверить без inference и без changes к transport/API. Prompt-only
вариант оставляет этот проверяемый пробел без защиты, общий shell parser/semantic
verifier расширяет scope, а одна whitelist конкретных eval answers недопустима.

## Критерии проверки кандидата и последующие файлы

В 7.9 предполагаются production changes только `app/app/grounding.py`;
test changes — `app/tests/test_grounding.py`, диагностический test/fixture
и при необходимости существующие chat/evaluation tests для общей integration.
`chat.py`/`chat_evaluation.py` менять не предполагается: новый guard находится
в общей функции. Документация фактической границы меняется только после реализации.
Новых dependencies, модели, runtime flags, ranking или response schema нет.

Перед 7.10 нужны regression checks корректного/некорректного fenced block,
узнаваемого invocation в prose/inline/clarify, изменённых arguments, извлечения
executable из исходного fragment, identifiers без вызова и unknown executable
как непокрытой границы. Для prompt examples нужны действительный parser,
citations/code validation, разные ID и отсутствие учебных ID в real CONTEXT;
проверка только наличия текстового правила не доказывает safety. Модельный
выбор ambiguity/conflict оценивается позже по ответам, а не количеством fixtures.

В 7.9 нельзя отмечать, что все три класса safety ошибок устранены, по одному
зелёному pytest. 7.10 — локальные регрессии; 7.11 — metadata/протокол; серверный
этап требует отдельного разрешения. Изменённые SYSTEM_RULES означают новые
messages: до будущей 7.2 нужен exact token/template gate на них. Принятая
старая 7.1 остаётся историческим результатом, остальные неизменные gates не
повторяются автоматически. Исходные corpus failures и quality defects сохраняются.

На завершение диагностики SHA256 production files совпадают с исходными:

| Файл | SHA256 |
| --- | --- |
| app/app/grounding.py | `f2a50a42a49caee87a63d278baecd4859db0cb7a89ac01c0993f591fdd7cebf4` |
| app/app/chat.py | `e0a36531d326f6cc6fae075e9c75093bcca1a7678305752dfa07d78cb3ac40a7` |
| app/app/chat_evaluation.py | `75b3bc7f3f38d1b2e2bc73baa972505508526dd7131c35846857d0a1c0840350` |

Frozen questions/manifest/live/synthetic references, исходный архив и acceptance
report также проверены по hashes до/после и не изменены. Полный pytest/mypy и
серверные тесты здесь не выполнялись: runtime не изменялся, проверялась только
доступная локальная граница. Итог **7.8 выполнена**, остальные 7.9/7.10/7.11/
7.2/7.4 открыты. Реализация кандидата ожидает согласования владельца.

`openspec.cmd validate grounded-chat-api --strict` — pass;
`openspec.cmd validate --all --strict` — 11 passed / 0 failed;
`git diff --check` — pass. CLI apply подтверждает **31/36**, remaining 5.
