#!/usr/bin/env bash
# Gate 7.2: sequential frozen end-to-end and fixed-evidence generation runs.
set -euo pipefail
umask 077
llm_id=$(docker compose ps -q llm)
app_id=$(docker compose ps -q app)
if test -z "$llm_id" || test -z "$app_id"; then
  echo 'Evaluation requires already running app and llm containers.' >&2
  exit 1
fi
app_image_id=$(docker inspect --format '{{.Image}}' "$app_id")
llm_image_id=$(docker inspect --format '{{.Image}}' "$llm_id")
digests=$(docker image inspect --format '{{json .RepoDigests}}' "$llm_image_id")
case "$digests" in
  *'ghcr.io/ggml-org/llama.cpp@sha256:f9115c95639e60abc09d4ea83b26fd4d56c66aa1174594393335a514da00c283'*) ;;
  *) echo 'Evaluation stopped: LLM image identity mismatch.' >&2; exit 1 ;;
esac
model_path=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/models/model.gguf"}}{{.Source}}{{end}}{{end}}' "$llm_id")
test -f "$model_path" || { echo 'Evaluation stopped: GGUF bind mount is unavailable.' >&2; exit 1; }
model_hash=$(sha256sum -- "$model_path")
model_hash=${model_hash%% *}
test "$model_hash" = 2fde00ce69dd4899c70d020845e2638353015bba0fdf161b3eb965f2bca4464e || {
  echo 'Evaluation stopped: GGUF identity mismatch.' >&2
  exit 1
}

snapshot=${FROZEN_SNAPSHOT:-/data/eval/1/wiki-documents.json}
live_index=${FROZEN_LIVE_INDEX:-/data/hybrid-live.db}
synthetic_index=${FROZEN_SYNTHETIC_INDEX:-/data/hybrid-synthetic.db}
for input in "$snapshot" "$live_index" "$synthetic_index"; do
  case "$input" in
    /data/*) test -f "$PWD/data/${input#/data/}" || { echo "Missing frozen input: $input" >&2; exit 1; } ;;
    *) echo 'Frozen inputs must be under the read-only /data mount.' >&2; exit 1 ;;
  esac
done
test -f "$PWD/eval/questions.yaml" && test -f "$PWD/eval/manifest.json"
test -f "$PWD/eval/fixtures/wiki-documents.json"

env_args=()
while IFS= read -r setting; do
  case "$setting" in
    EMBEDDING_MODEL_PATH=*|EMBEDDING_MODEL_ID=*|EMBEDDING_MODEL_REVISION=*|EMBEDDING_BATCH_SIZE=*|EMBEDDING_CPU_THREADS=*|RETRIEVAL_SEMANTIC_CANDIDATES=*|RETRIEVAL_LEXICAL_CANDIDATES=*|RETRIEVAL_RRF_CONSTANT=*|RETRIEVAL_TOP_K=*|LLM_MODEL_NAME=*|LLM_MAX_TOKENS=*|LLM_CONTEXT_SIZE=*|LLM_TIMEOUT_SECONDS=*)
      env_args+=(--env "$setting")
      ;;
  esac
done < <(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$app_id")

report_dir=$(mktemp -d "$PWD/data/grounded-chat-api-eval.XXXXXXXX")
printf '%s\n' "$digests" > "$report_dir/image-digests.json"
printf '%s\n' "$model_hash" > "$report_dir/model.sha256"
printf 'Reports: %s\n' "$report_dir"
trap 'printf "Evaluation stopped. Inspect reports in %s; no automatic retry.\n" "$report_dir" >&2' ERR
for mode in end-to-end generation-only; do
  printf 'Running %s\n' "$mode"
  docker run --rm --pull=never --read-only --tmpfs /tmp:rw,nosuid,nodev \
    --network "container:$llm_id" \
    --mount "type=bind,src=$PWD/app,dst=/workspace/app,readonly" \
    --mount "type=bind,src=$PWD/eval,dst=/workspace/eval,readonly" \
    --mount "type=bind,src=$PWD/data,dst=/data,readonly" \
    --workdir /workspace/app "${env_args[@]}" \
    --env PYTHONDONTWRITEBYTECODE=1 --env LLM_BASE_URL=http://127.0.0.1:8080 \
    "$app_image_id" python -m app.chat_evaluation --mode "$mode" \
    --questions /workspace/eval/questions.yaml --manifest /workspace/eval/manifest.json \
    --snapshot "$snapshot" --fixtures /workspace/eval/fixtures/wiki-documents.json \
    --index "$live_index" --synthetic-index "$synthetic_index" \
    2> "$report_dir/$mode.stderr" | tee "$report_dir/$mode.jsonl"
done
printf 'Generation runs finished; manual review pending. Reports: %s\n' "$report_dir"
