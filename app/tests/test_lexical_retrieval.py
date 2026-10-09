from dataclasses import replace

import pytest

from app.index_storage import parse_output, write_snapshot
from app.lexical_retrieval import LexicalIndex, LexicalRetrievalError, extract_literals, literal_matches
from app.lexical_storage import _write_extension, lexical_metadata
from test_index_storage import output
from test_lexical_storage import lexical_file, semantic_file


def search_file(tmp_path, markdown, ranges=None, count=1):
    data = output(markdown)
    base = data["chunks"][0]
    if ranges is not None:
        base["source_ranges"] = ranges
        base["segments"] = [{"kind": "generated", "reason": "separator", "text": "route-plan "},
                            *[{"kind": "source", "start": a, "end": b, "role": "code"} for a, b in ranges]]
        base["search_text"] = "route-plan " + "".join(markdown[a:b] for a, b in ranges)
    data["chunks"] = [{**base, "chunk_id": f"{i + 1:064x}", "ordinal": i} for i in range(count)]
    snapshot = parse_output(data)
    path = tmp_path / "search.db"
    write_snapshot(path, snapshot)
    _write_extension(path, snapshot, lexical_metadata(snapshot))
    return path


def test_real_unicode61_and_ties(tmp_path):
    path = search_file(tmp_path, "Настройка СЕРВЕРА abc MixedCase", count=3)
    with LexicalIndex(path) as index:
        one = index.search("сервера mixedcase", 99)
        assert len(one) == 3
        assert [result.rank for result in one] == [1, 2, 3]
        assert [result.chunk.chunk_id for result in one] == sorted(chunk.chunk_id for chunk in index.chunks)
        assert all(result.bm25_score < 0 for result in one)
        assert one == index.search("СЕРВЕРА, mixedcase! сервера", 99)
        assert index.search("unknown") == ()
        assert index.search("!!!") == ()
        assert index._probe.execute("SELECT count(*) FROM terms").fetchone()[0] == 0
    with pytest.raises(LexicalRetrievalError, match="lexical_closed"):
        index.search("abc")


@pytest.mark.parametrize("question", [None, True, 3, "", " \n", "\ud800", "x\x00y"])
def test_invalid_question(lexical_file, question):
    with LexicalIndex(lexical_file) as index, pytest.raises(LexicalRetrievalError, match="lexical_question"):
        index.search(question)


@pytest.mark.parametrize("k", [True, False, 0, -1, 1.5, "2", None])
def test_invalid_k(lexical_file, k):
    with LexicalIndex(lexical_file) as index, pytest.raises(LexicalRetrievalError, match="lexical_k"):
        index.search("word", k)


@pytest.mark.parametrize("text,expected", [
    ("Адрес 10.20.30.40, IPv6 2001:db8::1.", [("10.20.30.40", "ip"), ("2001:db8::1", "ip")]),
    ("'/etc/route-plan/config.yaml', ./foo-bar; ../config/file и config/file", [("/etc/route-plan/config.yaml", "path"), ("./foo-bar", "path"), ("../config/file", "path"), ("config/file", "path")]),
    (r"C:\foo-bar\config.yaml и \\server\share\file", [(r"C:\foo-bar\config.yaml", "path"), (r"\\server\share\file", "path")]),
    ("`systemctl restart route-plan` route-plan", [("systemctl restart route-plan", "quoted"), ("route-plan", "identifier")]),
    ("`route-plan` `10.20.30.40` `/etc/config`", [("route-plan", "identifier"), ("10.20.30.40", "ip"), ("/etc/config", "path")]),
    ("Незакрыто `route-plan", [("route-plan", "identifier")]),
    ("`  ` и 10.20.30.400 и prose", []),
    ("``route-plan``", [("route-plan", "identifier")]),
])
def test_literal_extraction_offsets(text, expected):
    literals = extract_literals(text)
    assert [(item.value, item.kind) for item in literals] == expected
    assert all(text[item.start:item.end] == item.value for item in literals)


def test_exact_boundaries_unicode_crlf_overlap(tmp_path):
    markdown = "😀 Заголовок\r\nroute-plan route-planner xroute-plan route-plan_x 10.20.30.40 10.20.30.400 /etc/a.yaml /etc/a.yaml.bak\r\n"
    path = search_file(tmp_path, markdown, [[0, len(markdown)], [0, 20]])
    with LexicalIndex(path) as index:
        result = index.search("route-plan 10.20.30.40 /etc/a.yaml")[0]
        assert len(result.literal_matches) == 3
        for match in result.literal_matches:
            assert markdown[match.start:match.end] == match.literal
        assert result.literal_matches[0].start == markdown.index("route-plan")
        assert result.to_dict()["segments"][0]["kind"] == "generated"
        assert result.chunk.structure["continued_before"] is True


def test_cut_identifier_full_markdown_boundary(tmp_path):
    path = search_file(tmp_path, "route-planner", [[0, 10]])
    with LexicalIndex(path) as index:
        result = index.search("route-plan")[0]
        assert result.literal_matches == ()


def test_generated_discontinuous_and_adjacent(tmp_path):
    path = search_file(tmp_path, "abcXXXdef", [[0, 3], [6, 9]])
    with LexicalIndex(path) as index:
        assert index.search("route-plan")[0].literal_matches == ()
        assert index.search("`abcdef`")[0].literal_matches == ()
        chunk = index.chunks[0]
        adjacent = replace(chunk, source_ranges=((0, 3), (3, 9)))
        assert literal_matches(adjacent, extract_literals("`abcXXXdef`"))[0].start == 0


def test_literal_only_null_bm25(tmp_path):
    path = search_file(tmp_path, "😀 !!!")
    with LexicalIndex(path) as index:
        result = index.search("`!!!`")[0]
        assert result.bm25_score is None
        assert result.literal_matches[0].literal == "!!!"


def test_literal_priority_before_bm25_limit(tmp_path):
    data = output("noise route-plan " + "filler " * 800)
    base = data["chunks"][0]
    chunks = []
    for i in range(12):
        start, end = (0, 5) if i < 11 else (0, len(data["documents"][0]["markdown"]))
        chunks.append({**base, "chunk_id": f"{i + 1:064x}", "ordinal": i,
                       "source_ranges": [[start, end]],
                       "segments": [{"kind": "generated", "reason": "separator", "text": "route-plan "},
                                    {"kind": "source", "start": start, "end": end, "role": "code"}],
                       "search_text": "route-plan " + data["documents"][0]["markdown"][start:end]})
    data["chunks"] = chunks
    snapshot = parse_output(data)
    path = tmp_path / "priority.db"
    write_snapshot(path, snapshot)
    _write_extension(path, snapshot, lexical_metadata(snapshot))
    with LexicalIndex(path) as index:
        expression = index._expression("noise `route-plan`")
        raw = index._reader._connection.execute("SELECT chunk_id FROM chunk_fts WHERE chunk_fts MATCH ? ORDER BY bm25(chunk_fts), chunk_id", (expression,)).fetchall()
        assert raw[-1][0] == chunks[-1]["chunk_id"]
        assert index.search("noise `route-plan`", 10)[0].chunk.chunk_id == chunks[-1]["chunk_id"]


def test_distinct_literals_count(tmp_path):
    path = search_file(tmp_path, "route-plan other-name route-plan")
    with LexicalIndex(path) as index:
        result = index.search("route-plan route-plan other-name")[0]
        assert len({item.literal for item in result.literal_matches}) == 2
        assert len(result.literal_matches) == 3
