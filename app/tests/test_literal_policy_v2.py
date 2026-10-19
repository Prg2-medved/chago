import json
import sqlite3

import pytest

from app.lexical_retrieval import LexicalIndex, extract_literals, literal_matches
from app.lexical_storage import LexicalReader, LexicalStorageError, _raw_vectors, build
from app.semantic_storage import SemanticReader
from test_lexical_retrieval import search_file
from test_lexical_storage import semantic_file


def test_explicit_fields_and_quoted_command_whole():
    query = "charge_device_id clear_device_id `cmd --charge_device_id 1` br-route-plan /etc/x 10.0.0.1"
    literals = extract_literals(query, 2)
    assert [literal.value for literal in literals] == [
        "charge_device_id", "clear_device_id", "cmd --charge_device_id 1", "br-route-plan", "/etc/x", "10.0.0.1"]
    assert all(query[item.start:item.end] == item.value for item in literals)
    assert extract_literals("charge_device_id clear_device_id", 1) == ()
    assert extract_literals("charge_device_id clear_device_id") == ()


def test_suffix_generated_discontinuous_and_source_ranges(tmp_path):
    markdown = "charge_device_id_extra charge_device_id clear_device_id"
    path = search_file(tmp_path, markdown)
    with LexicalIndex(path) as index:
        matches = literal_matches(index.chunks[0], extract_literals("charge_device_id clear_device_id", 2))
        assert len(matches) == 2
        assert [markdown[item.start:item.end] for item in matches] == ["charge_device_id", "clear_device_id"]
        assert matches[0].start == markdown.index("charge_device_id", 1)
    discontinuous = search_file(tmp_path, "charge_ device_id", [[0, 7], [8, 17]])
    with LexicalIndex(discontinuous) as index:
        assert literal_matches(index.chunks[0], extract_literals("charge_device_id", 2)) == ()
    generated = search_file(tmp_path, "charge_device_id other", [[17, 22]])
    with LexicalIndex(generated) as index:
        assert literal_matches(index.chunks[0], extract_literals("charge_device_id", 2)) == ()


def test_v1_v2_build_byte_preservation_and_unknown(semantic_file, tmp_path):
    original_bytes = semantic_file.read_bytes()
    outputs = []
    for policy in (1, 2):
        target = tmp_path / f"v{policy}.db"
        build(semantic_file, target, literal_policy_version=policy)
        with LexicalReader(target) as reader:
            assert reader.metadata["literal_policy_version"] == policy
            assert reader.snapshot == SemanticReader(semantic_file).snapshot
        assert _raw_vectors(target) == _raw_vectors(semantic_file)
        outputs.append(target)
    assert semantic_file.read_bytes() == original_bytes
    with pytest.raises(LexicalStorageError):
        build(semantic_file, outputs[1], literal_policy_version=3)
    with sqlite3.connect(outputs[1]) as connection:
        metadata = json.loads(connection.execute("SELECT metadata FROM lexical_metadata").fetchone()[0])
        metadata["literal_policy_version"] = 3
        connection.execute("UPDATE lexical_metadata SET metadata=?", (json.dumps(metadata),))
    before = outputs[1].read_bytes()
    with pytest.raises(LexicalStorageError, match="lexical_version"):
        LexicalReader(outputs[1])
    assert outputs[1].read_bytes() == before


def test_snapshot_dispatch(tmp_path):
    path = search_file(tmp_path, "charge_device_id clear_device_id")
    with LexicalIndex(path) as index:
        assert index.search("charge_device_id clear_device_id")[0].literal_matches == ()
    with sqlite3.connect(path) as connection:
        metadata = json.loads(connection.execute("SELECT metadata FROM lexical_metadata").fetchone()[0])
        metadata["literal_policy_version"] = 2
        connection.execute("UPDATE lexical_metadata SET metadata=?", (json.dumps(metadata),))
    with LexicalIndex(path) as index:
        assert len(index.search("charge_device_id clear_device_id")[0].literal_matches) == 2
