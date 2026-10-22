"""Operator harness safety checks; no Docker, model assets or frozen-input writes."""

from contextlib import closing, redirect_stdout
import copy
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("chat_memory_series", ROOT / "docs/grounded-chat-api-memory-series.py")
assert SPEC and SPEC.loader
series = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(series)

BODY = {"answer": "fixture", "insufficient_context": True, "sources": []}


def observation():
    container = {"pid": 12, "started_at": "fixture", "restarts": 0,
                 "cgroup": "/fixture", "events": {"oom": 0, "oom_kill": 0}}
    return {"host_kib": {"MemAvailable": series.THRESHOLD}, "host_oom_kill": 3,
            "containers": {"app": copy.deepcopy(container), "llm": copy.deepcopy(container)}}


class MemorySeriesTests(unittest.TestCase):
    def test_order_preserves_duplicates_and_only_tuning_live(self):
        cases = series.select_cases(ROOT / "eval/questions.yaml")
        expected = "q01 q02 q03 q05 q06 q07 q09 q11 q12 q13 q14 q15 q17 q19 q01 q02 q03 q05 q06 q19".split()
        self.assertEqual([case["id"] for case in cases], expected)
        self.assertEqual(len(cases), 20)
        self.assertNotIn("q18", expected)

    def test_holdout_fails_before_request(self):
        corpus = json.loads((ROOT / "eval/questions.yaml").read_text(encoding="utf-8"))
        corpus["questions"][0]["split"] = "holdout"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "questions.json"
            path.write_text(json.dumps(corpus), encoding="utf-8")
            with self.assertRaisesRegex(series.Stop, "case_metadata"):
                series.select_cases(path)

    def test_memory_threshold_exact_boundary(self):
        row = observation()
        self.assertIsNone(series.stop_reason(row, None, ("app", "llm")))
        row["host_kib"]["MemAvailable"] -= 1
        self.assertEqual(series.stop_reason(row, None, ("app", "llm")), "memory_pressure")

    def test_low_initial_memory_never_touches_docker_or_http(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            with patch.object(series.sys, "argv", ["series", "--app-url", "http://fixture"]), \
                    patch.object(series.sys, "platform", "linux"), \
                    patch.object(series.os, "umask"), \
                    patch.object(series.tempfile, "mkdtemp", return_value=directory), \
                    patch.object(series, "host_memory", return_value={"MemAvailable": series.THRESHOLD - 1}), \
                    patch.object(series, "command") as command, patch.object(series, "http") as transport:
                self.assertEqual(series.main(), 1)
                command.assert_not_called()
                transport.assert_not_called()
            summary = json.loads((Path(directory) / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["reason"], "memory_pressure_before_start")
            self.assertEqual(summary["state"], "incomplete")

    def test_monitor_records_peak_scope_and_detects_new_oom(self):
        app = {"Id": "app", "Config": {"Labels": {"com.docker.compose.project": "fixture"}}}
        llm = {"Id": "llm"}
        values = observation()["containers"]
        for row in values.values():
            row["memory.peak"] = 987654321
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory)
            monitor = series.Monitor(app, llm, report)
            with patch.object(series, "host_memory", return_value={"MemAvailable": series.THRESHOLD}), \
                    patch.object(series, "fields", return_value={"oom_kill": 3}), \
                    patch.object(series, "command", return_value="app\nllm\n"), \
                    patch.object(series, "docker_json", return_value=[app, llm]), \
                    patch.object(series, "cgroup_memory", side_effect=lambda c: copy.deepcopy(values[c["Id"]])):
                baseline = monitor.sample("baseline")
                self.assertEqual(baseline["containers"]["llm"]["memory.peak"], 987654321)
                values["llm"]["events"]["oom_kill"] += 1
                with self.assertRaisesRegex(series.Stop, "new_container_oom"):
                    monitor.sample("during_request", 1)
            self.assertEqual(len((report / "memory.jsonl").read_text().splitlines()), 2)

    def test_host_and_cgroup_oom_and_process_change(self):
        baseline = observation()
        for field in ("host", "cgroup", "process", "inventory"):
            with self.subTest(field=field):
                row = copy.deepcopy(baseline)
                if field == "host":
                    row["host_oom_kill"] += 1
                elif field == "cgroup":
                    row["containers"]["llm"]["events"]["oom_kill"] += 1
                elif field == "process":
                    row["containers"]["llm"]["pid"] += 1
                else:
                    row["containers"]["other"] = {}
                self.assertIsNotNone(series.stop_reason(row, baseline, ("app", "llm")))

    def test_20_http_calls_exact_questions_no_other_endpoint(self):
        cases = series.select_cases(ROOT / "eval/questions.yaml")
        calls = []

        def http(url, payload):
            calls.append((url, payload))
            return 200, BODY

        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()), patch.object(series, "http", http):
            report = Path(directory)
            series.run_series(cases, "http://fixture", Mock(), report)
            self.assertEqual(len(calls), 20)
            self.assertEqual([payload["message"] for _, payload in calls], [case["question"] for case in cases])
            self.assertTrue(all(url == "http://fixture/api/chat" for url, _ in calls))
            rows = [json.loads(line) for line in (report / "requests.jsonl").read_text().splitlines()]
            self.assertEqual([row["event"] for row in rows], ["start", "end"] * 20)

    def test_http_errors_stop_without_next_request_or_retry(self):
        cases = [{"id": "q01", "question": "fixture"}] * 2
        for status in (422, 502, 503, 504):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
                with patch.object(series, "http", return_value=(status, None)) as transport:
                    with self.assertRaisesRegex(series.Stop, "http_" + str(status)):
                        series.run_series(cases, "http://fixture", Mock(), Path(directory))
                    self.assertEqual(transport.call_count, 1)

    def test_socket_failure_stops_without_next_request(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            with patch.object(series, "http", side_effect=TimeoutError) as transport:
                with self.assertRaisesRegex(series.Stop, "client_transport_failure"):
                    series.run_series([{"id": "q01", "question": "fixture"}] * 2,
                                      "http://fixture", Mock(), Path(directory))
                self.assertEqual(transport.call_count, 1)

    def test_pre_request_memory_failure_sends_nothing(self):
        monitor = Mock()
        monitor.sample.side_effect = series.Stop("memory_pressure")
        with tempfile.TemporaryDirectory() as directory, patch.object(series, "http") as transport:
            with self.assertRaisesRegex(series.Stop, "memory_pressure"):
                series.run_series([{"id": "q01", "question": "fixture"}], "http://fixture", monitor, Path(directory))
            transport.assert_not_called()

    def test_memory_stop_does_not_wait_for_http_or_send_next(self):
        release = threading.Event()
        monitor = Mock()
        monitor.sample.side_effect = [None, series.Stop("memory_pressure")]

        def http(*args):
            release.wait(5)
            return 200, BODY

        try:
            with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
                with patch.object(series, "http", side_effect=http) as transport:
                    with self.assertRaisesRegex(series.Stop, "memory_pressure"):
                        series.run_series([{"id": "q01", "question": "fixture"}] * 2,
                                          "http://fixture", monitor, Path(directory))
                    self.assertEqual(transport.call_count, 1)
        finally:
            release.set()

    def test_invalid_api_response_stops(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            with patch.object(series, "http", return_value=(200, {"answer": "fixture"})) as transport:
                with self.assertRaisesRegex(series.Stop, "invalid_api_contract"):
                    series.run_series([{"id": "q01", "question": "fixture"}] * 2,
                                      "http://fixture", Mock(), Path(directory))
                self.assertEqual(transport.call_count, 1)

    def test_index_is_read_only_and_journal_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.sqlite3"
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("CREATE TABLE snapshot_metadata (singleton, source)")
                connection.execute("INSERT INTO snapshot_metadata VALUES (1, 'fixture')")
                connection.execute("CREATE TABLE reindex_metadata (singleton, indexed_at)")
                connection.execute("INSERT INTO reindex_metadata VALUES (1, 'fixture')")
                connection.execute("CREATE TABLE documents (page_id, locale, path, content_sha256)")
                connection.commit()
            digest = series.sha(path)
            self.assertEqual(series.index_identity(path)["sha256"], digest)
            self.assertEqual(series.sha(path), digest)
            Path(str(path) + "-wal").touch()
            with self.assertRaisesRegex(series.Stop, "journal"):
                series.index_identity(path)

    def test_logs_keep_numeric_metrics_without_prompt_or_sources(self):
        logs = ("2026-10-22T12:54:18Z prompt eval time = 20.0 ms / 42 tokens SENTINEL_SOURCE\n"
                "2026-10-22T12:54:19Z prompt done n_tokens = 100 SENTINEL_PROMPT\n"
                "2026-10-22T12:54:20Z SENTINEL_CREDENTIAL\n")
        rows = series.metric_rows("llm", logs)
        self.assertEqual(len(rows), 2)
        self.assertNotIn("SENTINEL", json.dumps(rows))
        self.assertEqual(rows[0]["values"]["tokens"], "42")
        self.assertEqual(rows[1]["values"]["n_tokens"], "100")

    def test_no_http_redirect_or_proxy(self):
        opener = Mock()
        opener.open.side_effect = series.HTTPError("http://fixture", 302, "redirect", {}, None)
        with patch.object(series, "build_opener", return_value=opener) as build:
            self.assertEqual(series.http("http://fixture"), (302, None))
            self.assertEqual(opener.open.call_count, 1)
            self.assertEqual(build.call_args.args[0].proxies, {})
            self.assertIsInstance(build.call_args.args[1], series.NoRedirect)

    def test_pressure_cleanup_verifies_old_process_stopped(self):
        llm = {"Id": "fixture"}
        with tempfile.TemporaryDirectory() as directory, patch.object(series, "command") as command:
            with patch.object(series, "docker_json", return_value=[{"State": {"Running": False, "Pid": 0}}]), \
                    patch.object(series, "inspect_summary", return_value={}):
                series.stop_llm(llm, Path(directory))
                command.assert_called_once_with("docker", "stop", "--time", "10", "fixture", timeout=25)
            with patch.object(series, "docker_json", return_value=[{"State": {"Running": True, "Pid": 12}}]), \
                    patch.object(series, "inspect_summary", return_value={}):
                with self.assertRaisesRegex(series.Stop, "not_confirmed"):
                    series.stop_llm(llm, Path(directory))


if __name__ == "__main__":
    unittest.main()
