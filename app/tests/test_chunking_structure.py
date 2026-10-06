from dataclasses import asdict
import hashlib
from pathlib import Path

import pytest

from app.chunking import (ChunkSettings, ChunkingError, SourceSegment, build_output,
                          chunk_document, output_bytes, parse_snapshot, pipe_cells, scan)
from app.chunk_tokenizer import LocalE5, REVISION
from test_chunking import snapshot


class Counter:
    identity = {"test": "character-counter"}

    def count(self, text, special=False):
        return len(text) + (2 if special else 0)


def make_chunks(text, settings=None, title="Test", counter=None):
    payload = snapshot(text)
    payload["documents"][0]["title"] = title
    source = parse_snapshot(payload)
    return chunk_document(source.source, source.documents[0], counter or Counter(), settings or ChunkSettings())


def assert_coverage(text, chunks):
    covered = set()
    for chunk in chunks:
        rendered = []
        for segment in chunk.segments:
            if isinstance(segment, SourceSegment):
                covered.update(range(segment.start, segment.end))
                rendered.append(text[segment.start:segment.end])
                assert segment.text(chunk.document) == text[segment.start:segment.end]
            else:
                rendered.append(segment.text)
        assert "".join(rendered) == chunk.search_text
        assert chunk.body_tokens <= 450 and chunk.input_tokens <= 512
    assert covered == set(range(len(text)))


@pytest.mark.parametrize("text", [
    "Preamble\r\n# First\r\n### Skipped\r\nbody\r\n## Sibling\r\n",
    "Title\n=====\nsubtitle\n---\nbody\n", "# heading only", "##\n",
    "```bash\n# not a heading\ncmd\n```\n# real\ntext\n",
    "~~~python\n## code\n~~~\n", "````bash\n```\n# code\n````\n",
    "```bash\n# unclosed\n", "    indented code\n- nested list\n![image](x)\n",
])
def test_scanner_lossless(text):
    blocks = scan(text)
    assert "".join(text[block.start:block.end] for block in blocks) == text
    assert_coverage(text, make_chunks(text))


def test_heading_paths():
    blocks = scan("intro\n# A\n### B\ncode\n## C\n# D\n")
    assert [(block.kind, block.headings) for block in blocks] == [
        ("text", ()), ("heading", ("A",)), ("heading", ("A", "B")),
        ("text", ("A", "B")), ("heading", ("A", "C")), ("heading", ("D",)),
    ]


def test_prose_overlap_and_large_page():
    text = "# A\n" + "literal/IP/10.0.0.1 😀 " * 600 + "\n# B\n" + "body " * 600
    chunks = make_chunks(text)
    assert_coverage(text, chunks)
    assert any(segment.role == "overlap" for chunk in chunks for segment in chunk.segments if isinstance(segment, SourceSegment))
    for chunk in chunks:
        assert chunk.heading_path in (("A",), ("B",))
        if chunk.heading_path == ("B",):
            assert all(segment.start >= text.index("# B") for segment in chunk.segments if isinstance(segment, SourceSegment))


def test_overlap_shrinks_for_metadata():
    chunks = make_chunks("x" * 2500, title="t" * 250)
    assert_coverage("x" * 2500, chunks)
    assert all(chunk.input_tokens <= 512 for chunk in chunks)


def test_fitting_code_above_target_stays_whole():
    text = "```bash\n" + "a" * 360 + "\n```\n"
    chunks = make_chunks(text)
    assert len(chunks) == 1 and chunks[0].search_text == text
    assert chunks[0].body_tokens > 350
    assert not chunks[0].structure.get("requires_complete_block")


@pytest.mark.parametrize("text", [
    "```bash\r\ncurl \\\r\n" + "arg \\\r\n" * 180 + "end\r\n```\r\n",
    "~~~bash\n" + "😀" * 1600 + "\n~~~\n",
])
def test_split_code_reconstructs_and_marks_all_parts(text):
    chunks = make_chunks(text)
    assert_coverage(text, chunks)
    assert "".join(text[segment.start:segment.end] for chunk in chunks for segment in chunk.segments
                   if isinstance(segment, SourceSegment)) == text
    assert all(chunk.structure["requires_complete_block"] for chunk in chunks)
    assert len({chunk.structure["block_id"] for chunk in chunks}) == 1
    assert [chunk.structure["part_index"] for chunk in chunks] == list(range(len(chunks)))
    assert chunks[0].structure["continued_after"] and chunks[-1].structure["continued_before"]
    if "😀" in text:
        assert any(chunk.structure["split_line"] for chunk in chunks)


def test_pipe_cells():
    assert pipe_cells(r"| a\|b | `a|b` | ``a`|b`` |") == [" a\\|b ", " `a|b` ", " ``a`|b`` "]


def test_table_rows_and_oversized_cell():
    text = "| ID | value |\r\n| --- | --- |\r\n" + "| id-123 | " + "😀x" * 1000 + " |\r\n" + "| other | exact |\r\n" * 30
    chunks = make_chunks(text)
    assert_coverage(text, chunks)
    assert "".join(text[segment.start:segment.end] for chunk in chunks for segment in chunk.segments
                   if isinstance(segment, SourceSegment)) == text
    assert all(chunk.search_text.startswith("| ID | value |\r\n| --- | --- |\r\n") for chunk in chunks)
    assert len({chunk.structure["table_id"] for chunk in chunks}) == 1
    assert any(chunk.structure.get("continued_after") for chunk in chunks)
    assert all(segment.kind == "generated" for chunk in chunks[1:] for segment in chunk.segments if not isinstance(segment, SourceSegment))


def test_oversized_header_errors():
    text = "| " + "x" * 600 + " |\n| --- |\n| data |\n"
    with pytest.raises(ChunkingError, match="table_header_budget"):
        make_chunks(text)


def test_deterministic_order_and_identity():
    payload = snapshot("text")
    second = dict(payload["documents"][0], page_id=2, path="other", source_url="https://wiki.example/ru/other")
    payload["documents"].append(second)
    counter = Counter()
    first = build_output(parse_snapshot(payload), counter, ChunkSettings())
    payload["documents"].reverse()
    assert output_bytes(first) == output_bytes(build_output(parse_snapshot(payload), counter, ChunkSettings()))
    original_id = first["chunks"][0]["chunk_id"]
    for kind in ("metadata", "settings", "tokenizer", "source"):
        altered = snapshot("text")
        settings = ChunkSettings(target=349) if kind == "settings" else ChunkSettings()
        tokenizer = Counter()
        if kind == "metadata":
            altered["documents"][0]["title"] = "Rename"
        if kind == "tokenizer":
            tokenizer.identity = {"test": "changed"}
        if kind == "source":
            altered["source"] = "https://synthetic.example"
            altered["documents"][0]["source_url"] = "https://synthetic.example/ru/test"
        assert build_output(parse_snapshot(altered), tokenizer, settings)["chunks"][0]["chunk_id"] != original_id


def test_empty_output_retains_documents():
    result = build_output(parse_snapshot(snapshot("")), Counter(), ChunkSettings())
    assert result["chunks"] == []
    assert result["documents"][0]["markdown"] == ""


def test_real_e5_structures():
    path = Path(__file__).resolve().parents[2] / "data/tokenizers" / REVISION
    if not path.is_dir():
        pytest.skip("local E5 assets required")
    text = "# Раздел\r\n```bash\r\n" + "команда --literal=10.0.0.1\r\n" * 200 + "```\r\n| ID | value |\n| --- | --- |\n| id | " + "длинная ячейка " * 700 + " |\n"
    chunks = make_chunks(text, counter=LocalE5(path))
    assert_coverage(text, chunks)
