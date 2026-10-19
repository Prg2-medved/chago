# Ручной запуск task 5.7: Windows → Linux/Docker

Подготовлено по текущему worktree, protocol v2 и фактическому API. Это **только
инструкция**, серверные команды не выполнялись. 5.7 остаётся `[ ]`.
Три arms: legacy `10/1/60/6`, control `120/1/60/6`, reranker на полном union
control. Никаких rebuild, historical holdout retrieval, independent validation,
lock, commit/push или перезапусков сервисов.

После исправления environment comparison упаковывать обновлённые tools до
серверного запуска. Если transport уже подготовлен, использовать новый RunId;
прежние архивы/logs/results сохранить. Старые reports с полным `cpuinfo` внутри
`environment` не переписывать под новую схему и не смешивать с новыми workers.

Выполнять блоки последовательно. При любой ошибке остановиться, сохранить
логи, не обходить gate сменой модели/лимитов/policy/бюджетов. Не повторять
quality-запуски ради улучшения результата. Повтор 2 — только идентичная
проверка воспроизводимости после успешного повтора 1. Existing indices только
читаются из **доставленной копии**, каталог работающего проекта не обновляется.

Вспомогательные scripts — новые инструменты измерения, а не новые параметры
приложения. `worker` вызывает существующие `HybridIndex`, `RerankedIndex`,
`protocol_input`, `evidence_hit`, `retrieval_diagnostics`. Scorer получает
top-5 из final k=6. Все 14 tuning cases исполняются в frozen order; девять live
answerable single questions образуют denominator, follow-up/synthetic/answerless
сохраняются отдельно. Frozen questions читаются как JSON для фильтрации `tuning`;
holdout не диагностируется и не передаётся retrieval/scorer. Hashing protected
файлов/исторических reports не является повторным quality experiment.

**1. Windows / PowerShell — подготовить transport, без Git для весов.**

```powershell
Set-Location D:\Dev\chago
$ErrorActionPreference = 'Stop'
$RunId = '20261019-01'
$TestLog = 'data/retrieval-quality-improvement/reranker-v2/manual-local-checks.txt'
if (Test-Path $TestLog) { throw 'STOP: local test evidence already exists; preserve/review it' }
.venv/Scripts/python.exe docs/retrieval-quality-5-7-test.py 2>&1 | Tee-Object -FilePath $TestLog
if ($LASTEXITCODE -ne 0) { throw 'STOP: measurement tests failed' }
Push-Location app
try {
    ../.venv/Scripts/python.exe -m pytest tests/test_reranking.py tests/test_hybrid_retrieval.py tests/test_retrieval_evaluation.py tests/test_retrieval_config.py tests/test_retrieval.py tests/test_health.py -q -p no:cacheprovider --basetemp "../data/retrieval-quality-improvement/reranker-v2/manual-checks-$RunId" 2>&1 | Tee-Object -FilePath "../$TestLog" -Append
    if ($LASTEXITCODE -ne 0) { throw 'STOP: functional regression tests failed' }
} finally {
    Pop-Location
}
$Transfer = "data/retrieval-quality-improvement/reranker-v2/transfer-$RunId.tar"
if (Test-Path $Transfer) { throw 'STOP: transport already exists' }
.venv/Scripts/python.exe docs/retrieval-quality-5-7-tools.py pack --output $Transfer
if ($LASTEXITCODE -ne 0) { throw 'STOP: pack/hash verification failed' }
Get-FileHash $Transfer -Algorithm SHA256
Get-FileHash ($Transfer -replace '\.tar$', '.json') -Algorithm SHA256
git ls-files data/models
```

Ожидается: 8 synthetic measurement tests и 75 functional regression tests прошли;
проверены 76 committed identities, создан TAR и JSON manifest;
`git ls-files data/models` пуст. В TAR включён фактический изменённый/untracked
код, pinned E5/CE assets, frozen inputs, v1 receipts и все 36 reports.
`.git`, `.env`, токены, LLM weights и другие data-каталоги не копируются.
SHA-256 manifest сохраняет текущую transport identity; это не acceptance lock.
STOP: missing/hash mismatch, непустой список tracked weights, повторное имя.
При изменении исходников после упаковки создать новый RunId до inference.

**2. Windows / PowerShell — доставить в новый sibling-каталог.**

Команды ниже пользователь выполняет вручную; агент их не выполнял.
При первом SSH проверить fingerprint сервера по доверенному источнику.

```powershell
ssh prg2@srv-ubdev 'umask 077; mkdir /home/prg2/chago-llm/rq57-20261019-01'
if ($LASTEXITCODE -ne 0) { throw 'STOP: remote directory not new or SSH failed' }
scp $Transfer 'prg2@srv-ubdev:/home/prg2/chago-llm/rq57-20261019-01/payload.tar'
if ($LASTEXITCODE -ne 0) { throw 'STOP: TAR transfer failed' }
scp ($Transfer -replace '\.tar$', '.json') 'prg2@srv-ubdev:/home/prg2/chago-llm/rq57-20261019-01/transport.json'
if ($LASTEXITCODE -ne 0) { throw 'STOP: manifest transfer failed' }
ssh prg2@srv-ubdev
```

Ожидается: только два новых файла вне `/home/prg2/chago-llm/chago`.
STOP: SSH/SCP ошибка, несовпадающий SSH fingerprint, каталог уже существует.

**3. Linux / Bash — проверить host и архив, распаковать изолированно.**

```bash
set -Eeuo pipefail
umask 077
export RUN_ID=20261019-01
STAGE=/home/prg2/chago-llm/rq57-$RUN_ID
cd "$STAGE"
python3 -c 'import sys; assert sys.version_info >= (3,11), sys.version'
command -v docker
command -v vmstat
docker compose version
docker info --format 'cgroup={{.CgroupVersion}} driver={{.CgroupDriver}}'
lscpu > host-cpu.txt
grep -F 'i5-14400' host-cpu.txt
df -h .
free -h
vmstat -w 1 5
docker ps --no-trunc --format '{{.ID}} {{.Image}} {{.Names}} {{.Status}}' > services-before.txt
sha256sum payload.tar transport.json
python3 - <<'PY'
import hashlib, json, pathlib, tarfile
m = json.load(open('transport.json'))
with open('payload.tar', 'rb') as f:
    assert hashlib.file_digest(f, 'sha256').hexdigest() == m['archive_sha256']
target = pathlib.Path('payload')
target.mkdir()  # Must be new.
with tarfile.open('payload.tar') as t:
    members = t.getmembers()
    names = [x.name for x in members]
    assert len(names) == len(set(names))
    assert set(names) == set(m['files'])
    for item in members:
        p = pathlib.PurePosixPath(item.name)
        assert item.isfile() and not p.is_absolute() and '..' not in p.parts
        output = target.joinpath(*p.parts)
        output.parent.mkdir(parents=True, exist_ok=True)
        with t.extractfile(item) as source, output.open('xb') as dest:
            import shutil
            shutil.copyfileobj(source, dest)
PY
cp --no-clobber transport.json payload/transport.json
cd payload
python3 docs/retrieval-quality-5-7-tools.py check
bash -n docs/retrieval-quality-5-7-run.sh
```

Ожидается: archive SHA совпадает с Windows и JSON; check выдаёт `passed: true`.
Сравнить также SHA самого `transport.json` с Windows. Нужны cgroup v2,
доступ к Docker, Python ≥3.11 на host и preregistered i5-14400.
STOP: любое несовпадение, missing command, иной CPU/cgroup, недостаточно места
для TAR + распаковки + image/build cache + results или нехватка RAM для 5 GiB
worker вместе с работающими сервисами. Не считать прежние «12 GB/8.1 GiB»
актуальным измерением. Активный swap I/O — повод остановиться и устранить
внешнюю нагрузку до inference, не менять лимиты эксперимента.

**4. Linux / Bash — собрать отдельный image через Compose.**

```bash
OUT="$PWD/data/retrieval-quality-improvement/reranker-v2/manual-$RUN_ID"
export OUT
mkdir "$OUT"
cat > ../compose-screening.yaml <<'YAML'
services:
  app:
    image: chago-rq57:20261019-01
    build:
      context: ./payload/app
YAML
docker compose --project-name rq57-20261019-01 --env-file /dev/null \
  -f ../compose-screening.yaml config > "$OUT/compose-resolved.yaml"
docker compose --project-name rq57-20261019-01 --env-file /dev/null \
  -f ../compose-screening.yaml build app > "$OUT/image-build.log" 2>&1
export IMAGE=$(docker image inspect chago-rq57:20261019-01 --format '{{.Id}}')
test -n "$IMAGE"
printf '%s\n' "$IMAGE" > "$OUT/image-id.txt"
docker image inspect "$IMAGE" > "$OUT/image-inspect.json"
cp ../host-cpu.txt ../services-before.txt "$OUT/"
cp transport.json "$OUT/transport.json"
cp docs/retrieval-quality-experiment-protocol-v2.md docs/retrieval-quality-protocol-receipt-v2.json "$OUT/"
cp data/retrieval-quality-improvement/reranker-v2/manual-local-checks.txt "$OUT/"
```

Ожидается: новый image с текущим кодом из TAR и существующим
`app/requirements.txt`; работают прежние containers. Build может обращаться
к package registries для provision существующих pinned dependencies, это
не inference. Отдельные project name/image tag исключают подмену app image.
`docker compose images -q app` в работающем проекте здесь не используется:
он мог бы вернуть image старого контейнера.
STOP: build error, resolver конфликт, недостаток диска. Не запускать `up`,
`restart`, `down`, `exec` в работающих app/LLM/Wiki.js.

**5. Linux / Bash — задать одинаковую изоляцию всех служебных workers.**

```bash
offline_python() {
  docker run --rm --network none --read-only --cpus 4 --memory 5g --memory-swap 5g \
    --tmpfs /tmp:rw,nosuid,nodev,size=256m --user "$(id -u):$(id -g)" \
    -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e HF_HUB_OFFLINE=1 \
    -e TRANSFORMERS_OFFLINE=1 -e HF_HUB_DISABLE_TELEMETRY=1 -e TOKENIZERS_PARALLELISM=false \
    -e OMP_NUM_THREADS=4 -e MKL_NUM_THREADS=4 -e OPENBLAS_NUM_THREADS=4 \
    --mount "type=bind,src=$PWD,dst=/work,readonly" \
    --mount "type=bind,src=$OUT,dst=/out" -w /work "$IMAGE" python "$@"
}
offline_python -m pip check > "$OUT/pip-check.txt" 2>&1
offline_python -m pip freeze --all > "$OUT/pip-freeze.txt"
offline_python docs/retrieval-quality-5-7-tools.py check > "$OUT/protected-before.json"
du -B1 -s "data/models/1427fd652930e4ba29e8149678df786c240d8825" > "$OUT/bundle-disk-allocated.txt"
du -B1 --apparent-size -s "data/models/1427fd652930e4ba29e8149678df786c240d8825" > "$OUT/bundle-disk-apparent.txt"
df -B1 . > "$OUT/disk-before.txt"
```

Ожидается: `No broken requirements found`, matching hashes. CE logical files
487,679,201 bytes; `du` дополнительно считает directory/allocation overhead.
Это disk increment sole model, доставка также хранит E5/копии protected inputs
и архив. Их общий размер не выдаётся за increment reranker.
STOP: несовместимые зависимости, hash mismatch, ошибка bind/лимитов.

**6. Linux / Bash — общий token preflight и offline compatibility до scoring.**

```bash
offline_python docs/retrieval-quality-5-7-tools.py preflight \
  --output /out/preflight.json > "$OUT/preflight.stdout.txt" 2> "$OUT/preflight.stderr.txt"
python3 - "$OUT/preflight.json" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))
assert r['passed'] and r['network_attempts'] == 0 and not r['cross_encoder_quality_inference']
assert len(r['cases']) == 14
assert sum(len(c['pairs']) for c in r['cases']) == 1682
assert r['maximum_pair_tokens'] == 469
print('pairs:', sum(len(c['pairs']) for c in r['cases']))
print('max pair:', r['maximum_pair_tokens'])
print(json.dumps(r['environment'], indent=2))
PY
```

Ожидается: 14 tuning cases, 1682 pairs, max pair 469/512; questions ≤128;
model/runtime identities в отчёте. Сперва preflight **всех** pairs, затем
guarded local-only FP32 model load без CE inference. E5 retrieval загружает E5;
CE загружается рядом с ним для проверки совместимости. Worker проверяет
cgroup memory.max=5368709120, swap.max=0, CPU quota=4; missing counters — ошибка.
STOP: overflow любого pair, missing/corrupt asset, CUDA build, runtime mismatch,
network attempt, ошибка загрузки/cgroup или отличие от ожидаемого preflight.
Не обрезать, не исключать кандидатов и не повышать budgets.

**7. Linux / Bash — первый fresh sequential повтор трёх arms.**

```bash
bash docs/retrieval-quality-5-7-run.sh 1
cat "$OUT/summary-1.stdout.txt"
```

Ожидается: legacy → control → reranker, по одному fresh container на arm.
Внутри каждого одного процесса: first pass, затем warm pass; модели сохраняются
resident, caches не сбрасываются. Полный union ранжируется до final cutoff.
Нет дополнительных прогревочных запросов. До/после каждого arm проверяются
protected/transport SHA. Сохраняются logs, Docker inspect, vmstat/free/meminfo,
whole-worker peak RSS, kernel cgroup memory.peak/events/cpu.stat, swap counters,
per-query end-to-end/branches/tokenization/rerank, model init/load, все finite
scores/ranks/union input hashes, coverage/witness/partial и follow-up transitions.
`summary-1.json` содержит Hit@5 `/9` и warm arithmetic mean ratio.
STOP немедленно: ошибка/OOM/cap/network/integrity/повторяемости, <8/9 или
candidate warm mean >2× legacy. При ранней ошибке JSON может отсутствовать:
inspect/logs являются failure evidence, не pass. До повтора 2 не переходить.

**8. Linux / Bash — второй fresh sequential повтор, только после успеха первого.**

```bash
bash docs/retrieval-quality-5-7-run.sh 2
cat "$OUT/summary-2.stdout.txt"
```

Ожидается: ещё ровно три fresh workers, first/warm passes. Проверяются exact
same-environment serialized scores/ranks/counts/union/input hashes между
повторами, first↔warm и identity control↔reranker↔preflight.
Оба warm ratios ≤2, denominator 9, единственный возможный miss — legacy q03.
Все hit→miss относительно **обоих** controls сохраняются; это отчётность,
не отдельный exclusion gate. Сравнивается только стабильная `environment`:
версии Python/packages/libc/OS/kernel, архитектура, CPU vendor/family/model/
stepping/microcode, topology/cache/address sizes и отсортированные flags.
Полный `/proc/cpuinfo` (включая текущую `cpu MHz`, bogomips и прочие
диагностические поля) и hostname сохраняются отдельно в
`environment_diagnostics` и не участвуют в exact comparison. Изменение стабильных
полей по-прежнему останавливает experiment. Latency/RSS не обязаны совпадать.
STOP: любое расхождение или gate failure. Никакого нового tuning cycle.

**9. Linux / Bash — проверить evidence и сохранить результаты даже при провале.**

При успешных двух повторах:

```bash
offline_python docs/retrieval-quality-5-7-tools.py check > "$OUT/protected-after.json"
docker ps --no-trunc --format '{{.ID}} {{.Image}} {{.Names}} {{.Status}}' > "$OUT/services-after.txt"
diff -u <(awk '{print $1,$2,$3}' "$OUT/services-before.txt" | sort) \
        <(awk '{print $1,$2,$3}' "$OUT/services-after.txt" | sort)
df -B1 . > "$OUT/disk-after.txt"
python3 - "$OUT" <<'PY'
import json, pathlib, sys
p = pathlib.Path(sys.argv[1])
for n in (1, 2):
    s = json.load(open(p / f'summary-{n}.json'))
    assert not s['failures'] and not s['quality_acceptance']
    r = json.load(open(p / f'reranker-{n}.json'))
    singles = [x for x in r['rows'] if x['pass'] == 'warm' and x['source_set'] == 'live'
               and x['answerable'] and not x['follow_up']]
    for suffix, minimum in (('q02', 3), ('q07', 1), ('q03', 6)):
        rows = [x for x in singles if x['id'].endswith(suffix)]
        assert len(rows) == 1, suffix
        row = rows[0]
        assert row['diagnostics']['inventory']['minimum'] == minimum
        assert row['hit'] == (suffix != 'q03')
        print(n, row['id'], row['hit'], row['diagnostics']['final_top_5'])
    assert sum(x['hit'] for x in singles) == 8
print('Review resource logs and functional evidence before task 5.8; no acceptance lock.')
PY
```

Ожидается: unchanged service IDs/images/names, protected hashes, полные q02
три chunks и q07 один chunk в top-5, q03 minimum=6/miss. Не считать partial
coverage hit. Проверить `*.vmstat.txt`: первая строка — среднее с boot,
последующие — текущие si/so; `free`/`meminfo` дают host available RAM/swap.
Worker `swap.max=0` запрещает swap контейнера; host swap может относиться к
другим сервисам, его нельзя приписывать модели без evidence. Missing logs,
OOM/max events, ошибки, вытеснение рабочих сервисов или неясная нехватка
ресурсов оставляют gate incomplete до review. Не менять swap/sysctl host.

Сохранение доступных результатов выполняется **и после STOP**, без новых
inference-запусков (оставить тот же `$OUT`, `$STAGE`):

```bash
cd "$STAGE"
RESULTS=rq57-$RUN_ID-results.tar
test ! -e "$RESULTS"
tar -cf "$RESULTS" -C payload "data/retrieval-quality-improvement/reranker-v2/manual-$RUN_ID"
sha256sum "$RESULTS" > "$RESULTS.sha256"
cat "$RESULTS.sha256"
```

Ожидается: новый results TAR и checksum. STOP: ошибка архива/места или
существующее имя; не перезаписывать прежние evidence. Measurement containers
оставлены stopped для review, никакой автоматической очистки работающих services.

**10. Windows / PowerShell — скачать и сверить results.**

```powershell
Set-Location D:\Dev\chago
$ResultsDir = "data/retrieval-quality-improvement/reranker-v2/download-$RunId"
if (Test-Path $ResultsDir) { throw 'STOP: download directory already exists' }
New-Item -ItemType Directory $ResultsDir | Out-Null
scp "prg2@srv-ubdev:/home/prg2/chago-llm/rq57-$RunId/rq57-$RunId-results.tar*" $ResultsDir
if ($LASTEXITCODE -ne 0) { throw 'STOP: download failed' }
$ResultTar = Join-Path $ResultsDir "rq57-$RunId-results.tar"
$Expected = ((Get-Content "$ResultTar.sha256") -split '\s+')[0]
if ((Get-FileHash $ResultTar -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Expected) {
    throw 'STOP: results SHA-256 mismatch'
}
tar -tf $ResultTar
```

Ожидается: matching SHA и только новый `.../reranker-v2/manual-$RunId/`.
STOP: mismatch/неожиданные пути. Не распаковывать поверх v1 или input files.

Даже успешные автоматические checks — evidence для review 5.7/5.8, не
автоматическая отметка tasks. Проверить полноту resource/functional evidence,
включая сохранённый отчёт целевых local regression tests для доставленной
code identity. Отсутствующие обязательные измерения — incomplete, не pass.
При успехе допустим следующий отдельный шаг 5.8, затем 5.3 lock; порядок
остаётся lock → frozen ≥11/12 → server acceptance → independent ≥90%.
Этот runbook не выполняет ни один из этих финальных шагов.

Точность timings: `seconds` охватывает полный `search`, включая встроенные
preflight/trace; diagnostics и JSON serialization идут после timer. `first`
содержит lazy model load; отдельные load durations также записаны. Инициализация
tokenizer/index до первого search записана отдельно. Tokenization duration —
вложенная часть CE search/rerank, её нельзя прибавлять к end-to-end повторно.
First query — первая строка first pass; warm mean считается только по девяти
single questions, follow-up latency остаётся отдельной строкой. cgroup peak
включает worker/runtime/page cache до сохранения отчёта; post-run inspect
проверяет exit/OOM в том числе при serialization/завершении. `cpu.stat` и
process user/system seconds показывают фактический CPU, quota ограничивает 4
CPU, `vmstat` показывает host load. Build-only метрики v2 явно N/A, historical
v1 build records доставлены и остаются неизменными.
