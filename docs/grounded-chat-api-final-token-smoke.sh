#!/usr/bin/env bash
# Gate 7.1: inspect existing runtime, start only a temporary read-only app client.
set -euo pipefail
llm_id=$(docker compose ps -q llm)
app_id=$(docker compose ps -q app)
test -n "$llm_id" && test -n "$app_id"
app_image_id=$(docker inspect --format '{{.Image}}' "$app_id")
image_id=$(docker inspect --format '{{.Image}}' "$llm_id")
digests=$(docker image inspect --format '{{json .RepoDigests}}' "$image_id")
model_path=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/models/model.gguf"}}{{.Source}}{{end}}{{end}}' "$llm_id")
test -f "$model_path"
model_hash=$(sha256sum -- "$model_path")
model_hash=${model_hash%% *}
# Use the existing image ID directly: no Compose build behavior or run flags.
# Copy only public app settings, never database credentials or other secrets.
env_args=()
while IFS= read -r setting; do
  case "$setting" in
    INDEX_PATH=*|EMBEDDING_MODEL_PATH=*|EMBEDDING_MODEL_ID=*|EMBEDDING_MODEL_REVISION=*|EMBEDDING_BATCH_SIZE=*|EMBEDDING_CPU_THREADS=*|RETRIEVAL_SEMANTIC_CANDIDATES=*|RETRIEVAL_LEXICAL_CANDIDATES=*|RETRIEVAL_RRF_CONSTANT=*|RETRIEVAL_TOP_K=*|LLM_MODEL_NAME=*|LLM_MAX_TOKENS=*|LLM_CONTEXT_SIZE=*|LLM_TIMEOUT_SECONDS=*)
      env_args+=(--env "$setting")
      ;;
  esac
done < <(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$app_id")
docker run --rm --pull=never --read-only --tmpfs /tmp:rw,nosuid,nodev \
  --network "container:$llm_id" \
  --mount "type=bind,src=$PWD/app,dst=/workspace/app,readonly" \
  --mount "type=bind,src=$PWD/data,dst=/data,readonly" \
  --workdir /workspace/app "${env_args[@]}" \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -e LLM_BASE_URL=http://127.0.0.1:8080 \
  -e ACCEPTANCE_IMAGE_DIGESTS="$digests" -e ACCEPTANCE_MODEL_SHA256="$model_hash" \
  "$app_image_id" python -m app.chat_token_check
