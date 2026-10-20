# Retrieval quality improvement: historical experiment evidence

Archived on 2026-10-20 as a negative experiment: cross-encoder reranker rejected,
quality acceptance still open, 17/25 tasks completed. No further v2 inference
or repeats are authorized. Historical instructions below this directory are
evidence of the procedure at their respective dates, not permission to run it.

See the [current short outcome](../../retrieval-quality-result.md) and the
[existing OpenSpec archive](../../../openspec/changes/archive/2026-10-20-retrieval-quality-improvement/).
The archive is the sole source for proposal/design/tasks/delta specs; none are
copied here. Main specs were not synchronized when the change was archived.

## Relocation inventory

All paths in this table are repository-relative. All 21 historical files retain
their exact bytes from immediately before relocation, including the complete
result with its reporting addenda. These are relocation SHA-256 values, not new
experiment commitments or an acceptance lock. The root result is now a short
summary, so its old address has a different role.

| Old path | New path | SHA-256 of preserved bytes |
| --- | --- | --- |
| `docs/retrieval-quality-5-7-manual.md` | [`docs/experiments/retrieval-quality-improvement/retrieval-quality-5-7-manual.md`](retrieval-quality-5-7-manual.md) | `3f25e81c4ed70ffd2c1e6b956db5fc6a57d8d97339ca0202ad431e80ad4ad1ad` |
| `docs/retrieval-quality-5-7-run.sh` | [`docs/experiments/retrieval-quality-improvement/retrieval-quality-5-7-run.sh`](retrieval-quality-5-7-run.sh) | `08be055ceba4325acd4249b4b66816d6566b07f0cc453a3e74b5293aac42b04a` |
| `docs/retrieval-quality-5-7-test.py` | [`docs/experiments/retrieval-quality-improvement/retrieval-quality-5-7-test.py`](retrieval-quality-5-7-test.py) | `4ec0b4d91f76da9c1ef84a10a84ece37ed4b8f88de7059dcd4f672e0d34428f4` |
| `docs/retrieval-quality-5-7-tools.py` | [`docs/experiments/retrieval-quality-improvement/retrieval-quality-5-7-tools.py`](retrieval-quality-5-7-tools.py) | `6ac4020a94192342e699af6e879731ceb7ea63ebd895fb6c154f5cfe05c68d8b` |
| `docs/retrieval-quality-build-report.json` | [`docs/experiments/retrieval-quality-improvement/retrieval-quality-build-report.json`](retrieval-quality-build-report.json) | `13ccd1e476d291df304caaea393d8fb013e4d29dba7676f4e647ddc2ad15c330` |
| `docs/retrieval-quality-development.json` | [`docs/experiments/retrieval-quality-improvement/retrieval-quality-development.json`](retrieval-quality-development.json) | `11d5899d00d7c75813f787a7f3e5343885d33537d3f7f11422767b9cf5c5bbd9` |
| `docs/retrieval-quality-evidence-audit-v2.json` | [`docs/experiments/retrieval-quality-improvement/retrieval-quality-evidence-audit-v2.json`](retrieval-quality-evidence-audit-v2.json) | `feb478b9aa11ad8a1ab83432e4b46032465d96ca2ecf42ef6d497e9d77792464` |
| `docs/retrieval-quality-experiment-protocol-v2.md` | [`docs/experiments/retrieval-quality-improvement/retrieval-quality-experiment-protocol-v2.md`](retrieval-quality-experiment-protocol-v2.md) | `6efdb9a7cbd836145926483669e60735f76409222e8fe459d631dff1493e7a47` |
| `docs/retrieval-quality-experiment-protocol.md` | [`docs/experiments/retrieval-quality-improvement/retrieval-quality-experiment-protocol.md`](retrieval-quality-experiment-protocol.md) | `c41b1156d04cc368e3db4f0de8ffbaf20fb250c7a56429230d78d7abe2ea2e5a` |
| `docs/retrieval-quality-improvement.md` | [`docs/experiments/retrieval-quality-improvement/retrieval-quality-improvement.md`](retrieval-quality-improvement.md) | `2a8a9440f799b02f11839617cb075b77857b798cf907dc509c0a8c5be7e843dd` |
| `docs/retrieval-quality-literal-builds.json` | [`docs/experiments/retrieval-quality-improvement/retrieval-quality-literal-builds.json`](retrieval-quality-literal-builds.json) | `9071e4d39eca946480108621b1bb4a499e96d605cc4fe4308144884357043215` |
| `docs/retrieval-quality-offline-bundle-v2.md` | [`docs/experiments/retrieval-quality-improvement/retrieval-quality-offline-bundle-v2.md`](retrieval-quality-offline-bundle-v2.md) | `719770140b2df616b0c488c1c8f93825cedce4582125c80d534a514daeed12c5` |
| `docs/retrieval-quality-packing-feasibility.json` | [`docs/experiments/retrieval-quality-improvement/retrieval-quality-packing-feasibility.json`](retrieval-quality-packing-feasibility.json) | `d990b03ccb4fcc0d4b23cf7c5855d29bcd27b4678f03e961c60101c73a649b76` |
| `docs/retrieval-quality-preflight-v2.json` | [`docs/experiments/retrieval-quality-improvement/retrieval-quality-preflight-v2.json`](retrieval-quality-preflight-v2.json) | `7fde596612e52592dd924662ef7083d2a1f29fcdad81cc2e33075a1a54065765` |
| `docs/retrieval-quality-protocol-receipt-v2.json` | [`docs/experiments/retrieval-quality-improvement/retrieval-quality-protocol-receipt-v2.json`](retrieval-quality-protocol-receipt-v2.json) | `7054e6e47f2a5a4fd117af3192293450c04fbdfa4df85502f63815d1c3d92222` |
| `docs/retrieval-quality-protocol-receipt.json` | [`docs/experiments/retrieval-quality-improvement/retrieval-quality-protocol-receipt.json`](retrieval-quality-protocol-receipt.json) | `8ab70b2d4df35a42da2529dfe0118107ec5ef7c3d2fdbdc613057914b0aa4a03` |
| `docs/retrieval-quality-result-v1-frozen.md` | [`docs/experiments/retrieval-quality-improvement/retrieval-quality-result-v1-frozen.md`](retrieval-quality-result-v1-frozen.md) | `49008ac640564014fc4e2e5d4fabaaa766a472102ae671f35f11a9c607f58a42` |
| `docs/retrieval-quality-result-v2.md` | [`docs/experiments/retrieval-quality-improvement/retrieval-quality-result-v2.md`](retrieval-quality-result-v2.md) | `863f6e1caf1d0fde5ed561774afd3294da5181a8f778aaec5e2526e80cc6c979` |
| `docs/retrieval-quality-result.md` | [`docs/experiments/retrieval-quality-improvement/retrieval-quality-result.md`](retrieval-quality-result.md) | `067e3d33f7e6947e3bb76327631c9077f39b4feb56688cf4c8bd052ae4a7c071` |
| `docs/retrieval-quality-tuning-grid.json` | [`docs/experiments/retrieval-quality-improvement/retrieval-quality-tuning-grid.json`](retrieval-quality-tuning-grid.json) | `131bd790c6ac0e8c93c6ed439de594fa8f22b6d94e035238aa996fdac90839f4` |
| `docs/retrieval-quality-verification.json` | [`docs/experiments/retrieval-quality-improvement/retrieval-quality-verification.json`](retrieval-quality-verification.json) | `eb71237edc1f8fa85e80d19ed1149f14b9f6d1957d84c59b915174d3782e9e78` |

## Evidence and known limitations

- At inventory time, 75 of 76 execution commitments matched the local files.
  The exception was the old `docs/retrieval-quality-result.md`: disclosed
  reporting addenda changed its bytes. Its complete pre-relocation version is
  [preserved here](retrieval-quality-result.md), SHA-256
  `067e3d33f7e6947e3bb76327631c9077f39b4feb56688cf4c8bd052ae4a7c071`.
- The [frozen v1 result](retrieval-quality-result-v1-frozen.md) retains the
  original committed SHA-256
  `49008ac640564014fc4e2e5d4fabaaa766a472102ae671f35f11a9c607f58a42`.
  Existing receipts still commit that original content at the old result path.
  Neither the current root summary nor the complete report matches that
  historical commitment. Relocation must not be represented as 76/76.
- The [v1 receipt](retrieval-quality-protocol-receipt.json) records
  `source_receipt_sha256 =
  9c8a78584600e584fa7621d2b39b1dea398d392912198c24b8863592d776d555`
  without a source path. The source receipt could not be identified in the
  inspected related directories; this commitment remains unverified.
- At inventory time all nine protected inputs, all 36 grid reports, both
  baseline hashes, the results TAR and its 60 extracted files matched their
  recorded identities. The seven server integrity receipts were byte-identical.
  The v2 receipt also matched its copy in the results archive.
- Of 141 transport entries, the local manual and complete result had disclosed
  post-run reporting changes. The audit's intermediate documentation hashes
  describe an earlier reporting snapshot, not the final owner-decision text.
  Preserve that distinction; do not update historical manifests to hide it.
- Second fresh v2 repeats and final/independent acceptance evidence are absent.
  Synthetic measurement-test fixtures with repeat=2 and 8/9 are not real runs.

Protocols, receipts, reports, scripts and historical prose were moved without
rewriting embedded paths, hashes or commands. The targeted `.gitattributes`
rule disables text normalization for these historical files and allows their
original CRLF line endings. This index is newly authored navigation.
Seven historical JSON files had normalized LF blobs in the parent Git commit
but CRLF bytes in the pre-relocation checkout. Their new blobs preserve those
original checkout bytes and SHA-256 values; the apparent content changes in
the Git diff are only line endings, not rewritten evidence.

## Links and historical addresses

Links between the preserved documents continue to resolve because all files
remain together with their original names. Embedded repository paths such as
`docs/retrieval-quality-protocol-receipt-v2.json` are historical logical
addresses; resolve them through the inventory above, not relative to this index.
Paths under `data/`, `eval/` and `app/` also remain repository-relative.

No compatibility stubs were created. References in immutable OpenSpec history
to former root-doc addresses therefore require this inventory; the old
`docs/retrieval-quality-result.md` now leads to the current summary.
There was already a broken Markdown link in archived `design.md:88`:
`../../../docs/retrieval-quality-experiment-protocol-v2.md` resolves to
`openspec/docs/...` after archival. Its intended target is the
[preserved v2 protocol](retrieval-quality-experiment-protocol-v2.md).
The archived design remains unchanged. These historical address limitations
are explicit and are not repaired with redirects or changes to OpenSpec.

## Restore the historical directory layout

Use a separate, previously nonexistent directory outside the checkout. Keep
this checkout, raw data, historical archives and receipts unchanged. The
following documentation-only example, run from the repository root, copies
the 21 preserved files back under their old `docs/` names and verifies that
copying did not change bytes. It does not load models or execute the experiment.
Replace the destination with a suitable new absolute path.

```python
from pathlib import Path
import hashlib
import shutil

source = Path("docs/experiments/retrieval-quality-improvement").resolve()
destination = Path("D:/Temp/retrieval-quality-history-review").resolve()
assert not destination.exists(), "Use a fresh directory"
checkout = Path.cwd().resolve()
assert destination != checkout and checkout not in destination.parents
files = sorted(source.glob("retrieval-quality*"))
assert len(files) == 21 and all(path.is_file() for path in files)
(destination / "docs").mkdir(parents=True)
for original in files:
    restored = destination / "docs" / original.name
    shutil.copyfile(original, restored)
    assert hashlib.sha256(restored.read_bytes()).digest() == hashlib.sha256(
        original.read_bytes()
    ).digest()
```

Compare the source hashes against the inventory before restoration. This
recreates the documentation state immediately before relocation, including the
complete result with addenda; its execution-commitment status remains 75/76
when combined with the other original artifacts. It does not recreate an
executable historical worktree by itself.

For an investigation of the original v1 commitment only, make another separate
view and place the frozen v1 bytes at that view's
`docs/retrieval-quality-result.md`. Clearly label it as reconstructed original
v1 content. Keep the full report in the first restored view. This content
substitution explains the old digest; it is not a repair of the current
75/76 inventory, a new receipt or permission to execute inference.

The manual tools hard-code root-relative `docs/`, `app/`, `eval/` and
`data/` addresses. The synthetic test imports its neighboring tools file and
uses `Path(__file__).resolve().parents[1] / "data"`; it should not be executed
directly from this relocated directory. To inspect historical behavior, use
the restored layout and the matching original transport/code/assets, rather
than rewriting the preserved scripts or mixing current code with old receipts.

Full historical reproducibility additionally requires the original transport
and its file manifest, matching application/test code and pinned runtime,
`eval/` inputs, both baseline JSON files at their original root-doc addresses,
read-only snapshots, model/tokenizer assets and all 36 worker reports.
These remain at their existing locations; relocation does not vendor them.
The v2 receipt records code/worktree and asset identities. The original
transport is described by `transfer-20261019-01.tar` and its adjacent JSON
manifest under `data/retrieval-quality-improvement/reranker-v2/` when available.
Reconstruct from those original bytes and verify their recorded hashes; the
post-reporting copies of the manual/result are not transport-identical.

The saved results archive is
`data/retrieval-quality-improvement/reranker-v2/download-20261019-01/rq57-20261019-01-results.tar`,
SHA-256 `e98c230fbec36f0071e36649cb76b8390844d006358942e1b4bb112c81cd1d7b`.
Its layout and all 60 member hashes are recorded in the
[evidence audit](retrieval-quality-evidence-audit-v2.json).
The local audit helper remains
`data/retrieval-quality-improvement/reranker-v2/download-20261019-01/audit_saved_evidence.py`.
Do not overwrite existing extracted evidence while reconstructing a separate view.
The `data/` artifacts and model assets are ignored by Git and are not supplied
by a clean clone of this documentation commit; retain them separately.

Restoring paths enables inspection and hash checks, not additional experiment
runs. The historical STOP decision and incomplete acceptance gates remain in
force.
