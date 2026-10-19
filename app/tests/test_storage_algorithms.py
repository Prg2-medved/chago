from dataclasses import replace

import pytest

from app.index_storage import StorageError, StorageReader, parse_output, write_snapshot
from app.lexical_storage import LexicalReader, build
from app.semantic_storage import SemanticReader, write_semantic
from test_index_storage import output
from test_semantic_storage import metadata, semantic_snapshot, unit_matrix


@pytest.mark.parametrize("algorithm", ["markdown-chunking-1", "markdown-chunking-2"])
def test_algorithm_through_all_readers(tmp_path, algorithm):
    original = semantic_snapshot()
    snapshot = replace(original, algorithm_version=algorithm)
    base, semantic, lexical = (tmp_path / name for name in ("base.db", "semantic.db", "lexical.db"))
    write_snapshot(base, snapshot)
    with StorageReader(base) as reader:
        assert reader.snapshot == snapshot
    write_semantic(semantic, snapshot, unit_matrix(len(snapshot.chunks)), metadata())
    assert SemanticReader(semantic).snapshot == snapshot
    build(semantic, lexical, tmp_path / "assets")
    with LexicalReader(lexical) as reader:
        assert reader.snapshot == snapshot


@pytest.mark.parametrize("algorithm", ["markdown-chunking-3", "broken", "markdown-chunking-2 "])
def test_unknown_algorithm_rejected(algorithm):
    data = output()
    data["algorithm_version"] = algorithm
    with pytest.raises(StorageError, match="algorithm_version"):
        parse_output(data)
