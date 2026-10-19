#!/usr/bin/env bash
# Invoke from staged payload root, with IMAGE pinned to an immutable image ID.
set -Eeuo pipefail
umask 077
test "$#" = 1
repeat=$1
test "$repeat" = 1 || test "$repeat" = 2
: "${IMAGE:?export IMAGE=sha256:... first}"
: "${RUN_ID:?set RUN_ID first}"
case "$RUN_ID" in *[!a-z0-9-]*|'') exit 1;; esac
ROOT=$(pwd -P)
OUT="$ROOT/data/retrieval-quality-improvement/reranker-v2/manual-$RUN_ID"
test -d "$OUT"
test -f "$OUT/preflight.json"
test ! -e "$OUT/summary-$repeat.json"
if test "$repeat" = 2; then
  test -f "$OUT/summary-1.json"
  python3 -c 'import json,sys; assert not json.load(open(sys.argv[1]))["failures"]' "$OUT/summary-1.json"
fi
run_python() {
  docker run --rm --network none --read-only --cpus 4 --memory 5g --memory-swap 5g \
    --tmpfs /tmp:rw,nosuid,nodev,size=256m \
    --user "$(id -u):$(id -g)" \
    -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e HF_HUB_OFFLINE=1 \
    -e TRANSFORMERS_OFFLINE=1 -e HF_HUB_DISABLE_TELEMETRY=1 -e TOKENIZERS_PARALLELISM=false \
    -e OMP_NUM_THREADS=4 -e MKL_NUM_THREADS=4 -e OPENBLAS_NUM_THREADS=4 \
    --mount "type=bind,src=$ROOT,dst=/work,readonly" \
    --mount "type=bind,src=$OUT,dst=/out" -w /work "$IMAGE" python "$@"
}
for arm in legacy control reranker; do
  name="rq57-$RUN_ID-$arm-$repeat"
  test ! -e "$OUT/$arm-$repeat.json"
  run_python docs/retrieval-quality-5-7-tools.py check > "$OUT/$arm-$repeat.before.json"
  docker create --name "$name" --network none --read-only --cpus 4 --memory 5g --memory-swap 5g \
    --tmpfs /tmp:rw,nosuid,nodev,size=256m \
    --user "$(id -u):$(id -g)" \
    -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e HF_HUB_OFFLINE=1 \
    -e TRANSFORMERS_OFFLINE=1 -e HF_HUB_DISABLE_TELEMETRY=1 -e TOKENIZERS_PARALLELISM=false \
    -e OMP_NUM_THREADS=4 -e MKL_NUM_THREADS=4 -e OPENBLAS_NUM_THREADS=4 \
    --mount "type=bind,src=$ROOT,dst=/work,readonly" \
    --mount "type=bind,src=$OUT,dst=/out" -w /work "$IMAGE" \
    python docs/retrieval-quality-5-7-tools.py worker --arm "$arm" --repeat "$repeat" \
    --output "/out/$arm-$repeat.json" > "$OUT/$arm-$repeat.container-id"
  docker inspect "$name" > "$OUT/$arm-$repeat.inspect-before.json"
  free -b > "$OUT/$arm-$repeat.free-before.txt"
  cat /proc/meminfo > "$OUT/$arm-$repeat.meminfo-before.txt"
  vmstat -w 1 > "$OUT/$arm-$repeat.vmstat.txt" &
  monitor=$!
  trap 'kill "$monitor" 2>/dev/null || true' EXIT
  set +e
  docker start -a "$name" > "$OUT/$arm-$repeat.stdout.txt" 2> "$OUT/$arm-$repeat.stderr.txt"
  attach_status=$?
  set -e
  kill "$monitor" 2>/dev/null || true
  wait "$monitor" 2>/dev/null || true
  trap - EXIT
  docker inspect "$name" > "$OUT/$arm-$repeat.inspect-after.json"
  free -b > "$OUT/$arm-$repeat.free-after.txt"
  cat /proc/meminfo > "$OUT/$arm-$repeat.meminfo-after.txt"
  # Leave stopped measurement containers for review. Never touch service containers.
  test "$attach_status" = 0
  python3 - "$OUT/$arm-$repeat.inspect-after.json" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))[0]
assert r['State']['ExitCode'] == 0 and not r['State']['OOMKilled'], r['State']
c = r['HostConfig']
assert c['NetworkMode'] == 'none' and c['ReadonlyRootfs']
assert c['NanoCpus'] == 4000000000 and c['Memory'] == c['MemorySwap'] == 5368709120
PY
  run_python docs/retrieval-quality-5-7-tools.py inspect --output "/out/$arm-$repeat.json" \
    > "$OUT/$arm-$repeat.metrics.json"
  run_python docs/retrieval-quality-5-7-tools.py check > "$OUT/$arm-$repeat.after.json"
done
run_python docs/retrieval-quality-5-7-tools.py summarize --directory /out --repeat "$repeat" \
  --output "/out/summary-$repeat.json" > "$OUT/summary-$repeat.stdout.txt"
cat "$OUT/summary-$repeat.stdout.txt"
