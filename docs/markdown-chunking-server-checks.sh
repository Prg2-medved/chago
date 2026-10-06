#!/usr/bin/env bash
# Run from ~/chago-llm/chago after transferring the current implementation.
# Writes only isolated acceptance artifacts and preinstalled tokenizer assets.
set -euo pipefail

revision=614241f622f53c4eeff9890bdc4f31cfecc418b3
test -f compose.yaml
test -f app/app/chunking.py
test -f app/app/chunk_tokenizer.py
grep -qx 'tokenizers==0.22.2' app/requirements.txt
test -f data/eval/1/wiki-documents.json
test -f eval/fixtures/wiki-documents.json
docker version --format '{{.Server.Version}}'
docker compose version
docker network inspect wiki_default >/dev/null

mkdir -p data/tokenizers
run_dir=$(mktemp -d "$PWD/data/chunking-compose-check.XXXXXX")
run_name=$(basename "$run_dir")
project="chago-chunking-check-$(date +%s)-$$"
health_name="${project}-health"
compose=(docker compose --project-name "$project" --file compose.yaml)
cleanup() {
    docker rm -f "$health_name" >/dev/null 2>&1 || true
    "${compose[@]}" down --remove-orphans >"$run_dir/cleanup.log" 2>&1 || true
}
trap cleanup EXIT
printf 'Acceptance artifacts: %s\n' "$run_dir"

sha256sum README.md ROADMAP.md compose.yaml \
    data/eval/1/wiki-documents.json eval/fixtures/wiki-documents.json \
    eval/manifest.json eval/questions.yaml >"$run_dir/inputs.before.sha256"
cp eval/fixtures/wiki-documents.json "$run_dir/input.json"
cmp eval/fixtures/wiki-documents.json "$run_dir/input.json"
mkdir "$run_dir/empty"

# Installation only: immutable HTTPS URLs, exactly three tokenizer JSON files.
# Existing files are never overwritten; wrong existing hashes abort the check.
assets="$PWD/data/tokenizers/$revision"
mkdir -p "$assets"
for asset in tokenizer.json tokenizer_config.json special_tokens_map.json; do
    if [[ ! -f "$assets/$asset" ]]; then
        curl --fail --location --proto '=https' --proto-redir '=https' \
            "https://huggingface.co/intfloat/multilingual-e5-small/resolve/$revision/$asset" \
            --output "$assets/$asset"
    fi
done
(
    cd "$assets"
    sha256sum --check <<'HASHES'
0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39  tokenizer.json
a1d6bc8734a6f635dc158508bef000f8e2e5a759c7d92f984b2c86e5ff53425b  tokenizer_config.json
d05497f1da52c5e09554c0cd874037a083e1dc1b9cfd48034d1c717f1afc07a7  special_tokens_map.json
HASHES
)
sha256sum "$assets"/*.json >"$run_dir/assets.before.sha256"

"${compose[@]}" build app
image="${project}-app"
docker image inspect "$image" --format '{{.Id}}' >"$run_dir/image-id.txt"

# Real Compose CLI, using ./data:/data. No Wiki.js/LLM services are started.
for attempt in 1 2; do
    "${compose[@]}" run --rm --no-deps --user "$(id -u):$(id -g)" app python -m app.chunking \
        --input "/data/$run_name/input.json" \
        --output "/data/$run_name/chunks-$attempt.json" \
        --tokenizer-path "/data/tokenizers/$revision" \
        | tee "$run_dir/cli-$attempt.log"
done
cmp "$run_dir/chunks-1.json" "$run_dir/chunks-2.json"

# Verify identity, counts, budgets, original source and byte fingerprint offline.
docker run --rm --network none \
    --mount "type=bind,src=$run_dir,dst=/checks,readonly" \
    --mount "type=bind,src=$assets,dst=/tokenizer,readonly" \
    "$image" python -c '
import hashlib, json
from pathlib import Path
from app.chunk_tokenizer import ASSET_HASHES, LocalE5, MODEL_ID, PACKAGE_VERSION, REVISION, passage
raw = Path("/checks/chunks-1.json").read_bytes()
result = json.loads(raw)
original = json.loads(Path("/checks/input.json").read_bytes())
assert result["documents"] == original["documents"]
assert result["source"] == original["source"]
assert len(result["documents"]) == len(result["chunks"]) == 1
identity = result["tokenizer"]
assert identity["model_id"] == MODEL_ID
assert identity["revision"] == REVISION
assert identity["assets_sha256"] == ASSET_HASHES
assert identity["package_version"] == PACKAGE_VERSION
assert identity["assets_fingerprint"] == "573b6457b17946a70015f085b8b467715631438ac1a72ba8c4e2784813848850"
tokenizer = LocalE5(Path("/tokenizer"))
assert identity == tokenizer.identity
assert hashlib.sha256(raw).hexdigest() == "1423dfff20f580bf553ab55b0c62e98196aed083923643dbfead241482ece8d3"
chunk = result["chunks"][0]
assert chunk["body_tokens"] == 45 and chunk["input_tokens"] == 67
assert tokenizer.count(chunk["search_text"]) == chunk["body_tokens"]
assert tokenizer.count(passage(chunk["title"], tuple(chunk["heading_path"]), chunk["search_text"]), True) == chunk["input_tokens"]
assert chunk["body_tokens"] <= 450 and chunk["input_tokens"] <= 512
assert chunk["source_url"] == original["documents"][0]["source_url"]
markdown = original["documents"][0]["markdown"]
covered = set()
rendered = []
for segment in chunk["segments"]:
    if segment["kind"] == "source":
        start, end = segment["start"], segment["end"]
        covered.update(range(start, end))
        rendered.append(markdown[start:end])
    else:
        rendered.append(segment["text"])
assert covered == set(range(len(markdown)))
assert "".join(rendered) == chunk["search_text"]
print("PASS: Compose fixture identity, byte equality, source coverage, 45/67 tokens")
' | tee "$run_dir/fixture-verification.log"

# Standard app entrypoint with no tokenizer files and no network access.
# No published host ports and no production container changes.
docker run --detach --name "$health_name" --network none \
    --mount "type=bind,src=$run_dir/empty,dst=/data,readonly" \
    "$image" >"$run_dir/health-container-id.txt"
docker exec "$health_name" python -c '
import json, time, urllib.request
from pathlib import Path
assert not list(Path("/data").iterdir())
for attempt in range(40):
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=1) as response:
            assert response.status == 200
            assert json.load(response) == {"status": "ok"}
        break
    except OSError:
        if attempt == 39:
            raise
        time.sleep(0.25)
print("PASS: app-only startup without tokenizer/Wiki.js/LLM; health 200 status=ok")
' | tee "$run_dir/health-verification.log"
test "$(docker inspect --format '{{.HostConfig.NetworkMode}}' "$health_name")" = none
test "$(docker inspect --format '{{.State.Running}}' "$health_name")" = true

# Missing-assets Compose CLI must fail safely and preserve existing output.
printf 'previous-output\n' >"$run_dir/preserved-output.json"
cp "$run_dir/preserved-output.json" "$run_dir/preserved-output.before"
if "${compose[@]}" run --rm --no-deps --user "$(id -u):$(id -g)" app python -m app.chunking \
    --input "/data/$run_name/input.json" \
    --output "/data/$run_name/preserved-output.json" \
    --tokenizer-path "/data/$run_name/empty" \
    >"$run_dir/missing-assets.stdout" 2>"$run_dir/missing-assets.stderr"; then
    echo 'FAIL: missing-assets CLI unexpectedly succeeded' >&2
    exit 1
else
    status=$?
fi
test "$status" -eq 1
grep -Fx 'chunking: tokenizer_assets' "$run_dir/missing-assets.stderr"
test ! -s "$run_dir/missing-assets.stdout"
cmp "$run_dir/preserved-output.before" "$run_dir/preserved-output.json"
cmp eval/fixtures/wiki-documents.json "$run_dir/input.json"
sha256sum --check "$run_dir/inputs.before.sha256"
sha256sum --check "$run_dir/assets.before.sha256"
printf 'PASS: missing assets exit=1, old output/input/assets unchanged\n' \
    | tee "$run_dir/missing-assets-verification.log"
printf 'PASS: all server checks complete; artifacts=%s\n' "$run_dir" \
    | tee "$run_dir/result.log"
