from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import hashlib

import pytest

from app.hybrid_retrieval import HybridResult
from app.reranking import LocalCrossEncoder, RerankedIndex, RerankingError, SETTINGS, rerank, verify_assets
from test_semantic_storage import semantic_snapshot


def candidates():
    chunk = semantic_snapshot().chunks[0]
    return tuple(HybridResult(i, 1 / (60 + i), replace(chunk, chunk_id=key * 64),
                              i, .5, None, None, ()) for i, key in enumerate('cab', 1))


def test_full_union_dedup_ties_same_page_and_provenance():
    original = candidates()
    calls = []
    def score(question, chunks):
        calls.append((question, [c.chunk_id for c in chunks]))
        return {c.chunk_id: (2.0 if c.chunk_id.startswith('b') else 1.0) for c in chunks}
    scorer = SimpleNamespace(score=score, identity={'policy': 'test'})
    result = rerank('exact question', (*original, original[0]), scorer, 2)
    assert len(calls[0][1]) == 3  # Final k=2 never cuts candidates before scoring.
    assert calls[0][1] == sorted(c.chunk.chunk_id for c in original)
    assert [r.chunk.chunk_id[0] for r in result] == ['b', 'a']
    assert len({r.chunk.document.page_id for r in result}) == 1
    assert result[0].chunk is original[2].chunk
    payload = result[0].to_dict()
    assert payload['rrf_score'] == original[2].score
    assert payload['reranker_score'] == 2 and payload['rank'] == 1
    assert payload['source_ranges'] == original[2].to_dict()['source_ranges']


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -float('inf')])
def test_nonfinite_and_no_fallback(value):
    scorer = SimpleNamespace(score=lambda q, chunks: {c.chunk_id: value for c in chunks}, identity={})
    with pytest.raises(RerankingError, match='reranker_scores'):
        rerank('q', candidates(), scorer, 6)


def test_failed_model_and_missing_scores_never_return_rrf():
    def fail(q, chunks):
        raise RerankingError('model failure')
    with pytest.raises(RerankingError, match='model failure'):
        rerank('q', candidates(), SimpleNamespace(score=fail), 6)
    with pytest.raises(RerankingError, match='reranker_scores'):
        rerank('q', candidates(), SimpleNamespace(score=lambda q, c: {}), 6)


def test_invalid_limits_before_model():
    for k in (0, -1, True, 1.5):
        with pytest.raises(RerankingError, match='reranker_k'):
            rerank('q', candidates(), None, k)
    original = candidates()[0]
    many = [replace(original, chunk=replace(original.chunk, chunk_id=str(i))) for i in range(122)]
    with pytest.raises(RerankingError, match='reranker_union_limit'):
        rerank('q', many, None, 6)


def test_unknown_missing_corrupt_asset_rejected(tmp_path, monkeypatch):
    import app.reranking as module
    (tmp_path / 'asset').write_bytes(b'known')
    monkeypatch.setattr(module, 'manifest', lambda: {'assets_sha256': {'asset': hashlib.sha256(b'known').hexdigest()}})
    monkeypatch.setattr(module, 'version', lambda name: {'torch': '2.7.1+cpu', 'transformers': '4.57.3', 'tokenizers': '0.22.2'}[name])
    assert verify_assets(tmp_path)['pair_limit'] == 512
    (tmp_path / 'asset').write_bytes(b'corrupt')
    with pytest.raises(RerankingError):
        verify_assets(tmp_path)
    (tmp_path / 'asset').unlink()
    with pytest.raises(RerankingError):
        verify_assets(tmp_path)


@pytest.fixture
def real_tokenizer_scorer():
    from transformers import AutoTokenizer
    path = Path(__file__).resolve().parents[2] / 'data/models/1427fd652930e4ba29e8149678df786c240d8825'
    if not path.exists():
        pytest.skip('pinned local tokenizer unavailable')
    scorer = LocalCrossEncoder.__new__(LocalCrossEncoder)
    scorer.tokenizer = AutoTokenizer.from_pretrained(str(path), local_files_only=True, trust_remote_code=False)
    return scorer


def test_real_pair_budgets_no_padding_or_truncation(real_tokenizer_scorer):
    scorer = real_tokenizer_scorer
    question, text = 'Как проверить поле?', 'Полный текст команды и пояснение. ' * 3
    pair = scorer.pair(question, text)
    assert len(pair['input_ids']) < 512
    assert all(v == 1 for v in pair['attention_mask'])
    assert pair == scorer.tokenizer(question, text, padding=False, truncation=False)
    with pytest.raises(RerankingError, match='question_budget'):
        scorer.pair('question ' * 150, text)
    with pytest.raises(RerankingError, match='pair_budget'):
        scorer.pair(question, 'passage ' * 600)


def test_real_exact_512_boundary(real_tokenizer_scorer):
    scorer = real_tokenizer_scorer
    question = 'test'
    qlen = len(scorer.tokenizer(question, add_special_tokens=False)['input_ids'])
    text = 'test ' * (508 - qlen)
    assert len(scorer.pair(question, text)['input_ids']) == 512
    with pytest.raises(RerankingError, match='pair_budget'):
        scorer.pair(question, text + 'test ')


def test_batch_one_full_input_order_finite_raw_logit(real_tokenizer_scorer):
    import torch
    scorer = real_tokenizer_scorer
    scorer.torch = torch
    calls = []
    def model(**inputs):
        assert inputs['input_ids'].shape[0] == 1
        assert inputs['input_ids'].shape[1] < 512
        calls.append(inputs['input_ids'][0].tolist())
        return SimpleNamespace(logits=torch.tensor([[-2.25]]))
    scorer._model = model
    chunks = [r.chunk for r in candidates()]
    result = scorer.score('supplied question', chunks)
    assert list(result) == sorted(c.chunk_id for c in chunks)
    assert set(result.values()) == {-2.25}
    assert calls == [scorer.pair('supplied question', c.search_text)['input_ids']
                     for c in sorted(chunks, key=lambda c: c.chunk_id)]
    scorer._model = lambda **inputs: SimpleNamespace(logits=torch.tensor([[float('nan')]]))
    with pytest.raises(RerankingError, match='nonfinite'):
        scorer.score('q', chunks)


def test_preflight_overflow_prevents_all_model_calls(real_tokenizer_scorer):
    scorer = real_tokenizer_scorer
    scorer._load = lambda: pytest.fail('model called before complete preflight')
    chunks = [r.chunk for r in candidates()]
    chunks[-1] = replace(chunks[-1], search_text='passage ' * 600)
    with pytest.raises(RerankingError, match='pair_budget'):
        scorer.score('q', chunks)


def test_index_requests_entire_union_before_final_cutoff():
    results = candidates()
    calls = []
    def search(question, k):
        calls.append((question, k))
        return results
    base = SimpleNamespace(settings=SETTINGS, snapshot=SimpleNamespace(algorithm_version='markdown-chunking-1'),
                           metadata={'lexical': {'literal_policy_version': 1}}, chunks=tuple(r.chunk for r in results),
                           search=search, last_branch_union=tuple(r.chunk for r in results))
    scorer = SimpleNamespace(score=lambda q, chunks: {c.chunk_id: 1. for c in chunks}, identity={'policy': 'test'},
                             preflight=lambda q, chunks: [c.chunk_id for c in chunks])
    index = RerankedIndex(base, scorer)
    assert len(index.search('q', 1)) == 1
    assert calls == [('q', 121)]
    assert len(index.last_candidates) == 3
    assert len(index.trace[0]['inputs']) == 3
    base.settings = replace(SETTINGS, lexical_candidates=20)
    with pytest.raises(RerankingError, match='reranker_settings'):
        RerankedIndex(base, scorer)
