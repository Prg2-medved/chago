# Retrieval quality experiment: final outcome

2026-10-20. **Negative result; retrieval quality acceptance remains open.**
The cross-encoder reranker was rejected. No further v2 runs are authorized.

| Phase | Tuning result | Decision |
| --- | --- | --- |
| V1: 36 chunking/literal/candidate-limit combinations | Best 6/9, required >=8/9 | Stop before lock |
| V2: sole CPU cross-encoder | 4/9 versus legacy/control 6/9; warm latency 258.071122x legacy, allowed <=2x | Quality and latency gates failed |

Only one fresh run per v2 arm exists; first/warm equality does not establish
the missing second fresh repeat. No acceptance lock, final frozen candidate
comparison, final target-server acceptance or independent validation was completed.
The closed validation package remains unused.

The [OpenSpec change](../openspec/changes/archive/2026-10-20-retrieval-quality-improvement/)
was archived without spec synchronization on 2026-10-20, retaining **17/25**
completed tasks and eight unfinished tasks. This administrative closure does
not accept the experimental retrieval policies or satisfy MVP quality acceptance.

The [experiment index](experiments/retrieval-quality-improvement/index.md)
contains the path/hash inventory, historical-structure restoration procedure,
[complete report](experiments/retrieval-quality-improvement/retrieval-quality-result.md)
and [detailed v2 analysis](experiments/retrieval-quality-improvement/retrieval-quality-result-v2.md).
Known limitations remain **75/76 matching execution commitments** at inventory
time (the historical result path gained disclosed reporting addenda; original
v1 bytes are preserved) and an **unidentified source receipt v1**. Relocation
does not repair or replace those historical commitments.
