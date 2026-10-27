# Grounded chat API: кандидат 7.9 и локальные регрессии, 2026-10-27

Владелец согласовал механизм из design §11 как минимальный кандидат, **не как
подтверждённое устранение safety blockers**, и отдельно разрешил реализацию/
локальные регрессии. Реальные LLM/server/Compose/token endpoint calls не
выполнялись. В тестах используются fake HTTP servers/clients и authored outputs.
Историческая 7.2 и review 7.8 не переписаны; holdout q18 не использован для
настройки prompt, guard, fixtures или выбора варианта.

## Реализованное поведение

Единственный production file — `app/app/grounding.py`:

- Prompt сначала определяет объект из текущего вопроса; при неопределённом
  объекте требует сразу clarify без угадывания по context. Затем сравнивает
  релевантные sources одного объекта/параметра, требует оба conflicting values
  с citations и partial; затем выбирает обычный ответ по достаточности.
- Естественный вопрос с местоимением показан без подсказки «объект неизвестен».
  Добавлены независимые examples Orion/Vega для conflict/agreement/different
  objects. Все 7 учебных outputs проверены настоящими parser/code/citation
  validators, включая перестановку sources и недопустимость учебных ID для
  реального manifest. Это форматные тесты, не результаты генерации Qwen.
- В общей validation после canonical refusal проверяется оставшаяся вне
  проверенных fences prose, включая inline code/clarify. Узнаваемый shell
  invocation даёт `code_prose` и прежний полный fallback без raw generated
  claims, автоматического оборачивания команды или второго completion.
- Содержимое каждого generated fenced block по-прежнему должно дословно
  находиться в одном переданном непрерывном original fragment. Изменённые flags,
  whitespace/IP, склейки ranges и незакрытые fences остаются недопустимыми.
  Само наличие generated fence не является подтверждением источника.

Guard узнаёт `sudo` с последующим ASCII token argument и executable с arguments,
извлечённый из простой строки внутри полного исходного `sh`/`bash`/`shell` fence.
Имя executable не зашивается в список eval literals. Извлечение использует
только packed original fragments; не generated output, title или heading.
Строки с shell keyword из поддержанного списка, leading assignment, pipeline,
redirect, variable/continuation исключаются из извлечения; `.`/`..` и отдельные
разделители пути не становятся executable. Проверка не выполняет команды.

Public API, `{kind, answer}`, validator signature, transport/semaphore, один
completion и read-only retrieval остаются прежними. Dependency/model/image/
runtime flags/sampling/window/reserve/timeout/Compose не менялись. Изменённый
prompt означает новые messages и **не получает старый token pass автоматически**.

## Что проверено и что осталось вне гарантии

22 исходных fixtures 7.8 сохранены. У шести command cases expectations в tests
заменены на новый fallback: скрытая команда в clarify, абзац q03, inline Netplan,
custom executable в prose/inline и изменённые arguments известного executable.
Остальные unsafe authored outputs остаются явными границами, не safety passes:
угаданный объект с корректной fenced command, односторонний conflict и invented
executable без узнаваемого prefix/исходного shell примера.

Дополнительные регрессии проверяют произвольные имена/пути executable в трёх
языковых markers, answer/partial/clarify, tilde/длинные fences, точную команду
и дополнительную unfenced команду в том же ответе. Позитивные controls включают
обычные ответы, standalone identifiers, mode=sudo/sudoers, русские пояснения
об утилите, английское пояснение с именем в inline code и shell builtin `.`:
ни один такой control не превращается в fallback. API test подтверждает HTTP 200
fallback, исходный quote, ровно один completion, отсутствие private output в
логах и нормальную обработку следующего обычного вопроса. Harness test
подтверждает безопасную diagnostic category и отсутствие retry/сырого output.

**Ограничения не сняты:**

- Неизвестные executable без sudo/source example, bare command без arguments,
  другие языки, неполные/неразмеченные исходные blocks и сложная shell grammar/
  обфускация могут остаться в prose. Guard не является полным shell parser.
- Английская prose с видом «executable + ASCII слово», а также ошибочно
  размеченный исходный shell block могут дать ложный fallback. Позитивные
  fixtures не подтверждают отсутствие массовых false refusals на реальных
  пользовательских вопросах. Это отдельно проверяется при live review.
- Backend не понимает объект вопроса или смысл конфликта. Эффект нового prompt
  на Qwen ещё не измерен; нельзя объявлять локальные examples доказательством
  исправления ambiguity/conflict, entailment либо всех команд.
- Более длинный prompt может изменить packing/evidence coverage; это должно
  быть измерено на окончательных messages без изменения window/reserve.

## Локальные проверки

Из `app/`, с `-B` и отключённым pytest cache:

```powershell
../.venv/Scripts/python.exe -B -m pytest -q -rs -p no:cacheprovider --basetemp=../.tmp/grounded-79-profile-final tests/test_grounding.py tests/test_grounding_safety_diagnostic.py tests/test_chat_api.py tests/test_chat_concurrency.py tests/test_llm_client.py tests/test_chat_evaluation.py tests/test_health.py tests/test_config.py tests/test_index_state.py tests/test_active_retrieval.py tests/test_hybrid_retrieval.py tests/test_hybrid_retrieval_cli.py
../.venv/Scripts/python.exe -B -m pytest -q -p no:cacheprovider tests/test_grounding.py tests/test_grounding_safety_diagnostic.py
../.venv/Scripts/python.exe -B -m pytest -q -rs -p no:cacheprovider --basetemp=../.tmp/grounded-79-full-final
../.venv/Scripts/python.exe -B -m mypy app ../docs/grounded-chat-api-fault.py --follow-imports=silent --cache-dir ../.tmp/mypy-grounded-79
```

Профильные API/grounding/LLM/evaluation + config/health/index/hybrid — **274 passed**.
После исключения builtin `.` и добавления его regression итоговые grounding —
**127 passed in 0.42s**; mypy — success, **31 source files**.
Итоговый полный pytest окончательной версии: **1126 passed, 46 skipped,
35 subtests passed, 1 warning in 87.64s**.
Первый полный suite до проверки builtin прошёл: 1125 passed / 46 skipped /
35 subtests passed in 118.83s. Повтор обоснован последней production правкой.

46 skips относятся к Windows: 3 symlink privilege, 1 Linux flock, 4 POSIX
permission и 38 Linux Bash/flock/signals tests. Они не объявляются выполненными;
изменение grounding не затрагивает эти Linux mechanisms. Warning — существующий
Starlette/httpx deprecation. Первые sandbox runs упёрлись в WinError 5 при pytest
temp cleanup; проверки с filesystem/fake HTTP выполнены вне sandbox. Первый
расширенный run имел один test failure: authored answer без citation закономерно
получил citation_missing раньше code_prose. Fixture заменена на clarify с командой;
production порядок validation не менялся ради expected error category.

Финальный local-bytes SHA256 `app/app/grounding.py`:
`1587022b84f4ab1ad586403ab673516defa455d77c34b18b330343891b0c045a`.
Frozen questions/manifest/live/synthetic reference и исходный evidence archive
сохранили hashes из 7.8. Ни один frozen input или исторический baseline/review
не изменялся; source namespaces/splits прежние.

## Необходимый серверный этап — только после отдельного согласования

1. В 7.11 дополнить уже сохранённую внешнюю обвязку прежнего run, если она
   существует. Не восстанавливать прошлую RAM/process identity новыми снимками.
   Подготовить сбор code/messages hashes, public settings/flags, image/model/
   index identity, timestamps/exit, process/OOM/resource observations и inputs
   before/after для нового интервала. Текущий архив содержит лишь inner reports.
2. На окончательных новых messages повторить exact template/token gate 7.1
   с calculated=actual usage.prompt_tokens и context boundary/reserve. Старый
   pass 7.1 сохранить для старых messages. При mismatch не переходить к corpus,
   не вводить поправки, не менять window/max_tokens/runtime ради прохождения.
3. Зафиксировать вариант до приёмки и выполнить предусмотренную 7.2: полный
   single-question corpus end-to-end и generation-only, все unanswerable,
   security/conflict cases; сохранить IDs/coverage/packing/counts/timings/
   fallback/errors и внешнюю обвязку. Не повторять отдельный holdout за хорошим
   ответом и не настраивать на q18; обычные корректные ответы проверить на
   необоснованные отказы. Отдельно оценить stability, safety, semantic quality.
4. При safety/stability fail сохранить blocker и остановиться без автоматического
   retry/tuning/recovery. При pass — выполнить оставшуюся 7.4. Неизменные принятые
   memory/Compose/logging gates не повторять без конкретной причины; новая
   memory series или fault injection не являются автоматическим следствием
   правки prompt/validator. Follow-up и весь MVP продукта этим не принимаются.

На этом этапе **safety 7.2 не пройдена и 7.4 открыта**. 7.9 означает реализацию
согласованного кандидата, а 7.10 — локальные регрессии, без live acceptance.
OpenSpec strict validation change и всех items — pass (11/11),
`git diff --check` — pass; CLI подтверждает **33/36**, remaining 3.
Два tracked .pyc, перезаписанных тестовыми subprocesses, восстановлены;
production diff содержит только grounding.py, без README/ROADMAP/frozen inputs.
