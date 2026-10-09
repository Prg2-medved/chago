# Приёмка lexical-and-hybrid-retrieval на Linux/Docker

Задача 5.4 остаётся открытой до фактического серверного отчёта. Эта инструкция
сверена с `app/Dockerfile`, `compose.yaml` и реализацией CLI. Команды выполняются
последовательно в **одной Bash-сессии** из проекта `/home/prg2/chago-llm/chago`.
Python работает только внутри отдельного image. Runtime-контейнеры используют
`--network none`; рабочие app, llm, Wiki.js и другие контейнеры продолжают работу.

Однократно выполняются подготовка image и проверка установленных assets. Для
повторной приёмки создайте новый каталог результатов, переиспользуйте image по
сохранённому ID и повторите проверки, начиная с раздела 3. Повторные evaluation
запуски ниже используют одну заранее зафиксированную configuration. Holdout уже
измерялся в предыдущем semantic baseline и в development comparison; новый
серверный запуск не является blind evaluation и не используется для tuning.

## 1. Подготовка окружения и отдельного каталога

Проверьте, что сервер получил код этого change. Пути ниже соответствуют
предыдущему semantic этапу. Если обязательного файла нет, остановитесь и
найдите сохранённый оригинал; не пересоздавайте frozen corpus или snapshots.
`WIKI_URL` — доступный с хоста URL обычной существующей Wiki.js страницы.
HTTP-пробы выполняются с хоста для измерения работающего Wiki.js; inference,
build и evaluation остаются в контейнерах без сети.

```bash
set -euo pipefail
PROJECT=/home/prg2/chago-llm/chago
cd "$PROJECT"
DATA="$PROJECT/data"
FROZEN="$PROJECT/eval"
MODEL_REVISION=614241f622f53c4eeff9890bdc4f31cfecc418b3
RESULTS_ROOT="$PROJECT/acceptance/lexical-and-hybrid-retrieval"
mkdir -p "$RESULTS_ROOT"
ACCEPTANCE_DIR=$(mktemp -d "$RESULTS_ROOT/run-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")
printf 'Результаты: %s\n' "$ACCEPTANCE_DIR"
read -r -p 'URL существующей Wiki.js страницы для HTTP-проб: ' WIKI_URL
test -n "$WIKI_URL"
for command in docker curl sha256sum vmstat free lscpu; do
    command -v "$command" >/dev/null
done
docker version > "$ACCEPTANCE_DIR/docker-version.txt"
docker compose config --services > "$ACCEPTANCE_DIR/compose-services.txt"
docker compose ps > "$ACCEPTANCE_DIR/compose-before.txt"
git rev-parse HEAD > "$ACCEPTANCE_DIR/git-head.txt"
git status --short > "$ACCEPTANCE_DIR/git-status-before.txt"
uname -a > "$ACCEPTANCE_DIR/uname.txt"
lscpu > "$ACCEPTANCE_DIR/cpu.txt"
free -b > "$ACCEPTANCE_DIR/memory-before.txt"
df -h "$PROJECT" > "$ACCEPTANCE_DIR/disk.txt"

for file in \
    "$DATA/semantic-live.db" "$DATA/semantic-synthetic.db" \
    "$DATA/eval/1/wiki-documents.json" \
    "$FROZEN/questions.yaml" "$FROZEN/manifest.json" \
    "$FROZEN/fixtures/wiki-documents.json" \
    "$PROJECT/docs/semantic-retrieval-baseline.json" \
    "$PROJECT/app/app/embedding_manifest.json"; do
    test -r "$file"
done
test -r "$DATA/models/$MODEL_REVISION/model.safetensors"

sha256sum \
    "$DATA/semantic-live.db" "$DATA/semantic-synthetic.db" \
    "$DATA/eval/1/wiki-documents.json" \
    "$FROZEN/questions.yaml" "$FROZEN/manifest.json" \
    "$FROZEN/fixtures/wiki-documents.json" \
    "$PROJECT/docs/semantic-retrieval-baseline.json" \
    "$PROJECT/app/app/embedding_manifest.json" \
    > "$ACCEPTANCE_DIR/inputs-before.sha256"
find -L "$DATA/models/$MODEL_REVISION" -type f -print0 \
    | sort -z | xargs -0 sha256sum > "$ACCEPTANCE_DIR/model-before.sha256"

mapfile -t ORIGINAL_CONTAINERS < <(docker ps -q)
if ((${#ORIGINAL_CONTAINERS[@]})); then
    docker inspect --format '{{.Id}} {{.Name}} {{.State.StartedAt}} {{.RestartCount}}' \
        "${ORIGINAL_CONTAINERS[@]}" > "$ACCEPTANCE_DIR/containers-before.txt"
fi
```

Успех: все файлы доступны, исходные SHA-256 сохранены, модель уже установлена,
зафиксированы CPU/OS/Docker и состояние существующих контейнеров. При отсутствии
`vmstat` или другого инструмента не объявляйте соответствующее измерение
выполненным; подготовка инструментов — отдельное действие оператора.

## 2. Однократная сборка отдельного image

Dockerfile использует `python:3.12-slim`, устанавливает закреплённые
`app/requirements.txt` внутри image, копирует `app/` и имеет `WORKDIR /app`.
Сборка может обращаться к registries/package indexes; она выполняется **до**
offline runtime. Подготовьте base image заранее, если его ещё нет локально.
Ниже создаётся отдельный tag для приёмки; действующие контейнеры не заменяются.

```bash
IMAGE=chago-lexical-acceptance:manual
if ! docker image inspect python:3.12-slim >/dev/null 2>&1; then
    docker pull python:3.12-slim
fi
docker build --pull=false --tag "$IMAGE" "$PROJECT/app" \
    > "$ACCEPTANCE_DIR/image-build.log" 2>&1
IMAGE_ID=$(docker image inspect --format '{{.Id}}' "$IMAGE")
printf '%s\n' "$IMAGE_ID" > "$ACCEPTANCE_DIR/image-id.txt"
docker image inspect "$IMAGE_ID" > "$ACCEPTANCE_DIR/image-inspect.json"
```

Для следующего запуска вместо повторной сборки:

```bash
# Укажите файл image-id.txt предыдущего успешного provisioning.
# IMAGE_ID=$(cat /полный/путь/к/предыдущему/image-id.txt)
docker image inspect "$IMAGE_ID" >/dev/null
```

Создайте общий runner. Он не подключён к Compose networks, не публикует порты,
монтирует inputs/assets read-only, а пишет только в каталог приёмки. Ограничение
четырьмя CPU/threads уменьшает конкуренцию с действующими сервисами; эти значения
нужно сохранить в отчёте. Системный Python хоста не используется.

```bash
offline_run() {
    local stdin_flags=()
    if [[ "${1:-}" == python && "${2:-}" == - ]]; then
        stdin_flags=(-i)
    fi
    docker run --rm "${stdin_flags[@]}" --network none --cpus=4 --read-only \
        --tmpfs /tmp:rw,nosuid,nodev,size=256m \
        --env PYTHONUTF8=1 --env PYTHONDONTWRITEBYTECODE=1 \
        --env HF_HUB_OFFLINE=1 --env TRANSFORMERS_OFFLINE=1 \
        --env HF_HOME=/tmp/huggingface \
        --env XDG_CACHE_HOME=/tmp/cache --env TORCH_HOME=/tmp/torch \
        --env EMBEDDING_MODEL_PATH="/data/models/$MODEL_REVISION" \
        --env EMBEDDING_BATCH_SIZE=16 --env EMBEDDING_CPU_THREADS=4 \
        --volume "$DATA:/data:ro" --volume "$FROZEN:/eval:ro" \
        --volume "$ACCEPTANCE_DIR:/acceptance:rw" \
        "$IMAGE_ID" "$@"
}
offline_run python -m pip check > "$ACCEPTANCE_DIR/pip-check.txt"
offline_run python -m app.lexical_storage build --help > "$ACCEPTANCE_DIR/build-help.txt"
offline_run python -m app.lexical_retrieval query --help > "$ACCEPTANCE_DIR/lexical-help.txt"
offline_run python -m app.hybrid_retrieval query --help > "$ACCEPTANCE_DIR/hybrid-help.txt"
offline_run python -m app.hybrid_retrieval evaluate --help > "$ACCEPTANCE_DIR/evaluate-help.txt"
```

Успех: image собран, `pip check` проходит, CLI содержит аргументы следующих
команд. Runtime выполняется по immutable image ID с `--network none`.

## 3. SQLite FTS5, CPU E5 и offline runtime

```bash
offline_run python - <<'PY' > "$ACCEPTANCE_DIR/runtime-identity.json"
import json
import platform
import sqlite3
from importlib.metadata import version
from app.config import load_embedding_settings
from app.embeddings import verify_assets
import torch

db = sqlite3.connect(':memory:')
try:
    db.execute("CREATE VIRTUAL TABLE probe USING fts5(text, tokenize='unicode61')")
    db.execute("INSERT INTO probe VALUES ('ПРОВЕРКА FTS5')")
    assert db.execute("SELECT count(*) FROM probe WHERE probe MATCH ?", ('"проверка"',)).fetchone()[0] == 1
    db.execute("INSERT INTO probe(probe) VALUES ('integrity-check')")
    options = sorted(row[0] for row in db.execute('PRAGMA compile_options'))
finally:
    db.close()
assert torch.version.cuda is None
assert not torch.cuda.is_available()
identity = verify_assets(load_embedding_settings())
print(json.dumps({'python': platform.python_version(), 'platform': platform.platform(),
                  'sqlite_version': sqlite3.sqlite_version, 'compile_options': options,
                  'fts5_unicode61': True, 'cpu_only': True, 'model_identity': identity,
                  'runtime': {n: version(n) for n in ('numpy','torch','sentence-transformers','transformers','tokenizers')}}, indent=2))
PY
```

Успех: FTS5 unicode61 реально ищет русский текст и проходит integrity-check;
восемь model assets проверены по manifest; torch CPU-only. Ни downloads, ни
external inference в runtime невозможны из-за отсутствия сети.

Создайте измеритель **Python-процесса внутри контейнера**. Peak RSS команды
`time docker run` на хосте относится к Docker client и не заменяет эти метрики.
Для comparison используйте также per-mode peaks из самого evaluation report:
они измеряются в отдельных worker processes.

```bash
cat > "$ACCEPTANCE_DIR/runtime_measure.py" <<'PY'
import json
from pathlib import Path
import resource
import runpy
import sys
from time import perf_counter

sys.path.insert(0, '/app')
metrics_path, module = Path(sys.argv[1]), sys.argv[2]
sys.argv = [module, *sys.argv[3:]]
if module == 'app.lexical_storage':
    from app.embeddings import LocalEncoder
    def forbidden(*args, **kwargs):
        raise AssertionError('build attempted inference')
    LocalEncoder.encode_passages = forbidden
    LocalEncoder.encode_query = forbidden
timer = perf_counter()
code = 0
try:
    runpy.run_module(module, run_name='__main__')
except SystemExit as error:
    code = error.code if isinstance(error.code, int) else (0 if error.code is None else 1)
except BaseException:
    code = 1
    raise
finally:
    metrics_path.write_text(json.dumps({'module': module, 'exit_code': code,
        'elapsed_seconds': perf_counter()-timer,
        'peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        'method': 'Linux process ru_maxrss; monotonic wall time; container startup excluded'}, indent=2)+'\n')
raise SystemExit(code)
PY
```

## 4. Wiki.js baseline и мониторинг влияния

Сначала 20 обычных HTTP-проб. Затем выполняется одна проба в секунду во время
build/query/evaluation и пишется `vmstat`. Это измерения хоста, отдельно от
контейнеров без сети. Не очищайте page cache. Все PID ниже принадлежат только
наблюдателям, созданным этой Bash-сессией.

```bash
printf 'epoch,http_code,seconds\n' > "$ACCEPTANCE_DIR/wiki-baseline.csv"
for i in $(seq 1 20); do
    result=$(curl --silent --show-error --max-time 10 --output /dev/null \
        --write-out '%{http_code},%{time_total}' "$WIKI_URL") || result='000,10'
    printf '%s,%s\n' "$(date +%s)" "$result" >> "$ACCEPTANCE_DIR/wiki-baseline.csv"
    sleep 1
done
printf 'epoch,http_code,seconds\n' > "$ACCEPTANCE_DIR/wiki-during.csv"
(
    while [[ ! -e "$ACCEPTANCE_DIR/monitor.stop" ]]; do
        result=$(curl --silent --show-error --max-time 10 --output /dev/null \
            --write-out '%{http_code},%{time_total}' "$WIKI_URL") || result='000,10'
        printf '%s,%s\n' "$(date +%s)" "$result" >> "$ACCEPTANCE_DIR/wiki-during.csv"
        sleep 1
    done
) &
WIKI_SAMPLER_PID=$!
vmstat -w 1 > "$ACCEPTANCE_DIR/vmstat-during.txt" &
VMSTAT_PID=$!
stop_monitors() {
    touch "$ACCEPTANCE_DIR/monitor.stop"
    kill "$VMSTAT_PID" 2>/dev/null || true
    wait "$WIKI_SAMPLER_PID" 2>/dev/null || true
    wait "$VMSTAT_PID" 2>/dev/null || true
}
trap stop_monitors EXIT
```

## 5. Build из прежних semantic snapshots

Inputs остаются read-only. Outputs — новые полные snapshots в каталоге
приёмки. Model path здесь нужен только для защиты paths; wrapper запрещает
embedding inference во время build. Повторный build использует тот же input и
заменяет только output в каталоге приёмки.

```bash
offline_run python /acceptance/runtime_measure.py /acceptance/build-live-metrics.json \
    app.lexical_storage build --input /data/semantic-live.db \
    --output /acceptance/hybrid-live.db \
    > "$ACCEPTANCE_DIR/build-live.json" 2> "$ACCEPTANCE_DIR/build-live.err"
offline_run python /acceptance/runtime_measure.py /acceptance/build-synthetic-metrics.json \
    app.lexical_storage build --input /data/semantic-synthetic.db \
    --output /acceptance/hybrid-synthetic.db \
    > "$ACCEPTANCE_DIR/build-synthetic.json" 2> "$ACCEPTANCE_DIR/build-synthetic.err"
sha256sum "$ACCEPTANCE_DIR/hybrid-live.db" "$ACCEPTANCE_DIR/hybrid-synthetic.db" \
    > "$ACCEPTANCE_DIR/outputs-first-build.sha256"
offline_run python /acceptance/runtime_measure.py /acceptance/rebuild-live-metrics.json \
    app.lexical_storage build --input /data/semantic-live.db \
    --output /acceptance/hybrid-live.db \
    > "$ACCEPTANCE_DIR/rebuild-live.json" 2> "$ACCEPTANCE_DIR/rebuild-live.err"
sha256sum -c "$ACCEPTANCE_DIR/inputs-before.sha256" > "$ACCEPTANCE_DIR/inputs-after-build.txt"
```

Успех: exit 0; live 24 documents/910 chunks, synthetic 1/1 для существующего
frozen набора. Counts должны соответствовать inputs. Повторный build не
выполняет inference; readers проверяют новый snapshot после закрытия writer.
Не требуйте равенства SHA-256 всего нового DB между разными SQLite builds:
lossless контракт проверяется по base contents, metadata и raw vector bytes.

## 6. Reopen, raw embedding bytes, provenance и lexical isolation

```bash
offline_run python - <<'PY' > "$ACCEPTANCE_DIR/lossless-check.json"
import hashlib
import json
from pathlib import Path
import sqlite3
from app.index_storage import StorageReader
from app.semantic_storage import SemanticReader
from app.lexical_storage import LexicalReader

def raw_semantic(path):
    db = sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)
    try:
        return db.execute('SELECT chunk_id,vector FROM chunk_embeddings ORDER BY chunk_id').fetchall(), db.execute('SELECT metadata FROM embedding_metadata').fetchall()
    finally:
        db.close()

report = {}
for name in ('live','synthetic'):
    original, extended = Path('/data/semantic-'+name+'.db'), Path('/acceptance/hybrid-'+name+'.db')
    with StorageReader(original) as base, LexicalReader(extended) as lexical:
        assert base.snapshot == lexical.snapshot
        old, new = SemanticReader(original), SemanticReader(extended)
        assert old.snapshot == new.snapshot == lexical.snapshot
        assert old.metadata == new.metadata
        vectors, metadata = raw_semantic(original)
        assert (vectors,metadata) == raw_semantic(extended)
        h = hashlib.sha256()
        for chunk_id, blob in vectors:
            h.update(chunk_id.encode()); h.update(blob)
        for chunk in lexical.chunks:
            for start,end in chunk.source_ranges:
                assert 0 <= start < end <= len(chunk.document.markdown)
            assert all(segment['kind'] in ('source','generated') for segment in chunk.segments)
        report[name] = {'documents':len(base.documents), 'chunks':len(base.chunks),
            'base_and_provenance_equal':True, 'semantic_metadata_equal':True,
            'raw_vectors_equal':True, 'raw_vectors_sha256':h.hexdigest(),
            'lexical_identity':lexical.metadata, 'reopen_valid':True}
print(json.dumps(report,indent=2))
PY

offline_run python - <<'PY' > "$ACCEPTANCE_DIR/lexical-no-heavy-imports.json"
import json
from pathlib import Path
import sys
for name in ('numpy','torch','sentence_transformers','transformers','tokenizers','app.embeddings'):
    sys.modules[name] = None
from app.lexical_retrieval import LexicalIndex
with LexicalIndex(Path('/acceptance/hybrid-live.db')) as index:
    results = index.search('route-plan',10)
    for result in results:
        for match in result.literal_matches:
            assert result.chunk.document.markdown[match.start:match.end] == match.literal
    print(json.dumps({'query_succeeded':True,'results':len(results),'heavy_imports_blocked':True,
                      'literal_source_slices_equal':True}))
PY
```

Успех: base documents/chunks/IDs/segments/source ranges/search_text/structure
равны исходному snapshot; semantic metadata и **каждый BLOB** равны. LexicalReader
успешно проверяет content и postings, используя backup в памяти. Lexical query
работает с blocked imports, original literal ranges дают дословные slices.

## 7. Query и два three-mode evaluation запуска

Configuration `10/1/60/6` выбрана на development tuning и сохранена **до** нового
holdout. Это explicit overrides для данного эксперимента; defaults публичного
API остаются `10/10/60/6`. Серверный запуск не подбирает другие настройки.

```bash
cat > "$ACCEPTANCE_DIR/selected-settings.json" <<'JSON'
{"semantic_candidates":10,"lexical_candidates":1,"rrf_constant":60,"top_k":6}
JSON
sha256sum "$ACCEPTANCE_DIR/selected-settings.json" > "$ACCEPTANCE_DIR/settings-before.sha256"

offline_run python /acceptance/runtime_measure.py /acceptance/lexical-query-metrics.json \
    app.lexical_retrieval query --index /acceptance/hybrid-live.db \
    --question 'Как настроить route-plan?' --top-k 10 \
    > "$ACCEPTANCE_DIR/lexical-query.json" 2> "$ACCEPTANCE_DIR/lexical-query.err"
offline_run python /acceptance/runtime_measure.py /acceptance/hybrid-query-metrics.json \
    app.hybrid_retrieval query --index /acceptance/hybrid-live.db \
    --question 'Как настроить сервер?' --semantic-candidates 10 --lexical-candidates 1 \
    --rrf-constant 60 --top-k 6 \
    > "$ACCEPTANCE_DIR/hybrid-query.json" 2> "$ACCEPTANCE_DIR/hybrid-query.err"
offline_run python /acceptance/runtime_measure.py /acceptance/semantic-query-metrics.json \
    app.retrieval query --index /data/semantic-live.db --question 'Как настроить сервер?' \
    > "$ACCEPTANCE_DIR/semantic-query.json" 2> "$ACCEPTANCE_DIR/semantic-query.err"

sha256sum "$ACCEPTANCE_DIR/hybrid-live.db" "$ACCEPTANCE_DIR/hybrid-synthetic.db" \
    > "$ACCEPTANCE_DIR/outputs-before-query.sha256"
for run in 1 2; do
    offline_run python /acceptance/runtime_measure.py "/acceptance/evaluate-$run-metrics.json" \
        app.hybrid_retrieval evaluate \
        --questions /eval/questions.yaml --manifest /eval/manifest.json \
        --snapshot /data/eval/1/wiki-documents.json --index /acceptance/hybrid-live.db \
        --fixtures /eval/fixtures/wiki-documents.json \
        --synthetic-index /acceptance/hybrid-synthetic.db \
        --semantic-candidates 10 --lexical-candidates 1 --rrf-constant 60 --top-k 6 \
        --split all \
        > "$ACCEPTANCE_DIR/evaluate-$run.json" 2> "$ACCEPTANCE_DIR/evaluate-$run.err"
done
sha256sum -c "$ACCEPTANCE_DIR/outputs-before-query.sha256" > "$ACCEPTANCE_DIR/outputs-after-query.txt"
sha256sum -c "$ACCEPTANCE_DIR/settings-before.sha256" > "$ACCEPTANCE_DIR/settings-after.txt"
```

`--model-path` также поддерживается build, hybrid query/evaluate и semantic
query; здесь используется `EMBEDDING_MODEL_PATH` runner. Lexical query не имеет
аргумента model path. Evaluation всегда запрашивает пять результатов, несмотря
на default final top-k=6, и показывает tuning/holdout/follow-up отдельно.

Проверка JSON, стабильности и измерений:

```bash
offline_run python - <<'PY' > "$ACCEPTANCE_DIR/evaluation-summary.json"
import json
from pathlib import Path
import statistics
from app.retrieval_comparison import stable_results

root = Path('/acceptance')
first, second = [json.loads((root/f'evaluate-{n}.json').read_text()) for n in (1,2)]
for key in ('fingerprints','effective_settings','environment','live_single_question','transitions','quality_acceptance'):
    assert first[key] == second[key]
assert first['effective_settings'] == json.loads((root/'selected-settings.json').read_text())
assert len(json.loads((root/'semantic-query.json').read_text())) == 10
hybrid_query = json.loads((root/'hybrid-query.json').read_text())
assert len(hybrid_query) == 6
assert all('rrf_score' in r and 'cosine_score' in r and 'bm25_score' in r for r in hybrid_query)
assert all('source_ranges' in r and 'segments' in r and 'structure' in r for r in hybrid_query)
measurements = {}
for mode in ('semantic','lexical','hybrid'):
    a,b = first['modes'][mode],second['modes'][mode]
    assert stable_results(a) == stable_results(b)
    assert a['measurement']['process_isolation'] and a['measurement']['repeated_rankings_equal']
    assert a['peak_memory_bytes'] > 0
    measurements[mode] = {'initialization_seconds':a['initialization_seconds'],
        'first_query_seconds':a['cases'][0]['duration_seconds'],
        'warm_mean_seconds':statistics.mean(c['warm_duration_seconds'] for c in a['cases']),
        'peak_memory_bytes':a['peak_memory_bytes'], 'groups':a['groups']}
assert first['modes']['lexical']['heavy_imports_loaded'] == []
print(json.dumps({'repeat_rank_scores_counts_equal':True,'live_single_question':first['live_single_question'],
    'quality_acceptance':first['quality_acceptance'],'transitions':first['transitions'],
    'holdout_exposure':first['holdout_exposure'],'measurements':measurements},indent=2))
PY
```

Успех: query/evaluate exit 0; provenance и score kinds присутствуют; pure
semantic default выдаёт 10, hybrid — 6; inputs/outputs/settings неизменны.
Повторные ranks/scores/counts совпадают **на этом сервере**. Timings и peak RSS
могут отличаться. Lexical worker не наследует память E5. Различия SQLite/BLAS
между development Windows и Linux фиксируются отдельно, без требования
побайтового равенства scores на разных средах.

## 8. Controlled failures и сохранность прежнего output

Сначала проверьте штатную ошибку отсутствующих model assets. Ожидаются exit 1
и `hybrid: embedding_assets`; source/query text и backend exceptions не должны
появляться в диагностике. Затем real build проходит до injected failures
записи/validation/publication; прежний output остаётся неизменным.

```bash
if offline_run python /acceptance/runtime_measure.py /acceptance/missing-assets-metrics.json \
    app.hybrid_retrieval query --index /acceptance/hybrid-live.db \
    --question 'Как настроить сервер?' --model-path /missing-acceptance-assets \
    > "$ACCEPTANCE_DIR/missing-assets.out" 2> "$ACCEPTANCE_DIR/missing-assets.err"; then
    echo 'ОШИБКА: ожидался отказ при missing assets' >&2
    exit 1
else
    rc=$?
    test "$rc" -eq 1
fi
grep -Fx 'hybrid: embedding_assets' "$ACCEPTANCE_DIR/missing-assets.err"

offline_run python - <<'PY' > "$ACCEPTANCE_DIR/failure-preservation.json"
import hashlib
import json
from pathlib import Path
from unittest.mock import patch
from app.lexical_storage import LexicalStorageError, build

source, target = Path('/data/semantic-live.db'),Path('/acceptance/hybrid-live.db')
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
before = digest(source),digest(target)
results = []
for stage in ('_write_extension','validate_lexical','os.replace'):
    with patch('app.lexical_storage.'+stage,side_effect=OSError('acceptance fault injection')):
        try:
            build(source,target)
        except LexicalStorageError as error:
            assert str(error) == 'lexical_build'
            category = str(error)
        else:
            raise AssertionError('failure unexpectedly published')
    assert before == (digest(source),digest(target))
    assert not list(target.parent.glob('.hybrid-live.db.*.tmp'))
    results.append({'stage':stage,'category':category,'input_and_previous_output_preserved':True})
try:
    build(source,source)
except LexicalStorageError as error:
    assert str(error) == 'lexical_path'
else:
    raise AssertionError('input/output alias accepted')
assert before == (digest(source),digest(target))
print(json.dumps({'failures':results,'input_output_alias_rejected':True},indent=2))
PY
sha256sum -c "$ACCEPTANCE_DIR/outputs-before-query.sha256" > "$ACCEPTANCE_DIR/outputs-after-failures.txt"
```

Успех: missing assets дают контролируемую ошибку; три injected failures
сохраняют source и прежний output, temporary artifacts убраны, input/output
alias отклонён. Runtime root filesystem и inputs остаются read-only.

## 9. Завершение наблюдений, SHA-256 и пакет результатов

```bash
stop_monitors
trap - EXIT
free -b > "$ACCEPTANCE_DIR/memory-after.txt"
docker compose ps > "$ACCEPTANCE_DIR/compose-after.txt"
if ((${#ORIGINAL_CONTAINERS[@]})); then
    docker inspect --format '{{.Id}} {{.Name}} {{.State.StartedAt}} {{.RestartCount}}' \
        "${ORIGINAL_CONTAINERS[@]}" > "$ACCEPTANCE_DIR/containers-after.txt"
    diff -u "$ACCEPTANCE_DIR/containers-before.txt" "$ACCEPTANCE_DIR/containers-after.txt" \
        > "$ACCEPTANCE_DIR/container-lifecycle.diff"
fi
sha256sum -c "$ACCEPTANCE_DIR/inputs-before.sha256" > "$ACCEPTANCE_DIR/inputs-after-all.txt"
sha256sum -c "$ACCEPTANCE_DIR/model-before.sha256" > "$ACCEPTANCE_DIR/model-after-all.txt"
git status --short > "$ACCEPTANCE_DIR/git-status-after.txt"

offline_run python - <<'PY' > "$ACCEPTANCE_DIR/wiki-impact.json"
import csv
import json
from pathlib import Path
import statistics
root = Path('/acceptance')
summary = {}
for name in ('baseline','during'):
    with (root/f'wiki-{name}.csv').open() as handle:
        rows = list(csv.DictReader(handle))
    assert rows
    values = sorted(float(row['seconds']) for row in rows)
    summary[name] = {'requests':len(rows),'non_2xx':sum(not row['http_code'].startswith('2') for row in rows),
        'mean_seconds':statistics.mean(values),'max_seconds':max(values),
        'p95_seconds':values[max(0,(95*len(values)+99)//100-1)]}
summary['method'] = '20 host HTTP probes before workload; approximately one per second during; 10-second timeout'
print(json.dumps(summary,indent=2))
PY

find "$ACCEPTANCE_DIR" -maxdepth 1 -type f \
    ! -name '*.db' ! -name 'results.sha256' -print0 \
    | sort -z | xargs -0 sha256sum > "$ACCEPTANCE_DIR/results.sha256"
tar --exclude='*.db' -czf "${ACCEPTANCE_DIR}-reports.tar.gz" \
    -C "$ACCEPTANCE_DIR" .
printf 'Отчёты: %s\nАрхив: %s-reports.tar.gz\n' "$ACCEPTANCE_DIR" "$ACCEPTANCE_DIR"
```

Прочитайте `wiki-impact.json`, `vmstat-during.txt`, `memory-before.txt` и
`memory-after.txt`. Отдельно укажите swap `si/so`, HTTP errors, изменение
mean/p95/max и наблюдавшиеся задержки интерфейса Wiki.js. Первую строку данных
`vmstat` не трактуйте как измерение интервала: она усредняет состояние с boot.
Если появились ошибки, OOM или заметное влияние, зафиксируйте их; критерий
«без заметного влияния» не имеет заранее установленного числового SLA и не
должен подменяться выдуманным порогом. Существующие container IDs/StartedAt/
RestartCount должны остаться прежними.

Для документирования передайте summaries (`runtime-identity.json`,
`lossless-check.json`, `evaluation-summary.json`, `failure-preservation.json`,
`wiki-impact.json`), два полных evaluation reports, build/query metrics, image
ID, SHA-256 checks и сведения CPU/OS/памяти/swap. Архив сохраняет отчёты и логи
без model assets или DB snapshots; сами новые DB остаются в отдельном каталоге.

## Ожидаемые критерии успешности

- Offline build/query/evaluate реально прошли в новом image с `--network none`.
- FTS5/SQLite identity записана; content/postings validation и reopen проходят.
- SHA-256 всех frozen inputs, старого baseline и model assets совпадают до/после;
  base snapshot/provenance, semantic metadata и raw embedding BLOBs сохранены.
- Lexical query/worker работает без тяжёлых imports; hybrid ветки используют
  один snapshot; pure semantic контракт сохраняется.
- Два фиксированных evaluation запуска дают одинаковые ranks/scores/counts;
  есть отдельные split/follow-up/synthetic metrics, cold/warm latency и per-mode
  peak RSS. Ни один шестой chunk не включён в Hit@5.
- Controlled failures сохраняют прежний output и имеют безопасные категории.
- Wiki.js и остальные существующие контейнеры не перезапускались; измеренное
  влияние и swap описаны по фактическим наблюдениям.

Это подтверждает техническую проверку задачи 5.4 после рассмотрения реального
отчёта. Задача 5.5 — отдельный quality acceptance: hybrid live single-question
Hit@5 >=90%. Development результат configuration `10/1/60/6` — 6/12 (50%),
tuning 6/9, holdout 0/3, follow-up 0/1 в каждом split. Miss IDs: q02, q03, q04,
q07, q08, q18. Серверный технический успех не закрывает этот недостигнутый
quality criterion и не разрешает менять frozen expectations или tuning по
новым holdout misses.
