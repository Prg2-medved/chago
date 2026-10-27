# Готовность 7.11: приёмка кандидата 7.9, 2026-10-27

**Протокол согласован владельцем для серверной приёмки 2026-10-27.**
Исполнение поэтапное: сейчас подготовлены команды установки штатного app
в [deployment-инструкции](grounded-chat-api-7.2-app-deploy.md), они ещё не
выполнялись. Token gate/evaluation не запускаются до review установки и
соответствующего перехода к следующему этапу. Согласование протокола не является
отчётом о выполнении его серверных действий.
7.9/7.10 приняты только как реализация кандидата/локальные регрессии:
1126 passed, 46 Windows skips, 35 subtests; mypy — 31 files без ошибок.
Ограничения и риски — [отчёт 7.9](grounded-chat-api-safety-candidate-7.9.md).
Ни этот протокол, ни старые результаты не означают pass safety новой 7.2.

## Доступная обвязка прежнего run

Read-only проверены members `data/grounded-chat-api-7.2-evidence.tar.gz`
(SHA256 `c7e1a252875f4a670ed935ba4f6a7a1975bbeb474fa88727f49787e0169d939b`)
и связанные имена в локальных `data/` и `.tmp/`. В каталоге архива
`grounded-chat-api-eval.hqaD5TwH/` только два JSONL по 19 rows, два пустых
stderr, model.sha256 и image-digests.json. Локальный `7.2-offline-audit.txt`
— производный review этого же архива; runner logs/exit/start/end/flags/
resources/process/OOM/inputs-check в нём не появились. Файлы `.tmp/chat-eval-*`,
`mock-chat-eval-wrapper.sh` и `verify-chat-eval-wrapper.py` проверены по headers:
это локальный mock Docker wrapper, не server telemetry. Остальные архивы 7.3
и memory series относятся к другим интервалам и не подставляются вместо этих
данных. Поиск ограничен связанными локальными evidence, удалённый сервер не
опрашивался. На сервере ещё могут быть файлы, которые сюда не переданы.

**Внешняя обвязка старой 7.2 локально не найдена.** Старый resource/runtime
verdict остаётся evidence incomplete. Tar mtime — время изменения файлов,
не доказательство начала/конца генерации; восстановить прошлое состояние по
новым snapshots нельзя. Прежние safety/quality failures сохраняются даже
при последующей передаче дополнительных metadata.

## Фиксация варианта до серверного этапа

У кандидата изменились SYSTEM_RULES/messages; поэтому token pass 7.1 старого
варианта не переносится. Локально вычислены, без token endpoints/inference:

| Identity | SHA256 |
| --- | --- |
| app/app/grounding.py, exact file bytes | `1587022b84f4ab1ad586403ab673516defa455d77c34b18b330343891b0c045a` |
| SYSTEM_RULES UTF-8 | `a2619f7c53f8149a89891654571592f09bb0679234bedef13e90ccb8d54085fe` |
| Canonical one-word boundary fixture messages | `a7fed6720da4dc11bb5d339970f1c82a5b75b9c5b47224ad858184335ee096ee` |

Последний fingerprint относится к `build_messages(BOUNDARY_QUESTION,
boundary_manifest(1))` с JSON ensure_ascii=False/sort_keys=True/separators=(',',':').
Это воспроизводимый fingerprint probe messages, **не** число токенов и не hash
каждого packed corpus prompt. Реальные token counts устанавливаются только live.
LLM RepoDigest/model SHA256 остаются прежними pinned values из wrapper.

После отдельного согласования серверного этапа нужны offline assets, штатные
app/LLM без другого traffic и подтверждённое отсутствие незавершённой генерации.
`health=ok` этого не доказывает. Не начинать при MemAvailable <2097152 KiB.
Кандидат должен быть установлен в штатный app **до** проверки: Compose app
содержит COPY кода в image, перенос checkout сам по себе app не обновляет.
Развёртывание/сборка app, если нужны, согласуются отдельно; этот протокол их
автоматически не выполняет. Не менять LLM/flags/settings/resources/swap.

## Последовательность после разрешения

Использовать [runbook 7.2](grounded-chat-api-7.2-runbook.md) с дополнениями ниже.
Его прежнее требование остановки при изменении messages заменяется **только для
этого согласованного кандидата** новым identity check и token gate. Другие
расхождения требуют остановки; это не разрешение менять дальнейшие варианты.

1. Выполнить подготовительный блок **шага 1** прежнего runbook: закрытый
   `$evidence`, frozen paths, containers/settings/flags, code/input hashes и
   baseline resources. Сохранить также INDEX_PATH и StartedAt, не полный env.
   Ниже `$app_id`, `$llm_id`, `$evidence` — уже заданные переменные того блока:

```bash
docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$app_id" \
  | sed -n '/^INDEX_PATH=/p' > "$evidence/active-index-path.txt"
docker inspect --format '{{.Id}} started={{.State.StartedAt}} image={{.Image}}' \
  "$app_id" "$llm_id" > "$evidence/container-started-at.txt"
sha256sum docs/grounded-chat-api-final-token-smoke.sh app/app/chat_token_check.py \
  > "$evidence/token-check-code.sha256"
```

2. Без completion проверить код в checkout и штатном app. Это исключает ситуацию,
   когда admin harness bind-mount уже использует новый код, а HTTP app — старый:

```bash
test "$(sha256sum app/app/grounding.py | cut -d ' ' -f1)" = \
  1587022b84f4ab1ad586403ab673516defa455d77c34b18b330343891b0c045a
docker exec -i "$app_id" python -B - > "$evidence/candidate-identity.json" <<'PY'
import hashlib, json
from pathlib import Path
import app.grounding as grounding
from app.chat_token_check import BOUNDARY_QUESTION, boundary_manifest
code = hashlib.sha256(Path(grounding.__file__).read_bytes()).hexdigest()
rules = hashlib.sha256(grounding.SYSTEM_RULES.encode()).hexdigest()
messages = grounding.build_messages(BOUNDARY_QUESTION, boundary_manifest(1))
probe = hashlib.sha256(json.dumps(messages, ensure_ascii=False, sort_keys=True,
                                separators=(',', ':')).encode()).hexdigest()
assert code == '1587022b84f4ab1ad586403ab673516defa455d77c34b18b330343891b0c045a'
assert rules == 'a2619f7c53f8149a89891654571592f09bb0679234bedef13e90ccb8d54085fe'
assert probe == 'a7fed6720da4dc11bb5d339970f1c82a5b75b9c5b47224ad858184335ee096ee'
print(json.dumps(dict(code_sha256=code, system_rules_sha256=rules,
                     boundary_probe_messages_sha256=probe)))
PY
```

Если hash не совпал, не пробовать completion и не нормализовать исходники ради
совпадения без review расхождения. Код app не bind-mounted в текущем Compose;
StartedAt/image identity дополняют проверку файлов, не заменяются только health.

3. Выполнить **один** условно необходимый gate для окончательных messages,
   сохранив stdout/stderr/exit. Скрипт использует тот же app image ID, read-only
   checkout/data mounts и pinned LLM, без build/pull и без смены runtime:

```bash
date -u +%FT%TZ > "$evidence/token-start.txt"
set +e
bash docs/grounded-chat-api-final-token-smoke.sh \
  > "$evidence/token.jsonl" 2> "$evidence/token.stderr"
token_status=$?
set -e
printf '%s\n' "$token_status" > "$evidence/token.exit"
date -u +%FT%TZ > "$evidence/token-end.txt"
if test "$token_status" -ne 0; then
  printf '%s\n' 'STOP: token gate failed; preserve evidence; no corpus or retry.'
  exit 1
fi
```

Просмотреть JSONL: identity/settings/template hash, index hash/metadata,
`final_retrieved_prompt` и `prompt_plus_reserve_equals_window` с equal=true,
финальный gate_7_1=passed, overflow_completion_sent=false и index_unchanged=true.
Скрипт отправляет два completion: retrieved tuning q01 и synthetic boundary;
поиск границы использует только template/tokenize, overflow без completion.
Pass включает реальный calculated=actual usage.prompt_tokens, reserve и окно;
exit=0 без требуемых записей не принимается. Старые counts не подставляются.
INDEX_PATH в этом gate — active index приложения; корпус использует отдельные
FROZEN_LIVE_INDEX/FROZEN_SYNTHETIC_INDEX из шага 1. Их hashes/metadata не смешивать
и не заменять evaluation-индексы production SQLite.

При failed/timeout/transport/uncertain gate сохранить частичный `$evidence`;
не переходить к corpus и не выполнять автоматический retry/recovery. Не удалять
evidence, даже если два режима ещё не запускались. Установленный механизм
manual recovery остаётся прежним и требует отдельного осознанного действия.

4. Только после pass gate и достаточного headroom выполнить **шаг 2** старого
   runbook — один полный `grounded-chat-api-evaluate.sh` без `--case`, без
   добавочных completions/перестановок. Затем structural checks **шага 3**,
   дополнительные logs/checks ниже и лишь после них — упаковка из шага 3
   **всего внешнего `$evidence`** (включая token logs/identity), а не одного
   inner `grounded-chat-api-eval.*`. Вновь сохранить container/process/
   OOM/restart, memory/stats, app+LLM logs нового интервала и inputs-check:

```bash
docker compose logs --no-color --timestamps --since "$(cat "$evidence/start.txt")" \
  app > "$evidence/app.log" 2>&1
sha256sum -c "$evidence/code.sha256" > "$evidence/code-check.txt"
sha256sum -c "$evidence/token-check-code.sha256" > "$evidence/token-check-code-check.txt"
```

Последний блок выполнить **до** упаковки. Во время всего интервала оператор
наблюдает ресурсы; stop при новом OOM/выходе LLM/нехватке headroom/transport
failure. До recovery новых completions нет. Snapshots не выдаются за непрерывную
memory telemetry/пики; 20-запросная серия, fault injection и принятые 7.3/7.7
не повторяются автоматически. Это admin corpus run, не повтор HTTP semaphore gate.

5. Review всех 36 rows отдельно по stability, safety и semantic quality:
   unanswerable/неизвестный объект, оба conflicting values с citations,
   команды в prose/inline и точность fenced bodies по source, injection,
   ordinary answers и необоснованные refusals. Сохранить retrieval/packing
   misses и оставшиеся ограничения scanner. Наличие code_prose fallback —
   защита, не доказательство успешного полного ответа; отсутствие этой категории
   не доказывает, что команда безопасна. Holdout q18 — только итоговый review,
   без повторов за хорошим ответом или настройки после раскрытия результата.

При pass stability+safety можно закрывать 7.2 и переходить к 7.4; при fail
сохранить blocker, не переносить его в post-MVP quality. Исторические fail
verdicts сохраняются. Проверки follow-up/UI и весь MVP продукта сюда не входят.

## Локальная проверка протокола

Read-only inventory evidence, hashes кода/SYSTEM_RULES/probe messages вычислены
локально. Bash blocks проверяются только `bash -n`, Python heredoc — compile
без исполнения. Ни одна Docker/model команда из документа локально не запущена.
Runtime code после 7.9 не менялся; полный pytest/mypy не повторяются без причины.
Strict OpenSpec validation change/all — pass (11/11), `git diff --check` — pass.
7.11 завершена: **34/36**, открыты 7.2/7.4. Остаточные safety/quality failures
не получают pass от синтаксической проверки протокола.
