# Tasks

> Review draft, 2026-10-22: пересмотр MVP по решению владельца; реализация до
> согласования не начинается. Принятые 1.1–7.1 сохранены. Ни одна новая проверка
> не отмечена выполненной. При неизменных messages/runtime gate 7.1 не повторяется.

Решение владельца от 2026-10-23: 7.6 принята по существующей серии с `--cache-ram 0`
и residual 4,684 MiB только для её интервала. Добавлена обязательная открытая
задача 7.7 по штатному INFO-логированию; на дату этого решения прогресс 28/32. Примечание
2026-10-22 выше описывает предшествующий planning review.

План 7.8–7.11 / design §10 согласован владельцем 2026-10-27. После диагностики
7.8 кандидат §11 отдельно согласован как минимальный вариант и реализован:
7.9/7.10 выполнены локально, без признания safety pass. Актуальный прогресс
**34/36**; прежние 30/32, 30/36, 31/36 и 33/36 ниже описывают свои этапы.
Новые серверные проверки не выполнялись. Порядок продолжения:
**7.8 → 7.9 → 7.10 → 7.11 → отдельно разрешённая 7.2 → 7.4**.

## 1. Интеграция активного индекса и retrieval

- [x] 1.1 Добавить минимальный hybrid view поверх удерживаемого ActiveIndex с единым владельцем reader/matrix и lazy LocalEncoder; проверить на temporary SQLite, что результаты и provenance совпадают с прежним HybridIndex, model identity mismatch отклоняется, CLI defaults 10/10/60/6 сохранены.
- [x] 1.2 Организовать single-thread executor lifecycle для создания/search/закрытия SQLite state и encoder; проверить concurrent searches, shutdown после ошибки/отмены и отсутствие SQLite thread violations, повторного открытия активного пути и двойного close.
- [x] 1.3 Проверить одинаковое поколение retrieval/context/source metadata после подмены pathname и app-only запуск без индекса/assets; запустить сначала профильные index_state/hybrid/health tests и подтвердить прежний `/health` JSON и отсутствие автоматического создания индекса.
- [x] 1.4 Создать раздел lifecycle/retrieval в `docs/grounded-chat-api.md`: snapshot до restart, read-only queries, lazy assets, граница session-follow-up; сверить описанное поведение с проверками 1.1–1.3 без изменения README/ROADMAP.

## 2. Локальный LLM client и бюджет

- [x] 2.1 До реализации зависимых LLM client/token counter провести первичный live compatibility smoke на уже закреплённом llama.cpp image/model: для одинаковых messages сравнить `/apply-template` → `/tokenize` с фактическим `usage.prompt_tokens` completion на коротком русском prompt и prompt с несколькими CONTEXT fragments, code/Unicode и служебным форматом, учитывая generation prefix/special tokens и влияние cache. Требовать точного целочисленного равенства для каждого случая; сохранить digest/model/options и пары calculated/actual в `docs/grounded-chat-api-server-acceptance.md`. Не менять runtime/image/flags/template и не вводить approximate counts/поправки; при mismatch, отсутствии usage/endpoints/live-доступа оставить задачу открытой и остановить зависимые задачи до согласования точного пути. Fake-server tests и поздняя проверка 7.1 этот gate не заменяют.
- [x] 2.2 После 2.1 добавить typed chat settings для context size и конечного LLM timeout, сохранив alias/max_tokens/sampling defaults; передать app `LLM_CONTEXT_SIZE` из общего с llm Compose значения и `LLM_TIMEOUT_SECONDS` default 300, описать их в `.env.example` и docs; проверить defaults, invalid integers, reserve >= window и согласованность `docker compose config` без вывода secrets.
- [x] 2.3 Реализовать внутренний HTTP client без proxies, cross-origin redirects, tools и auto-retry: completion, apply-template и tokenize; покрыть fake HTTP-server tests для payload/model alias, endpoint paths, timeout, 503, malformed JSON/envelope, пустого content и отсутствия повторного completion.
- [x] 2.4 Реализовать полный prompt token count точно по проверенному в 2.1 пути с generation prefix/special tokens и резервом max_tokens; проверить fake tokenizer boundary cases на равенстве и превышении window, ошибки token endpoints и отсутствие character heuristic.
- [x] 2.5 Добавить в docs воспроизводимые команды и фактические результаты ранней проверки 2.1, ожидаемый token accounting и безопасные категории ошибок; сверить документацию с live-отчётом и fake-server tests, указать, что 7.1 повторяет проверку на окончательном prompt.

## 3. Context manifest и правила ответа

- [x] 3.1 Реализовать immutable manifest из `StoredChunk.document.markdown` и source ranges, отдельно от generated segments, с JSON serialization недоверенных данных и chunk IDs; тестами подтвердить точные slices, headings, code/table continuation, смежные и несмежные ranges и попытки внедрить prompt delimiters.
- [x] 3.2 Реализовать prompt rules SPEC §§13–16 и внутренний JSON формат kind/answer, без URL generation и истории; проверить построенные messages и parser для answer/partial/refuse/clarify, запрещённых kind, лишнего/невалидного JSON и конфликтующих источников на fixtures.
- [x] 3.3 Реализовать packing whole chunks по ranking с повторным полным LLM token count; проверить E5 overflow → 422, минимальный prompt overflow → 422, удаление последних chunks целиком, запрет citations удалённых IDs и стандартный отказ без completion, если context пуст.
- [x] 3.4 Описать в docs prompt/data границу, insufficient_context для partial/refuse/clarify/conflict, token reserve и отсутствие score threshold; сверить примеры с parser/packing tests и не менять frozen evaluation inputs.

## 4. Backend citations и команды

- [x] 4.1 Реализовать проверку citation markers по packed manifest, backend numbering и source metadata/quotes; проверить повторные IDs, несколько chunks одной страницы, пустой heading, неизвестный/removed ID, malformed markers, отсутствие citations и сгенерированные source links.
- [x] 4.2 Реализовать отдельные source entries по непрерывным исходным ranges и точную fenced-code validation без нормализации; проверить одинаковые команды, multiline blocks, изменённые IP/flags/whitespace, склейку ranges, generated fences/headers, непереданные участки документа и незакрытые fences.
- [x] 4.3 Реализовать единый безопасный fallback, скрывающий весь неподтверждённый output, с исходными fragments и без повторного LLM вызова; тестами подтвердить HTTP-result insufficient_context=true, отсутствие исходных сгенерированных утверждений и сохранность валидных команд.
- [x] 4.4 Дополнить docs форматом `[n]`/sources, snapshot semantics, примерами partial/refusal/validation fallback и ограничением entailment checks; сверить примеры с реальными validator outputs.

## 5. Chat route, очередь и ошибки

- [x] 5.1 Добавить `POST /api/chat` с strict request/response models, фиксированными max lengths session_id=128 и message=4096 Unicode code points до trim и безопасной 422 validation без echo input; API tests должны проверить contract SPEC §20, неправильные типы/пустые поля, границы 128/129 и 4096/4097 с Unicode/whitespace, отсутствие retrieval/model calls при превышении и отсутствие truncation, отдельную E5/LLM token validation, повторный session_id без истории и отсутствие публичного reindex/context override.
- [x] 5.2 Соединить retrieval → manifest → budget → local completion → validation, с mapping 503/504/502 и отдельным HTTP 200 отказом; проверить missing/corrupt/incompatible index, missing assets, failed retrieval branch, unavailable LLM, invalid transport и malformed generated content без silent fallback.
- [x] 5.3 Добавить process-wide semaphore при одном worker с cancellation-safe владением и состоянием `generation_uncertain`: release после полного completion response, но не после timeout/socket close с возможной отправкой completion. Concurrency tests с управляемыми barriers/fake server должны моделировать сервер, продолжающий генерацию после HTTP timeout: проверить 504 исходному клиенту, удержание слота, 503 уже ожидающим/новым запросам, отсутствие следующего completion/retry даже при health=ok или истечении времени. Отдельно проверить cancellation с поздним полным ответом и release, cancellation с поздним timeout и блокировку, ошибки до отправки/tokenization без блокировки, bounded shutdown и работоспособность `/health`.
- [x] 5.4 Добавить отдельные query/retrieval/wait/generation timings и безопасные error categories; capture-log/API tests с sentinel credentials/message/source text должны подтвердить отсутствие secrets, raw exceptions, полного prompt и session_id в логах/ошибках.
- [x] 5.5 Дополнить docs запускаемыми curl/local/Compose примерами chat, лимитами полей и отдельными token budgets, длительным client timeout с учётом очереди, таблицей HTTP errors и app-only режимом. Описать 504 → generation_uncertain/503 и ручной recovery с подтверждённой остановкой прежней LLM, её запуском и затем restart app; один restart app, health=ok и задержка не подтверждают прекращение генерации. Проверить API examples и переходы состояний через TestClient/fake LLM, сохранив README/ROADMAP, runtime flags и `/health` без изменений.

## 6. Воспроизводимая проверка grounded generation

- [x] 6.1 Подготовить test/admin harness на текущих frozen single-question cases, с отдельным end-to-end режимом и generation-only режимом достаточного evidence из исходных ranges; проверить стабильные case IDs/fingerprints, source namespaces и отсутствие публичного context injection, записи в frozen corpus/expectations/baselines и изменения splits.
- [x] 6.2 Добавить недостающие test fixtures для partial/clarify/conflict/injection, похожих identifiers и длинного code block, не меняя eval frozen inputs; проверить автоматическими tests формат/API/validators, а в docs дать ручной checklist facts/citation entailment/exact commands/refusal и разделение retrieval/context misses от generation failures.
- [x] 6.3 Запустить профильные chat/grounding/LLM tests, затем затронутые health/config/index_state/hybrid/reindex regression tests; из-за integration нескольких компонентов выполнить полный `pytest` из `app/` и принятую в проекте mypy-проверку, сохранить команды и результаты, не отмечать проверки выполненными при missing dependencies или skips без объяснения.

## 7. Серверная и итоговая интеграционная приёмка

- [x] 7.1 После раннего gate 2.1 повторить live token/template compatibility на окончательных messages и границах context с подготовленными offline assets и тем же закреплённым llama.cpp image на целевом CPU: проверить точное равенство рассчитанного prompt count фактическому `usage.prompt_tokens` и соблюдение резерва, дополнить `docs/grounded-chat-api-server-acceptance.md` image/model/settings identity и результатами без изменения runtime или approximate fallback.

Номера сохранены для исторических ссылок; открытые задачи ниже расположены в
порядке выполнения после принятых 7.5/7.6: **7.7 (локально) → 7.3 (включая live
проверку 7.7) → 7.2 → 7.4**. В 7.3 сначала проверяется concurrency/cancellation/
timeout, затем ручной recovery, затем offline/isolation. 7.7 закрывается только
после локальной проверки и фактического logging evidence 7.3.

- [x] 7.5 Свести уже собранные OOM/kernel/container/recovery results из разделов acceptance report, перечисленных в design §9: global_oom/CONSTRAINT_NONE, PID 3709157/anon-rss, OOMKilled/exit=137/PID=0/limits=0, подтверждённый stop/start LLM/restart app, readiness и baseline, завершённый q01 transport. Повторные inspect/kernel/health/recovery команды не запрашивать без конкретно названного пробела и объяснения недостаточности имеющихся данных. Отделить установленный global OOM от неизвестного механизма большого anon-rss и гипотез leak/cache. Недостающие memory series/peaks собирать в 7.6; свежий pre-run baseline относится к новому интервалу, а не повтору прежнего recovery. Не менять модель/image/flags/ресурсы/swap/сторонние сервисы; не объявлять OOM устранённым или серию устойчивой по единичному recovery.
- [x] 7.6 После 7.5 выполнить оператором 20 последовательных end-to-end tuning HTTP chat запросов в точном порядке design §9, включая повторы, без generation-only/добавочных completions или замены cases. Samples раз в секунду для app/LLM/временных harness containers и host MemAvailable/swap; boundaries/status/HTTP durations/LLM prompt-eval/eval/total counts/timings, post-response memory, доступные peak/OOM/process counters и index identity. Stop при MemAvailable <2 GiB (2097152 KiB), новом OOM, завершении LLM или transport/uncertain failure; при исходном значении ниже порога не начинать, retry до recovery запрещён. Порог консервативный, не гарантирует предотвращения OOM. Pass только для полной серии с headroom/telemetry; оценить тренд всей серии, пики и повторные одинаковые cases. Абсолютное отсутствие роста/бесконечное plateau не требуются; небольшой residual может быть принят владельцем только для конкретного измеренного интервала с обоснованием и ограничениями. Неразобранный тренд без такого решения, неприемлемый ресурсный риск или недостаточный headroom оставляют gate открытым независимо от монотонности последних пяти samples. Раскрыть sampled peak limitations; не объявлять отсутствие leak на любой нагрузке. Holdout не включать и не использовать для настройки. Принято владельцем 2026-10-23 по `data/grounded-chat-api-memory.oytj57gl/`: 20/20 HTTP 200, 962 samples, без OOM, min MemAvailable 5372156 KiB; допуск residual LLM anon+swap 4,684 MiB только для этой серии на `--cache-ram 0`, не универсальный порог. Историческая серия `1iqwooas` и safety/quality verdicts не пересматриваются.
- [x] 7.7 Исправить штатное INFO-логирование существующего `app.chat` по обязательному SPEC §24: минимальная настройка уровня/handler, безопасные query/retrieval/wait/generation timings и error categories без secrets/DSN/prompt/document/message/session_id. Локально проверить штатную startup logging configuration без ручного включения INFO проверяемого logger тестом; capture-log checks должны подтвердить timings и отсутствие sensitive fields. Фактическую запись timings в Docker logs проверить на уже предусмотренных запросах последующей 7.3, включая поздний generation record при cancellation; сохранить evidence. До локальной и live проверки задача открыта, не переносится в post-MVP. Не повторять 20-запросную серию только ради логов и не менять LLM/runtime flags/settings ради этой задачи.
- [x] 7.3 После принятой 7.6 и локальной проверки исправления 7.7 проверить через Compose два одновременных HTTP chat запроса, cancellation с поздним полным ответом и с поздним timeout. До операторского timeout испытания подготовить конкретную воспроизводимую fault-injection процедуру по design §9: команды/preconditions/timeline/upstream completion count/cleanup, без изменения production flags/settings/timeout и без следующего completion при generation_uncertain. Без безопасной процедуры испытание не начинать, gate не закрывать. Подтвердить timeout приложения при возможной продолжающейся генерации, 504 исходному/503 ожидающим и новым, отсутствие upstream completion/retry от проверочных chat requests и сохранение блокировки при health=ok/задержке. Только затем подтверждённая остановка прежней LLM, её запуск и restart app разрешают новый completion; проверить успешный chat и неизменный index. Затем `/health` во время генерации, app-only/offline restart, один worker/одну генерацию, отсутствие host-published LLM port, downloads/внешних API и Wiki.js access/writes; сохранить evidence и SQLite hash/metadata до/после. Исторический OOM/recovery и unit tests этот Compose gate не заменяют. На предусмотренных запросах этой же 7.3 фактически подтвердить INFO query/retrieval/wait/generation timings и безопасные error categories app.chat в Docker logs; сохранить evidence для 7.7, включая поздний generation record при cancellation. Без live logging evidence 7.3 и 7.7 не закрывать; 20-запросную серию ради логов не повторять.
- [x] 7.8 После согласования draft design §10 провести offline диагностику safety failures без model/HTTP calls: сопоставить evidence review с текущими prompt/manifest/validators, не выдумывать отсутствующий raw JSON. Подготовить локальные negative/positive fixtures для неизвестного объекта, команд вне fences и противоречащих/согласованных источников, включая перестановку порядка; использовать tuning q13/q03 и независимые synthetic conflicts без копирования holdout q18. Canned/reconstructed outputs не объявлять проверкой поведения Qwen. Зафиксировать минимальный механизм для каждого blocker, границы покрытия, критерии тестов и затронутые файлы; до 7.9 уточнить design при необходимости, расширение архитектуры отдельно согласовать.
- [x] 7.9 После 7.8 реализовать обоснованное минимальное исправление ambiguity/commands/conflict в прежнем contract. Неизвестный объект не подставляется из retrieved heading; команды публикуются только дословно в fenced blocks либо весь generated answer скрывается существующим fallback без retry; при полном конфликтующем evidence показываются оба значения с citations и insufficient_context=true. Общий отказ не засчитывается как успешный показ конфликта; корректные однозначные ответы сохраняются. Конкретная правка prompt и/или ограниченных локальных проверок определяется 7.8; повторение правил prompt/regex само по себе не доказывает решение смысловых проблем. Не добавлять verifier model/общий entailment checker/второй completion/tools/parts, не менять public API, ranking, frozen inputs или runtime. При недостаточности решения оставить blocker открытым и вынести владельцу, не ослаблять safety и не исправлять kind/citations для pass.
- [x] 7.10 После 7.9 запустить профильные grounding/chat/LLM tests с новыми fixtures, затем затронутые API/config/health/index regressions, полный pytest из app/ и принятую mypy-проверку. Проверить exact commands, citations/fallback, независимость вопросов, отсутствие дополнительных completions и sensitive logging; обычные корректные ответы не должны превращаться в общий отказ. Сохранить команды/результаты/причины skips. Fake-server pass не заменяет live Qwen safety; 7.2/7.4 оставить открытыми.
- [x] 7.11 Read-only дополнить metadata исходной 7.2 только уже сохранённой внешней обвязкой: timestamps/exit/code hashes/public settings/LLM flags/container-process-OOM/resources/inputs-check; отсутствие данных явно оставить limitation, не собирать новые снимки за старый интервал. После 7.10 подготовить протокол будущей приёмки окончательного варианта с identity/messages fingerprints, полным сбором внешней обвязки и раздельными verdicts. Указать условный exact token/template gate для изменённых messages/token path/runtime до corpus run и сохранение принятых неизменных gates без автоматического повтора. Протокол не запускает серверные проверки; отдельное разрешение на live этап требуется после локальных результатов, q18 не становится tuning target, старые safety failures сохраняются.
- [ ] 7.2 После принятых 7.5/7.6/7.3, выполнения 7.8–7.11 и отдельного разрешения серверного этапа провести итоговую live MVP приёмку окончательного исправленного варианта на закреплённой Qwen по design §10: end-to-end single-question corpus, все answerable=false и synthetic security/conflict cases, отдельно generation-only на фиксированном достаточном evidence. При изменении messages/token path/runtime до corpus выполнить exact compatibility check по 7.1 для новой identity; прежний pass 7.1 сохранить для прежнего варианта. Раздельно оценить stability, safety и semantic quality; сохранить также внешнюю обвязку identity/resources. API/validators/fallback, exact fenced commands, unanswerable/ambiguity/conflict/injection safety обязательны; выявленные q13/q18 и commands-in-prose failures нельзя перенести в качество. MVP требует pass stability и safety; изолированные defects required facts/kind/entailment остаются post-MVP, не отменяя safety fail. Сохранить ответы/IDs/counts/timings/settings/fingerprints/misses/ограничения и все прежние непройденные 7.2; frozen inputs не менять, раскрытый holdout (включая q18) не использовать для выбора исправления или повторов за удачным ответом. Не требовать Hit@5 ≥90%, не заявлять follow-up acceptance и не повторять неизменные завершённые проверки без причины.
- [ ] 7.4 После фактических live gates сверить implementation со всеми обязательными MVP delta scenarios и отдельно перечислить deferred quality scenarios/дефекты и открытые safety blockers, выполнить `openspec validate grounded-chat-api --strict` и `openspec validate --all --strict`, проверить Git diff на отсутствие кода parts, несвязанных изменений/README/ROADMAP/frozen inputs/model/runtime/ranking. Сохранить прежние результаты, дату изменения критериев и раздельные stability/safety/semantic quality verdicts; отметить tasks только после фактических проверок. При отсутствии сервера или непройденной stability/safety приёмке оставить её открытой, не объявлять весь MVP продукта либо post-MVP качество завершёнными.

## Перенесённая семантическая приёмка (post-MVP, не выполнено)

Исходная 7.2 требовала успешного ручного review required facts, поддержки citations,
gaps/refusal/clarify и обоих противоречащих источников в двух режимах corpus.
Она **не пройдена**; её исходные reviews и результаты сохраняются. Пересмотренная
7.2 выше относится к новой области MVP и не означает ретроспективный pass.
Safety subset (команды, unanswerable, conflicts, injection) остаётся обязательным.

q13 (неоднозначный объект) и q18 (противоречие) остаются потенциальными safety
blockers. Их нельзя автоматически включить в неблокирующий перенос kind/полноты;
они требуют отдельного safety verdict. Сохранённые результаты holdout, включая
q18, не используются для настройки; новый planning review их не исправляет.

Полнота ответов, семантический выбор kind и entailment citations теперь открытые
цели SPEC §27 для отдельного post-MVP change; дополнительных механизмов проверки
или протокола parts здесь нет. Это перенос области работ, а не выполнение задачи.
Известные q01 дефекты: пропуски required facts при полном evidence, необоснованная
недостаточность и citation, не подтверждающая объявленный пробел. Они остаются
неисправленными; прочие failures сохранены в исходных reviews, без переназначения
старых verdicts и без использования раскрытого holdout для настройки.

Источники результатов (содержимое не изменяется):

- `docs/grounded-chat-api-server-acceptance.md` — token gates, global OOM/recovery и незавершённая live приёмка.
- `docs/grounded-chat-api-evaluation-review-2026-10-22.json`.
- `docs/grounded-chat-api-evaluation-review-2026-10-22-rerun.json`.
- `docs/grounded-chat-api-tuning-diagnostic-review-2026-10-22.json`.
- `docs/grounded-chat-api-prompt-examples-q01-review-2026-10-22.json`.

Проект `docs/grounded-chat-api-answer-parts-proposal.md` отклонён решением владельца
2026-10-22, не реализуется. Текущий planning review не закрывает ни один из gates.

## Ход реализации 2026-10-26

Локальная часть 7.7 реализована: startup настраивает INFO/StreamHandler только
для `app.chat`; тест отдельного процесса использует штатную Uvicorn configuration
и проверяет stderr без ручного включения INFO. Проверены безопасные timings/errors
и поздние generation records после cancellation (полный ответ/timeout).
Профильный итог: 50 passed; полный pytest: 1047 passed, 46 platform skips,
35 subtests passed; mypy: success, 31 source files. Подробности и причины skips —
в новом разделе `docs/grounded-chat-api-server-acceptance.md` за эту дату.

Серверные шаги, test-only transport boundary, upstream send trace, cancellation,
timeout/recovery и cleanup подготовлены в `docs/grounded-chat-api-compose-checks.md`
и `docs/grounded-chat-api-fault.py`. Локально проверена HTTP boundary на fake server;
Linux SIGUSR1/Compose/реальная Qwen не проверены. **7.7 остаётся `[ ]` до live
logging evidence 7.3; 7.3/7.2/7.4 также `[ ]`, прогресс 28/32.** Серверные действия
в этой сессии не выполнялись; 20-запросная серия не повторялась.

### Review серверного архива 7.3 / 7.7, 2026-10-27

Проверен SHA256 архива `data/grounded-chat-api-7.3-evidence.tar.gz`
`407cfbccbaf4dac503b9d2cb5184319d1b96091fdb86fa7fe26e410d97563aa0`,
все members безопасно распакованы; исходные bytes и hashes сохранены.
Полный review и границы вывода — в разделе «Итоговый review серверных evidence
7.3 / 7.7, 2026-10-27» acceptance report.

**7.7 `[x]`, прогресс 29/32.** Прежняя локальная startup/sentinel проверка
дополнена фактическими безопасными INFO timings/categories в Docker logs
четырёх Compose cases, включая обе late cancellation records и штатный app
после recovery. Code hashes соответствуют проверенной реализации.

**7.3 `[ ]`**: concurrency, cancellation, native timeout/uncertain/probes,
два полных recovery, app-only, SQLite identity и отсутствие Wiki/API traffic
в четырёх захваченных `any` network windows подтверждены. Но нет health GET
во время генерации (есть только startup/uncertain health), live PortBindings/Ports
и сетевого inspect обеих сетей; network capture не покрывает штатные recovered
chat. Сначала read-only дополнить существующие logs и filtered inspect.
Если нужной health записи нет, минимальная непроведённая проверка — один
health GET во время одного необходимого штатного indexed chat, совместив
с capture `any`; успешно проверенные fault cases не повторять. Не объявлять
незахваченные recovery интервалы наблюдавшимися.

7.2 и 7.4 остаются `[ ]`; 7.2 не начиналась, change не архивирован.
Runtime/settings/Compose/frozen inputs не изменены. Evidence и внутренние
ответы остаются в ignored `data/`, без добавления в Git.

### Review дополнения 7.3, 2026-10-27

Проверен `data/grounded-chat-api-7.3-addendum.tar.gz`, SHA256
`0ca5a8f01eff42800710fc156637a10154e7e0821d54bee8194bcde2e905d268`.
Подробности — «Review addendum 7.3, 2026-10-27» acceptance report.
Предыдущий архив и его verifier повторно проверены offline, без серверных запусков.

**7.3 `[x]`, прогресс 30/32; 7.7 остаётся `[x]`.** Четыре health GET:
HTTP 200 / `{"status":"ok"}`, 1,069–1,337 ms, timestamps внутри фактической
LLM task 282 (prefill), indexed chat HTTP 200 / 80,893726 s.
Filtered live ps/port/PortBindings подтверждают неопубликованный LLM port;
network inspect — app в chago_default/wiki_default, LLM только в chago_default.
Все 154 packets capture `any` разобраны, 0 dropped; только app↔LLM, входящий
HTTP/ответы и loopback DNS, без Wiki/DB/external API/download connections.
Эти данные дополняют прежние concurrency/cancellation/timeout/recovery,
logging, app-only/offline и SQLite hash/metadata evidence. Границы наблюдения
сохранены: прежние recovery/startup интервалы не объявляются захваченными,
новый index snapshot после health-live в addendum отсутствует.

**Открыты 7.2 и 7.4.** Следующий шаг 7.2 — предусмотренный
`bash docs/grounded-chat-api-evaluate.sh`: итоговые end-to-end и fixed-evidence
generation-only single-question cases, все answerable=false и synthetic
security/conflict, отдельные stability/safety/semantic-quality verdicts.
Обязателен ручной safety review q13/q18; раскрытый holdout и frozen inputs
не используются для tuning, прежняя непройденная 7.2 сохраняется.
Строгая валидация change и всех OpenSpec items — pass (11/11);
`git diff --check` — pass. Серверные испытания и runtime tests не повторялись,
настройки LLM не изменены, evidence остаются ignored, change не архивирован.

### Локальная подготовка итоговой 7.2, 2026-10-27

Существующий harness готов к операторскому запуску без изменения кода:
`docs/grounded-chat-api-7.2-runbook.md` содержит точные команды и ожидаемые evidence.
Проверены 10 профильных tests (pass), Bash syntax, frozen package v1,
read-only inventory обоих evaluation-индексов (live 24 docs/910 chunks,
synthetic 1/1), неизменность SQLite hashes и fixed manifests всех 18 cases.
Harness идёт через admin pipeline, не HTTP route/semaphore; принятые API/Compose
проверки не повторяются. Серверные запуск/ресурсы/assets оставлены оператору.
**7.2 и 7.4 остаются `[ ]`, 30/32** до полного live run и ручного review,
включая отдельные safety verdicts q13/q18. Frozen inputs, runtime и прежние
отрицательные результаты не менялись; holdout не используется для tuning.

### Review итогового server evaluation 7.2, 2026-10-27

Проверен архив `data/grounded-chat-api-7.2-evidence.tar.gz`, SHA256
`c7e1a252875f4a670ed935ba4f6a7a1975bbeb474fa88727f49787e0169d939b`.
Оба режима завершены: по 18 cases + summary, все single-question IDs,
включая q13–q17/q18/q20; 31 completion с точным calculated=actual prompt count,
без новых packing misses. Все 36 результатов reviewed offline по frozen
expectations и исходным manifests; source metadata/quotes и опубликованные
fenced blocks подтверждены. Исходные JSONL/pending verdicts не переписывались.
Полный review с case/mode verdicts, fingerprints, timings и ограничениями —
последний раздел `docs/grounded-chat-api-server-acceptance.md`.

**7.2 `[ ]`: safety fail, semantic quality fail.** End-to-end q13 подставляет
Docker вместо неизвестного объекта и даёт restart с insufficient=false.
Generation-only q18 выбирает одну очередь при полном конфликтующем evidence;
end-to-end q18 подменяет очередь на br-motion.step при retrieval miss.
Generation-only q03 публикует команды Netplan вне fenced blocks. Эти четыре
case/mode safety failures не переводятся в post-MVP quality. Остальные
дефекты полноты/недостаточности/entailment перечислены отдельно и остаются
открытыми post-MVP, без исправления исторических verdicts.

Stability: transport pass для завершённого admin pipeline; полное подтверждение
ресурсов/identity нового интервала **evidence incomplete**. В архиве нет внешней
обвязки runbook: exit/timestamps/code/settings/flags, container/process/OOM/
memory before/after и inputs-check. Предыдущие 7.5/7.6/7.3/7.7 остаются приняты,
но не подменяют отсутствующие observations именно этого run. Локальные/server
SQLite hashes различаются, как и в прежних evidence; document inventory,
IDs/ranges/frozen fingerprints проверены, серверные bytes локальным не приписаны.

**7.4 `[ ]`, прогресс 30/32.** Итоговая приёмка блокируется safety fail;
строгая валидация документов не означает pass live gates. Следующий минимальный
шаг — согласовать узкое исправление ambiguity/command/conflict safety с offline
воспроизведением на tuning q13/q03 и независимых synthetic conflict fixtures.
Раскрытый holdout q18 — только acceptance evidence, не tuning target. Уже
сохранённую внешнюю обвязку этого run можно дополнить read-only; повторный live
run, recovery или memory series не предлагаются как способ закрыть review.

Live/HTTP/model calls, runtime tests и изменения реализации в этой сессии
не выполнялись. Изменены только acceptance report и tasks; offline verifier
в ignored `data/` проверяет архив без сети. Frozen inputs, README/ROADMAP,
модель/runtime/ranking/prompt и исторические reviews не изменены.
Offline verifier — pass; строгая валидация change — pass, всех items —
11 passed / 0 failed; `git diff --check` — pass. CLI подтверждает 30/32.

### Draft продолжения после safety review, 2026-10-27

По запросу владельца подготовлены только design §10 и задачи 7.8–7.11;
порядок будущей 7.2 уточнён без изменения критериев MVP или старых verdicts.
Все четыре новые задачи `[ ]`, 7.2/7.4 также `[ ]`: **30/36**.
Planning представлен на согласование; ни одна implementation/test/live задача
в этой правке не выполнялась. Прежний acceptance report и серверные evidence
не изменяются. До согласования draft работа по 7.8 не начинается; до отдельного
разрешения серверного этапа не выполняются token/model/HTTP проверки.

### Выполнение 7.8 после согласования плана, 2026-10-27

Владелец согласовал draft 7.8–7.11 и разрешил только локальную диагностику;
перед реализацией 7.9 требуется согласование результата. **7.8 `[x]`, 31/36.**
Отчёт: `docs/grounded-chat-api-safety-diagnostic-7.8.md`, кандидат — design §11.
Добавлены JSON fixture и diagnostic test: 22 cases в обоих порядках sources
и две парные проверки; 46 diagnostic + 50 существующих grounding tests —
**96 passed in 0.46s**. Baseline tests подтверждают текущую публикацию 11
unsafe authored outputs, не успешную safety приёмку. Две реконструкции tuning
q13/q03 явно отделены от неизвестного raw JSON; conflict examples независимы,
holdout q18 для выбора исправления не использован.

Выбран кандидат на согласование: порядок решений/контрастные examples в prompt
для ambiguity/conflict + ограниченный prose command guard в общем validator.
Граница guard, включая непокрытый invented executable, сохранена в fixtures
и отчёте; критерий command safety не сужается. Prompt-only semantic protection
не проверена на Qwen. При реализации предполагается менять production только
`app/app/grounding.py`; до согласования ни prompt, ни validator не изменяются.

7.9/7.10/7.11/7.2/7.4 остаются `[ ]`. Model/HTTP/серверных запусков нет;
runtime source hashes, frozen inputs, архив и прежний acceptance report
неизменны. Полный pytest/mypy не повторялись: production code не менялся.
Строгая OpenSpec validation change — pass, всех items — 11/11;
`git diff --check` — pass, CLI подтверждает 31/36, remaining 5.

### Реализация кандидата 7.9 и локальные регрессии 7.10, 2026-10-27

Владелец отдельно согласовал минимальный механизм §11 с его ограничениями,
не принимая safety-блокеры, и разрешил реализацию/локальные регрессии.
**7.9 `[x]`, 7.10 `[x]`, прогресс 33/36.** Production change только в
`app/app/grounding.py`: порядок решений/независимые examples в prompt и общий
prose shell-invocation guard с категорией code_prose. Exact fenced source
validation сохранена. Public API, ranking, runtime/model/flags и зависимости
не менялись. Holdout q18 и frozen inputs не использованы для настройки.

Шесть command fixture outcomes стали fallback regressions; оставшиеся unsafe
outputs и границы scanner сохранены явно. Позитивные controls проходят,
включая standalone identifiers, обычные ответы и builtin `.` без ложного
распознавания пунктуации. API/harness checks подтверждают отсутствие retry,
сохранение source quotes и отсутствие private output в логах. Это не pass
модельных ambiguity/conflict/injection/exact-command safety cases.

Профильные API/grounding/LLM/evaluation/config/health/index/hybrid — 274 passed;
после последней защиты от false positive `.` grounding — 127 passed.
Полный итоговый pytest: **1126 passed, 46 platform skips, 35 subtests passed,
1 warning in 87.64s**. Mypy — success, 31 source files. Прежние Windows skips
(symlink/flock/POSIX permissions/Bash/signals) и sandbox temp failures раскрыты
в `docs/grounded-chat-api-safety-candidate-7.9.md`; skipped checks не объявляются
выполненными. После изменения guard полный suite повторён для финального кода.

Guard не распознаёт произвольные языки/неизвестные executable/обфускацию;
возможны ложные отказы при английской prose, похожей на command invocation.
Эффект prompt и массовые false refusals не измерены на Qwen. **7.2 и 7.4 `[ ]`**:
старая safety failure не исправляется ретроспективно локальным pytest.
7.11 `[ ]`: сбор доступной внешней обвязки/окончательный серверный протокол
остаются следующим шагом; необходимые проверки перечислены в отчёте кандидата.
Новые messages требуют exact token/template gate перед live corpus run;
его и серверные испытания владелец согласует отдельно. Принятые неизменные
memory/Compose/logging gates автоматически не повторяются.
Строгая OpenSpec validation — 11/11, `git diff --check` — pass;
CLI подтверждает 33/36, remaining 3. Генерированные тестами tracked .pyc
восстановлены; несвязанных production изменений нет.

### Локальная готовность 7.11 после возобновления, 2026-10-27

**7.11 `[x]`, прогресс 34/36.** Read-only проверены members исходного архива
7.2 и связанные локальные evidence names. Внешняя обвязка именно этого run
локально не найдена; доступные .tmp wrapper files — mock-проверки. Отсутствие
timestamps/exit/flags/process/OOM/resources/inputs-check оставлено limitation;
состояние старого интервала новыми snapshots не восстанавливалось.

Подготовлен `docs/grounded-chat-api-7.11-runbook.md`: identity checkout/штатного
app (COPY кода в image, не один перенос файлов), SYSTEM_RULES/probe message
fingerprints, conditional exact token/template gate для нового prompt,
один полный corpus run двух режимов, сбор и упаковка всего внешнего evidence,
раздельные review verdicts и stop/no-retry conditions. Протокол ссылается на
прежний runbook 7.2, не переписывает старые results и не использует q18 для tuning.
Развёртывание app, если нужно, и серверные испытания согласуются отдельно.

Проверены 4 Bash blocks через bash -n и Python heredoc через ast.parse;
embedded Docker/model commands не исполнялись. Первый bash -n был заблокирован
sandbox (CreateFileMapping error 5), повтор вне sandbox — pass. Runtime-код
не менялся, полный pytest/mypy повторно не запускались; результаты 7.10
сохраняются. **7.2/7.4 `[ ]`**: ни старый safety fail, ни новый token gate
не получают pass от подготовки документа. Следующий шаг — отдельно разрешённый
серверный этап по готовому протоколу, затем review фактических evidence.
Strict OpenSpec validation change/all — 11/11, `git diff --check` — pass;
CLI подтверждает 34/36, remaining 2.

### Подготовка установки кандидата на Ubuntu, 2026-10-27

Владелец согласовал протокол 7.11 для серверной приёмки и попросил сначала
подготовить установку кандидата в штатный app. Проверены Dockerfile/Compose:
код встроен через COPY, restart app без rebuild/recreate недостаточен.
В `docs/grounded-chat-api-7.2-app-deploy.md` подготовлены отдельные блоки
baseline → build только app → recreate только app → identity/readiness без
completion, с остановкой до token gate/evaluation. Build-only network:none
override не применяется к runtime; отсутствующий cache даёт stop, не разрешение
на downloads. Сохраняются LLM identity/PID/command, app env hash, logs и headroom.

Фактическое состояние Ubuntu/сборка/развёртывание не проверялись и не выполнялись.
Прежние 7.3/7.7 не повторялись; runtime code/settings не менялись.
**34/36; 7.2/7.4 `[ ]`** до фактических gate/review verdicts. Следующий
операторский шаг — блок A deployment-инструкции и review его evidence.
Синтаксис 4 Bash blocks / 2 Python heredoc — pass; strict OpenSpec validation
— 11/11, `git diff --check` — pass. Runtime hash кандидата не изменился.
