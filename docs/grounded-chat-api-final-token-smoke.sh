#!/usr/bin/env bash
# Gate 7.1: inspect existing runtime, start only a temporary read-only app client.
set -euo pipefail
llm_id=$(docker compose ps -q llm)
test -n "$llm_id"
image_id=$(docker inspect --format '{{.Image}}' "$llm_id")
digests=$(docker image inspect --format '{{json .RepoDigests}}' "$image_id")
model_path=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/models/model.gguf"}}{{.Source}}{{end}}{{end}}' "$llm_id")
test -f "$model_path"
model_hash=$(sha256sum -- "$model_path")
model_hash=${model_hash%% *}
docker compose run --rm --no-deps --no-build --pull never -T \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -e ACCEPTANCE_IMAGE_DIGESTS="$digests" -e ACCEPTANCE_MODEL_SHA256="$model_hash" \
  -v "$PWD/app:/workspace/app:ro" -v "$PWD/data:/data:ro" \
  -w /workspace/app app python -m app.chat_token_check
