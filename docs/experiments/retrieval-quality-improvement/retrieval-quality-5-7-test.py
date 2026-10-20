"""Synthetic checks of manual reporting gates; no models/corpus/quality inference."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("manual", Path(__file__).with_name("retrieval-quality-5-7-tools.py"))
manual = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manual)


def runtime_snapshot(mhz, hostname):
    cpuinfo = ("processor : 0\nvendor_id : GenuineIntel\ncpu family : 6\nmodel : 183\n"
               "model name : Intel Core i5-14400\nstepping : 1\nmicrocode : 0x123\n"
               "physical id : 0\ncore id : 0\ncpu cores : 10\nsiblings : 16\n"
               f"cpu MHz : {mhz}\nbogomips : {float(mhz) * 2}\n"
               "flags : sse2 avx2\nfuture diagnostic : changing\n")
    packages = dict(zip(("torch", "transformers", "tokenizers", "sentence-transformers", "numpy", "safetensors"),
                        ("2.7.1+cpu", "4.57.3", "0.22.2", "5.1.2", "2.2.6", "0.8.0")))
    with patch.object(manual.Path, "read_text", return_value=cpuinfo), \
            patch.object(manual, "version", side_effect=packages.__getitem__), \
            patch.object(manual.socket, "gethostname", return_value=hostname):
        return manual.runtime()


def report(arm, repeat=1):
    rows = []
    for label in ("first", "warm"):
        for i in range(10):  # Nine single questions; follow-up excluded from mean.
            pair = {"chunk_id": "chunk", "input_sha256": "input"}
            if arm == "reranker":
                pair["tokens"] = 32
            rows.append({"pass": label, "id": f"q{i:02}", "split": "tuning", "source_set": "live",
                         "answerable": True, "follow_up": i == 9, "union": ["chunk"], "inputs": [pair],
                         "candidates": [{"reranker_score": 0.5, "rrf_score": 0.01}],
                         "final": [], "hit": i != 3, "diagnostics": {},
                         "seconds": 1000 if i == 9 else 1, "semantic_seconds": .1,
                         "lexical_seconds": .01, "rerank_seconds": .5, "tokenization_seconds": .02})
    return {"arm": arm, "repeat": repeat, "rows": rows, "network_attempts": 0,
            "models_resident_together": arm == "reranker", "environment": {"cpu": "same"},
            "environment_diagnostics": {"hostname": str(repeat)},
            "cgroup_after": {"memory.peak": "1234567", "memory.swap.current": "0",
                             "memory.events": "max 0\noom 0\noom_kill 0"}}


class Gates(unittest.TestCase):
    def test_exact_serialized_float(self):
        self.assertFalse(manual.exact({"score": -0.0}, {"score": 0.0}))

    def test_denominator_and_mean_exclude_followup(self):
        self.assertEqual(manual.inspect_report(report("reranker")),
                         {"hits": 8, "count": 9, "warm_mean_seconds": 1})

    def test_reject_nonfinite_changed_scores_oom_swap_network(self):
        changes = (
            lambda r: r["rows"][0]["candidates"][0].update(reranker_score=float("nan")),
            lambda r: r["rows"][0]["candidates"][0].update(reranker_score=.6),
            lambda r: r["cgroup_after"].update({"memory.events": "max 0\noom 1\noom_kill 0"}),
            lambda r: r["cgroup_after"].update({"memory.swap.current": "1"}),
            lambda r: r.update(network_attempts=1),
        )
        for change in changes:
            value = report("reranker")
            change(value)
            with self.subTest(change=change), self.assertRaises(AssertionError):
                manual.inspect_report(value)

    def summarize(self, change=None):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / "data") as directory:
            path = Path(directory)
            for n in (1, 2):
                for arm in manual.ARMS:
                    value = report(arm, n)
                    if change:
                        change(value)
                    manual.write(path / f"{arm}-{n}.json", value)
            manual.write(path / "preflight.json", {"cases": [
                {"id": r["id"], "pairs": r["inputs"]} for r in report("reranker")["rows"] if r["pass"] == "first"]})
            manual.summarize(path, 2, path / "summary.json")
            return json.loads((path / "summary.json").read_text())

    def test_repeated_summary(self):
        result = self.summarize()
        self.assertEqual(result["failures"], [])
        self.assertEqual(len(result["transitions"]), 40)
        self.assertFalse(result["quality_acceptance"])

    def test_dynamic_cpu_frequency_and_hostname_do_not_fail_repeat(self):
        snapshots = {1: runtime_snapshot("800.000", "worker-1"),
                     2: runtime_snapshot("4200.000", "worker-2")}
        self.assertEqual(snapshots[1][0], snapshots[2][0])
        self.assertNotEqual(snapshots[1][1], snapshots[2][1])
        self.assertIn("cpu MHz : 4200.000", snapshots[2][1]["cpuinfo"])
        self.assertNotIn("cpuinfo", snapshots[1][0])
        self.assertNotIn("hostname", snapshots[1][0])
        self.assertNotIn("cpu MHz", snapshots[1][0]["cpu"][0])

        def change(r):
            r["environment"], r["environment_diagnostics"] = snapshots[r["repeat"]]

        self.assertEqual(self.summarize(change)["failures"], [])

    def test_stable_cpu_and_software_changes_still_fail_repeat(self):
        baseline, diagnostics = runtime_snapshot("800.000", "worker")
        changes = (
            lambda e: e["cpu"][0].update({"model": "999"}),
            lambda e: e["cpu"][0].update({"microcode": "0x456"}),
            lambda e: e["cpu"][0].update({"flags": ["sse2"]}),
            lambda e: e["cpu"][0].update({"core id": "1"}),
            lambda e: e["packages"].update({"torch": "different"}),
            lambda e: e.update(python="different"),
            lambda e: e.update(kernel_release="different"),
        )
        for mutate in changes:
            def change(r):
                r["environment"] = deepcopy(baseline)
                r["environment_diagnostics"] = diagnostics
                if r["repeat"] == 2:
                    mutate(r["environment"])
            with self.subTest(mutate=mutate), self.assertRaisesRegex(AssertionError, "environment mismatch"):
                self.summarize(change)

    def test_repeat_mismatch_stops(self):
        def change(r):
            if r["repeat"] == 2:
                for row in r["rows"]:
                    row["candidates"][0]["reranker_score"] = .6
        with self.assertRaisesRegex(AssertionError, "fresh-repeat"):
            self.summarize(change)

    def test_slow_or_low_quality_stops(self):
        for setting in ("slow", "quality"):
            def change(r):
                if r["arm"] == "reranker":
                    for row in r["rows"]:
                        if setting == "slow":
                            row["seconds"] = 3
                        elif row["id"] == "q00":
                            row["hit"] = False
            with self.subTest(setting=setting), self.assertRaises(SystemExit) as error:
                self.summarize(change)
            self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main(testRunner=unittest.TextTestRunner(stream=sys.stdout))
