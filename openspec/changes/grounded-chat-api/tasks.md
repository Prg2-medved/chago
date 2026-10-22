# Tasks

> Review draft, 2026-10-22: пересмотр MVP по решению владельца; реализация до
> согласования не начинается. Принятые 1.1–7.1 сохранены. Ни одна новая проверка
> не отмечена выполненной. При неизменных messages/runtime gate 7.1 не повторяется.

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
порядке выполнения: **7.5 → 7.6 → 7.3 → 7.2 → 7.4**. В 7.3 сначала проверяется
concurrency/cancellation/timeout, затем ручной recovery, затем offline/isolation.

- [x] 7.5 Свести уже собранные OOM/kernel/container/recovery results из разделов acceptance report, перечисленных в design §9: global_oom/CONSTRAINT_NONE, PID 3709157/anon-rss, OOMKilled/exit=137/PID=0/limits=0, подтверждённый stop/start LLM/restart app, readiness и baseline, завершённый q01 transport. Повторные inspect/kernel/health/recovery команды не запрашивать без конкретно названного пробела и объяснения недостаточности имеющихся данных. Отделить установленный global OOM от неизвестного механизма большого anon-rss и гипотез leak/cache. Недостающие memory series/peaks собирать в 7.6; свежий pre-run baseline относится к новому интервалу, а не повтору прежнего recovery. Не менять модель/image/flags/ресурсы/swap/сторонние сервисы; не объявлять OOM устранённым или серию устойчивой по единичному recovery.
- [ ] 7.6 После 7.5 выполнить оператором 20 последовательных end-to-end tuning HTTP chat запросов в точном порядке design §9, включая повторы, без generation-only/добавочных completions или замены cases. Samples раз в секунду для app/LLM/временных harness containers и host MemAvailable/swap; boundaries/status/counts/timings, post-response memory, доступные peak/OOM/process counters и index identity. Stop при MemAvailable <2 GiB (2097152 KiB), новом OOM, завершении LLM или transport/uncertain failure; при исходном значении ниже порога не начинать, retry до recovery запрещён. Порог консервативный, не гарантирует предотвращения OOM. Pass только для полной серии с headroom/telemetry; оценить тренд всей серии, пики и повторные одинаковые cases. Продолжающийся необъяснённый рост или недостаточный headroom оставляют gate открытым независимо от монотонности последних пяти samples. Раскрыть sampled peak limitations; не объявлять отсутствие leak на любой нагрузке. Holdout не включать и не использовать для настройки.
- [ ] 7.3 После 7.6 проверить через Compose два одновременных HTTP chat запроса, cancellation с поздним полным ответом и с поздним timeout. До операторского timeout испытания подготовить конкретную воспроизводимую fault-injection процедуру по design §9: команды/preconditions/timeline/upstream completion count/cleanup, без изменения production flags/settings/timeout и без следующего completion при generation_uncertain. Без безопасной процедуры испытание не начинать, gate не закрывать. Подтвердить timeout приложения при возможной продолжающейся генерации, 504 исходному/503 ожидающим и новым, отсутствие upstream completion/retry от проверочных chat requests и сохранение блокировки при health=ok/задержке. Только затем подтверждённая остановка прежней LLM, её запуск и restart app разрешают новый completion; проверить успешный chat и неизменный index. Затем `/health` во время генерации, app-only/offline restart, один worker/одну генерацию, отсутствие host-published LLM port, downloads/внешних API и Wiki.js access/writes; сохранить evidence и SQLite hash/metadata до/после. Исторический OOM/recovery и unit tests этот Compose gate не заменяют.
- [ ] 7.2 После 7.5/7.6/7.3 выполнить итоговый live MVP run на закреплённой Qwen: end-to-end single-question corpus, все answerable=false и synthetic security/conflict cases, отдельно generation-only на фиксированном достаточном evidence. Раздельно оценить stability, safety и semantic quality. API/validators/fallback, exact commands, unanswerable/ambiguity/conflict/injection safety обязательны; известные q13 (неоднозначный объект) и q18 (противоречие) потенциально блокируют safety, их нельзя автоматически перенести в качество. MVP требует pass stability и safety; изолированные defects required facts/kind/entailment остаются post-MVP, не отменяя safety fail. Сохранить ответы/IDs/counts/timings/settings/fingerprints/misses/ограничения и прежнюю непройденную 7.2; frozen inputs не менять, раскрытый holdout (включая q18) не использовать для настройки. Не требовать Hit@5 ≥90%, не заявлять follow-up acceptance и не повторять неизменные завершённые проверки без причины.
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
