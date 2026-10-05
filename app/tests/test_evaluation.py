from copy import deepcopy
import hashlib
import json
import os
import subprocess
import sys

import pytest

from app.evaluation import STARTER_QUESTIONS, ValidationError, main, validate_package


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def document(page_id, markdown, source):
    return {"page_id": page_id, "locale": "ru", "path": f"page-{page_id}",
            "title": "Test", "source_url": f"{source}/ru/page-{page_id}",
            "updated_at": "2026-10-05T00:00:00.000000Z", "markdown": markdown,
            "content_sha256": sha(markdown.encode("utf-8"))}


def evidence(doc, eid, start=0, end=None):
    if end is None:
        end = len(doc["markdown"])
    return {"id": eid, **{k: doc[k] for k in ("page_id", "locale", "path", "content_sha256")},
            "spans": [{"start": start, "end": end, "exact_text": doc["markdown"][start:end]}]}


class Package:
    def __init__(self, root):
        self.root = root
        self.live = {"schema_version": 1, "source": "https://live.example", "documents": [
            document(1, "# Проверка\r\nЖ😀\r\ncmd --full\r\nПовтор\r\nПовтор\r\n", "https://live.example"),
            document(2, "# Other\nOther claim\n", "https://live.example")]}
        self.synthetic = {"schema_version": 1, "source": "https://wiki.example", "documents": [
            document(1, "Synthetic only\n", "https://wiki.example")]}
        self.manifest = {"schema_version": 1, "corpus_version": 1}
        self.corpus = {"schema_version": 1, "corpus_version": 1, "questions": []}
        for index, question in enumerate(sorted(STARTER_QUESTIONS)):
            self.add(f"q{index}", question, holdout=index == 0)
        first = self.corpus["questions"][0]
        first["tags"] = ["text", "identifier", "code", "table", "long_code", "similar_identifiers",
                         "prompt_injection", "conflict", "composite"]
        first["expected_behavior"] = "report_conflict"
        first["evidence"].append(evidence(self.live["documents"][1], "e2"))
        first["required_facts"][0]["evidence_ids"].append("e2")
        first["exact_commands"] = ["cmd --full"]
        for q in self.corpus["questions"][1:3]:
            q["tags"] = ["follow_up"]
            q["previous_question"] = "Предыдущий вопрос"
        self.corpus["questions"][1]["split"] = "holdout"
        for index in range(3):
            self.add(f"r{index}", "Неизвестно?", behavior="refuse", holdout=index < 2)
        self.add("partial", "Частично?", behavior="partial_answer")
        self.corpus["questions"][-1]["missing_information"] = "Нет второй части"
        self.add("clarify", "Что?", behavior="clarify")
        self.corpus["questions"][-1]["clarification"] = "Какой сервис?"

    def add(self, case_id, question, behavior="answer", holdout=False, namespace="live"):
        answerable = behavior not in ("refuse", "clarify")
        doc = (self.live if namespace == "live" else self.synthetic)["documents"][0]
        self.corpus["questions"].append({
            "id": case_id, "question": question, "tags": [behavior if behavior != "answer" else "text"],
            "split": "holdout" if holdout else "tuning", "source_set": namespace,
            "answerable": answerable, "expected_behavior": behavior,
            "required_facts": [{"text": "Факт", "evidence_ids": ["e1"]}] if answerable else [],
            "evidence": [evidence(doc, "e1")] if answerable else [], "exact_commands": []})

    def save_json(self, name, payload):
        path = self.root / name
        path.write_bytes((json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode())
        return path

    def save(self, synthetic=False):
        self.paths = [self.save_json("questions.yaml", self.corpus), self.root / "manifest.json",
                      self.save_json("live.json", self.live)]
        entries = [("live", self.live, self.paths[2])]
        if synthetic:
            fixture = self.save_json("synthetic.json", self.synthetic)
            self.paths.append(fixture)
            entries.append(("synthetic", self.synthetic, fixture))
        for namespace, snap, path in entries:
            self.manifest[namespace] = {
                "source": snap["source"], "sha256": sha(path.read_bytes()),
                "document_count": len(snap["documents"]),
                "documents": [{k: d[k] for k in ("page_id", "locale", "path", "content_sha256")}
                              for d in snap["documents"]]}
        self.save_json("manifest.json", self.manifest)
        return self.paths

    def check(self):
        return validate_package(*self.paths)

    def argv(self):
        return [part for name, path in zip(("questions", "manifest", "snapshot", "fixtures"), self.paths)
                for part in (f"--{name}", str(path))]


@pytest.fixture
def package(tmp_path):
    return Package(tmp_path)


@pytest.mark.parametrize("count", [9, 20, 27])
def test_valid_without_count_limit(package, count):
    for index in range(count - len(package.corpus["questions"])):
        package.add(f"extra{index}", "Дополнительный вопрос")
    package.save()
    report = package.check()
    assert report.questions == count
    assert report.documents == {"live": 2}


def test_synthetic_namespace(package):
    package.add("synthetic", "Synthetic?", namespace="synthetic")
    package.save(synthetic=True)
    assert package.check().documents == {"live": 2, "synthetic": 1}
    q = package.corpus["questions"][-1]
    q["evidence"] = deepcopy(package.corpus["questions"][3]["evidence"])
    package.save(synthetic=True)
    with pytest.raises(ValidationError, match="identity: synthetic"):
        package.check()


@pytest.mark.parametrize("field,value", [
    ("id", "q1"), ("id", "secret\npassword=value"), ("id", []),
    ("answerable", 1), ("answerable", False), ("split", "other"),
    ("source_set", "other"), ("expected_behavior", "other"),
    ("tags", "text"), ("tags", ["invalid"]), ("required_facts", {}),
    ("evidence", []), ("exact_commands", "cmd"), ("previous_question", "unexpected"),
])
def test_invalid_question_fields(package, field, value):
    package.corpus["questions"][3][field] = value
    package.save()
    with pytest.raises(ValidationError):
        package.check()


@pytest.mark.parametrize("target,field,value", [
    ("corpus", "schema_version", True), ("corpus", "schema_version", 2),
    ("corpus", "corpus_version", "1"), ("manifest", "corpus_version", False),
    ("manifest", "schema_version", 0), ("live", "schema_version", 2),
])
def test_invalid_versions(package, target, field, value):
    getattr(package, target)[field] = value
    package.save()
    with pytest.raises(ValidationError):
        package.check()


@pytest.mark.parametrize("tag", ["table", "long_code", "prompt_injection", "identifier", "similar_identifiers"])
def test_missing_coverage(package, tag):
    package.corpus["questions"][0]["tags"].remove(tag)
    package.save()
    with pytest.raises(ValidationError, match="coverage"):
        package.check()


@pytest.mark.parametrize("mutation", ["followup", "refusal", "holdout", "tuning", "starter", "partial", "clarify", "conflict"])
def test_coverage_and_behavior(package, mutation):
    qs = package.corpus["questions"]
    if mutation == "followup":
        del qs[1]["previous_question"]
    elif mutation == "refusal":
        qs.pop(4)
    elif mutation == "holdout":
        for q in qs:
            q["split"] = "tuning"
    elif mutation == "tuning":
        for q in qs:
            q["split"] = "holdout"
    elif mutation == "starter":
        qs[0]["question"] = "Другой вопрос"
    elif mutation == "partial":
        del qs[-2]["missing_information"]
    elif mutation == "clarify":
        del qs[-1]["clarification"]
    else:
        qs[0]["evidence"].pop()
        qs[0]["required_facts"][0]["evidence_ids"].pop()
    package.save()
    with pytest.raises(ValidationError):
        package.check()


@pytest.mark.parametrize("field,value", [
    ("page_id", True), ("page_id", 0), ("locale", 2), ("title", None),
    ("source_url", "https://wrong.example"), ("updated_at", "2026-10-05"),
    ("updated_at", "2026-99-99T00:00:00Z"), ("markdown", 42),
    ("content_sha256", "0" * 64),
])
def test_snapshot_contract(package, field, value):
    package.live["documents"][0][field] = value
    package.save()
    with pytest.raises(ValidationError):
        package.check()


def test_duplicate_pages(package):
    package.live["documents"].append(deepcopy(package.live["documents"][0]))
    package.save()
    with pytest.raises(ValidationError, match="duplicate"):
        package.check()


@pytest.mark.parametrize("mutation", ["missing_page", "inventory", "source", "count", "file_bytes", "metadata", "markdown"])
def test_manifest_drift(package, mutation):
    package.save()
    if mutation == "missing_page":
        package.live["documents"].pop()
        package.save_json("live.json", package.live)
    elif mutation == "inventory":
        package.manifest["live"]["documents"][0]["path"] = "wrong"
        package.save_json("manifest.json", package.manifest)
    elif mutation == "source":
        package.manifest["live"]["source"] = "https://wrong.example"
        package.save_json("manifest.json", package.manifest)
    elif mutation == "count":
        package.manifest["live"]["document_count"] = True
        package.save_json("manifest.json", package.manifest)
    elif mutation == "file_bytes":
        package.paths[2].write_bytes(package.paths[2].read_bytes() + b" ")
    else:
        package.live["documents"][0]["title" if mutation == "metadata" else "markdown"] = "Drift"
        package.save_json("live.json", package.live)
    with pytest.raises(ValidationError):
        package.check()


@pytest.mark.parametrize("mutation", ["page", "locale", "hash", "start", "end", "bool", "text", "duplicate", "reference", "command", "prefix"])
def test_evidence_mutations(package, mutation):
    q = package.corpus["questions"][0]
    e = q["evidence"][0]
    span = e["spans"][0]
    if mutation == "page":
        e["page_id"] = 999
    elif mutation == "locale":
        e["locale"] = "en"
    elif mutation == "hash":
        e["content_sha256"] = "0" * 64
    elif mutation == "start":
        span["start"] = -1
    elif mutation == "end":
        span["end"] = 999
    elif mutation == "bool":
        span["start"] = False
    elif mutation == "text":
        span["exact_text"] = "Incorrect quote on correct page"
    elif mutation == "duplicate":
        q["evidence"].append(deepcopy(e))
    elif mutation == "reference":
        q["required_facts"][0]["evidence_ids"] = ["missing"]
    else:
        q["exact_commands"] = ["cmd --wrong" if mutation == "command" else "cmd"]
    package.save()
    with pytest.raises(ValidationError):
        package.check()


def test_unicode_crlf_repeated_quote_offsets(package):
    q = package.corpus["questions"][3]
    doc = package.live["documents"][0]
    markdown = doc["markdown"]
    for start in (markdown.index("Повтор"), markdown.rindex("Повтор")):
        q["evidence"] = [evidence(doc, "e1", start, start + len("Повтор"))]
        package.save()
        assert package.check().questions == 9
    q["evidence"][0]["spans"][0]["start"] -= 1
    package.save()
    with pytest.raises(ValidationError, match="exact_text"):
        package.check()


def test_crlf_not_normalized(package):
    package.corpus["questions"][0]["evidence"][0]["spans"][0]["exact_text"] = package.live["documents"][0]["markdown"].replace("\r\n", "\n")
    package.save()
    with pytest.raises(ValidationError, match="exact_text"):
        package.check()


def test_command_prefix_span_not_full_source_line(package):
    q = package.corpus["questions"][3]
    doc = package.live["documents"][0]
    start = doc["markdown"].index("cmd")
    q["evidence"] = [evidence(doc, "e1", start, start + 3)]
    q["exact_commands"] = ["cmd"]
    package.save()
    with pytest.raises(ValidationError, match="exact_command"):
        package.check()


def test_multiline_command(package):
    q = package.corpus["questions"][3]
    doc = package.live["documents"][0]
    q["exact_commands"] = ["Ж😀\r\ncmd --full"]
    package.save()
    assert package.check().questions == 9


def test_inventory_drift_with_refreshed_fingerprint(package):
    package.save()
    package.live["documents"][0]["path"] = "changed"
    package.live["documents"][0]["source_url"] = "https://live.example/ru/changed"
    package.save_json("live.json", package.live)
    package.manifest["live"]["sha256"] = sha(package.paths[2].read_bytes())
    package.save_json("manifest.json", package.manifest)
    with pytest.raises(ValidationError, match="inventory"):
        package.check()


def test_missing_page_with_consistent_manifest(package):
    package.live["documents"].pop()
    package.save()
    with pytest.raises(ValidationError, match="missing_page"):
        package.check()


def test_refuse_empty_facts_and_answerable_holdout(package):
    package.corpus["questions"][4]["required_facts"] = [{"text": "Invented", "evidence_ids": ["missing"]}]
    package.save()
    with pytest.raises(ValidationError, match="behavior"):
        package.check()


@pytest.mark.parametrize("synthetic", [False, True])
def test_cli_repeatable_read_only_offline(package, synthetic, monkeypatch, capsys):
    if synthetic:
        package.add("synthetic", "Synthetic?", namespace="synthetic")
    package.save(synthetic=synthetic)
    before = {p: p.read_bytes() for p in package.paths}
    for key in list(os.environ):
        if key.startswith(("WIKI_", "PG", "LLM_")):
            monkeypatch.delenv(key)
    assert main(package.argv()) == 0
    first = capsys.readouterr()
    assert main(package.argv()) == 0
    assert capsys.readouterr() == first
    assert {p: p.read_bytes() for p in package.paths} == before
    output = json.loads(first.out)
    assert output["questions"] == (10 if synthetic else 9)
    result = subprocess.run([sys.executable, "-m", "app.evaluation", *package.argv()],
                            text=True, capture_output=True, check=False)
    assert result.returncode == 0 and result.stdout == first.out and not result.stderr


def test_fixtures_required(package, capsys):
    package.add("synthetic", "Synthetic?", namespace="synthetic")
    package.save()
    assert main(package.argv()) == 1
    assert "fixtures:" in capsys.readouterr().err


@pytest.mark.parametrize("raw", [b"questions:\n  - id: q1\n", b"{", b"\xff", b'{"schema_version":1,"schema_version":1}', b'{"schema_version":NaN}'])
def test_bad_format_cli(package, raw, capsys):
    package.save()
    package.paths[0].write_bytes(raw)
    assert main(package.argv()) == 1
    assert "format:" in capsys.readouterr().err


def test_missing_file_safe_diagnostics(package, capsys):
    package.save()
    argv = package.argv()
    argv[1] = str(package.root / "credential-secret-value.yaml")
    assert main(argv) == 1
    err = capsys.readouterr().err
    assert "file: questions" in err and "credential-secret-value" not in err


def test_untrusted_error_values_not_echoed(package, capsys):
    q = package.corpus["questions"][3]
    q["id"] = "password=secret-value\n"
    package.save()
    assert main(package.argv()) == 1
    err = capsys.readouterr().err
    assert "question#4" in err and "secret-value" not in err


def test_missing_cli_option():
    with pytest.raises(SystemExit) as error:
        main([])
    assert error.value.code == 2
