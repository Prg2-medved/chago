import pytest

from app.chunking import (ALGORITHM_VERSION, PACKING_VERSION, ChunkSettings, ChunkingError,
                          build_output, chunk_document, output_bytes, parse_snapshot)
from test_chunking import snapshot
from test_chunking_structure import Counter, assert_coverage


def build(text, policy=PACKING_VERSION, settings=None):
    data = parse_snapshot(snapshot(text))
    return chunk_document(data.source, data.documents[0], Counter(), settings or ChunkSettings(), policy)


def test_adjacent_unicode_crlf_code_and_metadata():
    text = "# A\r\nПояснение 😀\r\n```sh\r\ncmd\r\n```\r\n"
    legacy, packed = build(text, ALGORITHM_VERSION), build(text)
    assert len(legacy) == 2 and len(packed) == 1
    assert packed[0].search_text == text
    assert packed[0].structure == legacy[-1].structure
    assert_coverage(text, packed)
    assert packed[0].chunk_id != legacy[0].chunk_id


@pytest.mark.parametrize("text", [
    "# A\ntext\n# B\n```\ncmd\n```\n",
    "text\n|a|\n|---|\n|b|\n",
    "text\n```\n" + "long\n" * 200 + "```\n",
    "text\n```\ncmd\n```\n```\nnext\n```\n",
])
def test_preserve_boundaries_tables_and_continuations(text):
    legacy, packed = build(text, ALGORITHM_VERSION), build(text)
    assert_coverage(text, packed)
    if "next" not in text:
        assert [(c.search_text, c.structure) for c in packed] == [(c.search_text, c.structure) for c in legacy]
    else:
        assert len(packed) == 2  # A preceding code chunk is never pending prose.


def test_combined_budget_rejected_and_legacy_byte_equality():
    text = "x" * 330 + "\n```\n" + "y" * 130 + "\n```\n"
    assert len(build(text)) == len(build(text, ALGORITHM_VERSION)) == 2
    data = parse_snapshot(snapshot(text))
    default = build_output(data, Counter(), ChunkSettings())
    explicit = build_output(data, Counter(), ChunkSettings(), ALGORITHM_VERSION)
    assert output_bytes(default) == output_bytes(explicit)
    with pytest.raises(ChunkingError, match="algorithm_version"):
        build_output(data, Counter(), ChunkSettings(), "unknown")


def test_page_boundary_and_full_input_budget():
    data = snapshot("text\n```\ncmd\n```\n")
    other = {**data["documents"][0], "page_id": 2, "path": "other", "source_url": "https://wiki.example/ru/other"}
    data["documents"].append(other)
    result = build_output(parse_snapshot(data), Counter(), ChunkSettings(), PACKING_VERSION)
    assert len(result["chunks"]) == 2
    text = "x" * 30 + "\n```\n" + "y" * 30 + "\n```\n"
    chunks = build(text, settings=ChunkSettings(input_limit=65))
    assert len(chunks) == 2 and all(c.input_tokens <= 65 for c in chunks)
