# Cross-encoder offline bundle v2

Task 5.5 continues the existing [v2 commitment](retrieval-quality-protocol-receipt-v2.json);
task 5.4 is not repeated. The committed [experiment protocol](retrieval-quality-experiment-protocol-v2.md)
and all v1 records remain unchanged.

The only authorized source is
`cross-encoder/mmarco-mMiniLMv2-L12-H384-v1@1427fd652930e4ba29e8149678df786c240d8825`.
Local assets belong under `data/models/1427fd652930e4ba29e8149678df786c240d8825/`:
`config.json`, `tokenizer.json`, `tokenizer_config.json`, `special_tokens_map.json`,
`model.safetensors`, and the upstream README saved as `model-card.md`.
Every source URL uses this immutable revision. The model card retains upstream
Apache-2.0 and language metadata. No pickle weights, exports, quantization,
new dependencies or alternative model are used.

The existing `data/` ignore rule covers weights and tokenizer assets. They must
not be force-added to Git. Only hashes, provenance, verification results and
workflow records belong in version control. Transport the complete verified
directory to the offline machine and recheck every file against the receipt.

The bundle verification script is retained locally at
`data/retrieval-quality-improvement/reranker-v2/verify_bundle.py`. From the repository root:

```powershell
.venv/Scripts/python.exe data/retrieval-quality-improvement/reranker-v2/verify_bundle.py
git check-ignore data/models/1427fd652930e4ba29e8149678df786c240d8825/tokenizer.json
git ls-files data/models
```

Verification checks the two preregistered published SHA-256 values, records the
complete six-file manifest and exact installed runtime, checks FP32 safetensors,
then loads the fast tokenizer and CPU model with `local_files_only=True`,
`trust_remote_code=False`, `use_safetensors=True`, eager attention and FP32.
Offline environment flags are set before backend imports. Socket connection
and DNS operations raise during verification; zero attempts are required.
Loading does not perform quality inference. The receipt records the verification
environment and loading duration; this is not target-server resource acceptance.

The owner reports 12 GB free server disk, 8.1 GiB available RAM and `vmstat`
`si=0`, `so=0` on 2026-10-19. These are operator-provided preparation observations,
not measured experiment peaks, latency, container cap or acceptance evidence.

After successful task 5.5, task 5.6 first checks every full tuning candidate pair
with the pinned tokenizer before cross-encoder quality inference. Any overflow
stops the experiment: no truncation, candidate dropping, windows or larger
budgets. Later development and final gates follow the committed protocol.

## Verified results, 2026-10-19

Task 5.5 passed. The six-file bundle occupies **487,679,201 bytes**, including
470,592,698 bytes of weights. Published weights/tokenizer SHA-256 values match.
All model parameters are FP32; the serialized `roberta.embeddings.position_ids`
buffer is correctly I64. The fast tokenizer has four pair special tokens.
Local model/tokenizer loading succeeded with zero network attempts under the
socket/DNS guard. Exact per-file hashes, source URLs, runtime and verification
environment are in the v2 receipt. No assets are tracked in Git.

The tuning live answerable preflight checked nine single questions plus one
separate follow-up: **1,201 pairs**, maximum question length **25/128**, maximum
pair length **469/512**, no overflow. Full identities and per-pair lengths are
in [the preflight report](retrieval-quality-preflight-v2.json). An additional
CLI preflight includes separate tuning synthetic/answerless cases; its full
report remains under `data/retrieval-quality-improvement/reranker-v2/`.
These checks perform E5 candidate retrieval and cross-encoder tokenization,
not cross-encoder quality inference, acceptance or resource screening.

## Explicit application CLI

The new module is only loaded when explicitly invoked. From `app/`, use the
verified E5 and cross-encoder local directories. No snapshot is rebuilt.

```sh
python -m app.reranking query --index ../data/hybrid-live.db --model-path ../data/models/614241f622f53c4eeff9890bdc4f31cfecc418b3 --reranker-path ../data/models/1427fd652930e4ba29e8149678df786c240d8825 --question 'YOUR QUESTION'

python -m app.reranking preflight --index ../data/hybrid-live.db --model-path ../data/models/614241f622f53c4eeff9890bdc4f31cfecc418b3 --reranker-path ../data/models/1427fd652930e4ba29e8149678df786c240d8825 --questions ../eval/questions.yaml --manifest ../eval/manifest.json --snapshot ../data/eval/1/wiki-documents.json --fixtures ../eval/fixtures/wiki-documents.json --synthetic-index ../data/hybrid-synthetic.db --split tuning

python -m app.reranking evaluate --index ../data/hybrid-live.db --model-path ../data/models/614241f622f53c4eeff9890bdc4f31cfecc418b3 --reranker-path ../data/models/1427fd652930e4ba29e8149678df786c240d8825 --questions ../eval/questions.yaml --manifest ../eval/manifest.json --snapshot ../data/eval/1/wiki-documents.json --fixtures ../eval/fixtures/wiki-documents.json --synthetic-index ../data/hybrid-synthetic.db --split tuning
```

Evaluation preflights the complete allowed tuning set before the first model
score. Reports distinguish raw reranker logits from original branch/RRF scores
and retain union/input identities, original ranges and model/policy identity.
RRF defaults remain 10/10/60/6; this explicit experiment fixes 120/1/60/6.
The evaluation CLI currently admits only tuning. Frozen/holdout execution is
reserved for task 6.1 after the development gates and lock.

## Compose image and offline execution

Provision the existing application image through Compose on the Linux server,
then execute isolated containers with network disabled. This does not start or
reconfigure the application, LLM or Wiki.js services. From the repository root:

```sh
docker compose build app
IMAGE=$(docker compose images -q app)
test -n "$IMAGE"
docker run --rm --network none --cpus 4 --memory 5g --memory-swap 5g \
  -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 -e TOKENIZERS_PARALLELISM=false \
  -v "$PWD/data:/data:ro" -v "$PWD/eval:/eval:ro" "$IMAGE" \
  python -m app.reranking preflight --index /data/hybrid-live.db \
  --model-path /data/models/614241f622f53c4eeff9890bdc4f31cfecc418b3 \
  --reranker-path /data/models/1427fd652930e4ba29e8149678df786c240d8825 \
  --questions /eval/questions.yaml --manifest /eval/manifest.json \
  --snapshot /data/eval/1/wiki-documents.json --fixtures /eval/fixtures/wiki-documents.json \
  --synthetic-index /data/hybrid-synthetic.db --split tuning
```

For the same isolated query/evaluation command, replace `preflight` with `query`
(and provide `--question`) or `evaluate`, respectively. Use fresh output files
only under `data/retrieval-quality-improvement/reranker-v2/`; never redirect
stdout to an input or v1 report. These are invocation examples, not the full
task 5.7 measurement harness: two fresh repeats of all three arms, first/warm
passes and whole-worker/container resource records remain mandatory. Do not
run extra quality experiments outside that protocol.

## Rollback

Stop invoking `app.reranking`; query the original read-only snapshot through
the existing RRF CLI. No model files or snapshots need modification:

```sh
python -m app.hybrid_retrieval query --index ../data/hybrid-live.db --model-path ../data/models/614241f622f53c4eeff9890bdc4f31cfecc418b3 --question 'YOUR QUESTION' --semantic-candidates 10 --lexical-candidates 1 --rrf-constant 60 --top-k 6
```

The default HTTP startup/health and pure semantic paths do not import or load
the cross-encoder. Passing structural tests does not establish live quality.
