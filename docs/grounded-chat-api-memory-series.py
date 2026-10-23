#!/usr/bin/env python3
"""Operator gate 7.6, Linux host + Docker CLI, Python standard library only.

No LLM probes/completions, retries, builds, downloads or restarts. On memory
pressure only, stop the existing LLM container and verify it has stopped.
"""

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


ORDER = "q01 q02 q03 q05 q06 q07 q09 q11 q12 q13 q14 q15 q17 q19 q01 q02 q03 q05 q06 q19".split()
CACHE_RAM_ZERO_ORDER = "q01 q02 q01 q02".split()
THRESHOLD = 2097152  # KiB, host MemAvailable; conservative, not an OOM guarantee.
DIGEST = "ghcr.io/ggml-org/llama.cpp@sha256:f9115c95639e60abc09d4ea83b26fd4d56c66aa1174594393335a514da00c283"
MODEL_HASH = "2fde00ce69dd4899c70d020845e2638353015bba0fdf161b3eb965f2bca4464e"
CODE = ("grounding.py", "chat.py", "chat_api.py", "llm_client.py", "config.py",
        "retrieval.py", "index_state.py", "__main__.py", "main.py")
SETTING_NAMES = ("LLM_BASE_URL", "LLM_MODEL_NAME", "LLM_MAX_TOKENS", "LLM_CONTEXT_SIZE",
                 "LLM_TIMEOUT_SECONDS", "RETRIEVAL_SEMANTIC_CANDIDATES", "RETRIEVAL_LEXICAL_CANDIDATES",
                 "RETRIEVAL_RRF_CONSTANT", "RETRIEVAL_TOP_K", "EMBEDDING_MODEL_PATH", "EMBEDDING_MODEL_ID",
                 "EMBEDDING_MODEL_REVISION", "EMBEDDING_BATCH_SIZE", "EMBEDDING_CPU_THREADS")
CHAT_IDENTITY = {"model_name": "Qwen3-4B-Instruct-2507", "context_size": 8192,
                 "max_tokens": 768, "timeout_seconds": 300}
CHAT_ENV_NAMES = ("LLM_MODEL_NAME", "LLM_CONTEXT_SIZE", "LLM_MAX_TOKENS", "LLM_TIMEOUT_SECONDS")
LLM_COMMAND = ["--model", "/models/model.gguf", "--alias", "Qwen3-4B-Instruct-2507", "--host", "0.0.0.0",
               "--port", "8080", "--ctx-size", "8192", "--threads", "8", "--threads-batch", "8",
               "--parallel", "1", "--gpu-layers", "0", "--device", "none", "--no-webui"]


class Stop(ValueError):
    """Controlled diagnostic without credentials, documents or raw exceptions."""


def utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def command(*args: str, timeout: float = 15) -> str:
    try:
        return subprocess.run(args, check=True, capture_output=True, text=True,
                              timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        raise Stop("command_failed:" + args[0]) from None


def docker_json(*args: str) -> Any:
    return json.loads(command("docker", *args))


def check_code_identity(app_id: str, report: Path) -> dict[str, str]:
    expected = {name: sha(Path("app/app") / name) for name in CODE}
    remote = json.loads(command(
        "docker", "exec", app_id, "python", "-c",
        "import app,hashlib,json,pathlib; p=pathlib.Path(app.__file__).parent; "
        "print(json.dumps({n:hashlib.sha256((p/n).read_bytes()).hexdigest() "
        "if (p/n).is_file() else None for n in " + repr(CODE) + "}))"))
    mismatches = [name for name in CODE if remote.get(name) != expected[name]]
    write_json(report / "code-check.json", {"expected": expected, "deployed": remote, "mismatches": mismatches})
    if mismatches:
        raise Stop("deployed_code_differs_from_checkout:" + ",".join(mismatches))
    return expected


def check_chat_identity(app_id: str, env: dict[str, str], report: Path) -> dict[str, Any]:
    """Read effective values through the deployed app's own loader, without LLM calls."""
    diagnostic = {"explicit_env": {key: env.get(key) for key in CHAT_ENV_NAMES},
                  "expected": CHAT_IDENTITY}
    write_json(report / "settings-check.json", diagnostic)
    try:
        effective = json.loads(command(
            "docker", "exec", app_id, "python", "-c",
            "import json; from app.config import load_chat_settings; s=load_chat_settings(); "
            "print(json.dumps({k:getattr(s,k) for k in " + repr(tuple(CHAT_IDENTITY)) + "}))"))
    except Stop:
        raise Stop("effective_settings_unavailable") from None
    mismatches = [key for key, value in CHAT_IDENTITY.items() if effective.get(key) != value]
    diagnostic.update(effective=effective, mismatches=mismatches)
    write_json(report / "settings-check.json", diagnostic)
    if mismatches:
        raise Stop("settings_identity_mismatch:" + ",".join(mismatches))
    return effective


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append(path: Path, value: Any) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False) + "\n")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fields(path: Path) -> dict[str, int]:
    return {parts[0].rstrip(":"): int(parts[1])
            for line in path.read_text().splitlines()
            if len(parts := line.split()) >= 2 and parts[1].isdigit()}


def host_memory() -> dict[str, int]:
    values = fields(Path("/proc/meminfo"))
    return {key: values[key] for key in ("MemAvailable", "SwapTotal", "SwapFree")}


def select_cases(path: Path, order: list[str] = ORDER) -> list[dict[str, Any]]:
    corpus = json.loads(path.read_text(encoding="utf-8"))
    selected = {case["id"]: case for case in corpus["questions"] if case["id"] in order}
    if set(selected) != set(order) or any(
        case["split"] != "tuning" or case["source_set"] != "live" for case in selected.values()
    ):
        raise Stop("case_metadata_mismatch")
    # The approved order includes q09 (tagged follow_up). Send only its original
    # question as one stateless request; never add previous_turns/history or claim
    # follow-up acceptance from this resource measurement.
    return [selected[case_id] for case_id in order]


def check_llm_command(llm: dict[str, Any], cache_ram_zero: bool) -> None:
    # Owner-approved MVP argv; the four-request experiment uses the same flags.
    expected = LLM_COMMAND + ["--cache-ram", "0"]
    if llm["Config"]["Cmd"] != expected or any(llm["NetworkSettings"]["Ports"].values()):
        raise Stop("llm_flags_or_ports_mismatch")
    if cache_ram_zero:
        actual = Path(f"/proc/{llm['State']['Pid']}/cmdline").read_bytes().decode().rstrip("\0").split("\0")
        if actual[-len(expected):] != expected:
            raise Stop("llm_process_flags_mismatch")


def bound_path(container: dict[str, Any], target: str) -> Path:
    target_path = Path(target)
    for mount in sorted(container["Mounts"], key=lambda item: len(item["Destination"]), reverse=True):
        try:
            suffix = target_path.relative_to(mount["Destination"])
        except ValueError:
            continue
        if mount["Type"] != "bind":
            raise Stop("bind_mount_required")
        return Path(mount["Source"]) / suffix
    raise Stop("bind_mount_missing")


def index_identity(path: Path) -> dict[str, Any]:
    if not path.is_file() or any(Path(str(path) + suffix).exists() for suffix in ("-wal", "-journal")):
        raise Stop("index_missing_or_has_journal")
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = sorted({"snapshot_metadata", "reindex_metadata", "documents"} - tables)
        if missing:
            raise Stop("index_missing_tables:" + ",".join(missing))
        metadata = connection.execute("SELECT * FROM snapshot_metadata").fetchall()
        reindex = connection.execute("SELECT * FROM reindex_metadata").fetchall()
        documents = connection.execute("SELECT page_id, locale, path, content_sha256 FROM documents ORDER BY page_id").fetchall()
    stat = path.stat()
    return {"path": str(path), "sha256": sha(path), "device": stat.st_dev,
            "inode": stat.st_ino, "snapshot_metadata": metadata, "reindex_metadata": reindex,
            "documents": documents}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def http(url: str, payload: dict[str, str] | None = None, timeout: float = 900) -> tuple[int, Any]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=timeout) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        # Do not follow redirects, retry or echo potentially sensitive error text.
        return error.code, None


def valid_response(body: Any) -> bool:
    return (isinstance(body, dict) and set(body) == {"answer", "insufficient_context", "sources"}
            and isinstance(body["answer"], str) and type(body["insufficient_context"]) is bool
            and isinstance(body["sources"], list) and all(
                isinstance(source, dict) and set(source) == {"title", "heading", "url", "quote"}
                and all(isinstance(value, str) for value in source.values()) for source in body["sources"]))


def inspect_summary(container: dict[str, Any]) -> dict[str, Any]:
    return {"id": container["Id"], "image": container["Image"],
            "state": {key: container["State"][key] for key in
                      ("Status", "Running", "Pid", "OOMKilled", "ExitCode", "StartedAt", "FinishedAt")},
            "restarts": container["RestartCount"], "command": container["Config"]["Cmd"],
            "memory_limit": container["HostConfig"]["Memory"], "swap_limit": container["HostConfig"]["MemorySwap"]}


def cgroup_memory(container: dict[str, Any]) -> dict[str, Any]:
    pid = container["State"]["Pid"]
    if not container["State"]["Running"] or not pid:
        raise Stop("container_not_running")
    entries = Path(f"/proc/{pid}/cgroup").read_text().splitlines()
    unified = next((line[3:] for line in entries if line.startswith("0::")), None)
    if unified is None:
        raise Stop("cgroup_v2_required")
    root = Path("/sys/fs/cgroup").resolve()
    path = (root / unified.lstrip("/")).resolve()
    if not path.is_relative_to(root):
        raise Stop("invalid_cgroup_path")
    result = {"pid": pid, "started_at": container["State"]["StartedAt"],
              "restarts": container["RestartCount"], "cgroup": str(path),
              "memory_current_bytes": int((path / "memory.current").read_text()),
              "events": fields(path / "memory.events"), "stat": fields(path / "memory.stat"),
              "process_status_kib": {key: value for key, value in fields(Path(f"/proc/{pid}/status")).items()
                                     if key in {"VmRSS", "VmHWM", "RssAnon", "RssFile", "VmSwap"}}}
    for filename in ("memory.peak", "memory.swap.current", "memory.swap.peak", "pids.current"):
        counter = path / filename
        result[filename] = int(counter.read_text()) if counter.exists() else None
    return result


class Monitor:
    def __init__(self, app: dict[str, Any], llm: dict[str, Any], report: Path) -> None:
        self.app, self.llm, self.report = app, llm, report
        self.project = app["Config"]["Labels"]["com.docker.compose.project"]
        self.baseline: dict[str, Any] | None = None
        self.previous_sample: float | None = None

    def sample(self, phase: str, request_number: int | None = None) -> dict[str, Any]:
        started = time.monotonic()
        row: dict[str, Any] = {"utc": utc(), "monotonic": started, "phase": phase, "request": request_number,
               "host_kib": host_memory(), "host_oom_kill": fields(Path("/proc/vmstat"))["oom_kill"],
               "harness_status_kib": {key: value for key, value in fields(Path("/proc/self/status")).items()
                                      if key in {"VmRSS", "VmHWM", "VmSwap"}}, "containers": {}}
        # Save the host threshold before Docker operations, even if Docker fails.
        if row["host_kib"]["MemAvailable"] < THRESHOLD:
            append(self.report / "memory.jsonl", row)
            raise Stop("memory_pressure")
        ids = set(command("docker", "ps", "-q", "--no-trunc", "--filter",
                          "label=com.docker.compose.project=" + self.project).split())
        ids.update((self.app["Id"], self.llm["Id"]))
        for container in docker_json("inspect", *sorted(ids)):
            row["containers"][container["Id"]] = cgroup_memory(container)
        row["sample_duration_s"] = time.monotonic() - started
        row["sample_gap_s"] = started - self.previous_sample if self.previous_sample is not None else None
        append(self.report / "memory.jsonl", row)
        reason = stop_reason(row, self.baseline, (self.app["Id"], self.llm["Id"]))
        if reason:
            raise Stop(reason)
        if row["sample_duration_s"] > 1 or (row["sample_gap_s"] is not None and row["sample_gap_s"] > 2):
            raise Stop("telemetry_gap")
        self.previous_sample = started
        if self.baseline is None:
            self.baseline = row
        return row


def stop_reason(row: dict[str, Any], baseline: dict[str, Any] | None,
                required: tuple[str, str]) -> str | None:
    if row["host_kib"]["MemAvailable"] < THRESHOLD:
        return "memory_pressure"
    if baseline is None:
        return None
    if row["host_oom_kill"] > baseline["host_oom_kill"]:
        return "new_host_oom"
    if set(row["containers"]) != set(baseline["containers"]):
        return "container_inventory_changed"
    for container_id in required:
        now, before = row["containers"][container_id], baseline["containers"][container_id]
        if any(now[key] != before[key] for key in ("pid", "started_at", "restarts", "cgroup")):
            return "process_changed"
        if any(now["events"].get(key, 0) > before["events"].get(key, 0)
               for key in ("oom", "oom_kill", "oom_group_kill")):
            return "new_container_oom"
    return None


def metric_rows(service: str, logs: str) -> list[dict[str, Any]]:
    rows = []
    for line in logs.splitlines():
        values = {}
        if service == "app" and "chat " in line:
            values = dict(re.findall(r"\b(query_ms|retrieval_ms|wait_ms|generation_ms)=([0-9.]+)", line))
            outcome = re.search(r"\boutcome=(ok|generation_uncertain|[a-z_]+)\b", line)
            if outcome:
                values["outcome"] = outcome[1]
        elif service == "llm":
            timing = re.search(r"\b(prompt eval|eval|total) time\s*=\s*([0-9.]+) ms(?:\s*/\s*(\d+) tokens)?", line)
            if timing:
                values = {"kind": timing[1], "ms": timing[2], "tokens": timing[3]}
            elif "prompt done" in line:
                values = dict(re.findall(r"\b(n_tokens|n_past|n_prompt_tokens|n_cached_tokens)\s*=\s*(\d+)", line))
        if values:
            rows.append({"service": service, "utc": line.split()[0], "values": values})
    return rows


def stop_llm(llm: dict[str, Any], report: Path) -> None:
    command("docker", "stop", "--time", "10", llm["Id"], timeout=25)
    state = docker_json("inspect", llm["Id"])[0]
    write_json(report / "llm-stopped.json", inspect_summary(state))
    if state["State"]["Running"] or state["State"]["Pid"] != 0:
        raise Stop("llm_stop_not_confirmed")


def run_series(cases: list[dict[str, Any]], base_url: str, monitor: Monitor, report: Path) -> None:
    for number, case in enumerate(cases, 1):
        monitor.sample("before_request", number)
        row = {"request": number, "case_id": case["id"], "started_at": utc()}
        append(report / "requests.jsonl", {**row, "event": "start"})
        print(f"{number}/{len(cases)} {case['id']} started", flush=True)
        done: queue.Queue[tuple[int, Any] | None] = queue.Queue()

        def send() -> None:
            try:
                done.put(http(base_url + "/api/chat", {"session_id": "memory-series", "message": case["question"]}))
            except Exception:
                done.put(None)

        # A daemon transport allows immediate stop on memory pressure. Abandoning
        # this client does not prove that the app/LLM has stopped generation.
        began = time.monotonic()
        threading.Thread(target=send, daemon=True).start()
        tick = began + 1
        while True:
            try:
                response = done.get(timeout=max(0, tick - time.monotonic()))
                break
            except queue.Empty:
                now = time.monotonic()
                monitor.sample("during_request", number)
                if now - tick > 1:
                    raise Stop("telemetry_gap")
                tick += 1
        row.update(ended_at=utc(), total_ms=(time.monotonic() - began) * 1000,
                   event="end", status=response[0] if response else None)
        append(report / "requests.jsonl", row)
        if response is None:
            raise Stop("client_transport_failure")
        write_json(report / f"response-{number:02d}-{case['id']}.json", response[1])
        monitor.sample("post_response", number)
        if response[0] != 200:
            raise Stop("http_" + str(response[0]))
        if not valid_response(response[1]):
            raise Stop("invalid_api_contract")
        print(f"{number}/{len(cases)} {case['id']} HTTP 200, {row['total_ms'] / 1000:.1f}s", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-url", required=True, help="Existing host-published app origin")
    parser.add_argument("--preflight-only", action="store_true", help="Check identity/readiness/baseline without chat requests")
    parser.add_argument("--cache-ram-zero-experiment", action="store_true",
                        help="Require --cache-ram 0; only q01/q02/q01/q02, then 10 seconds of idle telemetry; never gate 7.6 pass")
    args = parser.parse_args()
    parsed = urlsplit(args.app_url)
    if (parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        parser.error("--app-url must be a plain HTTP origin without credentials")
    if sys.platform != "linux":
        parser.error("Run on the Linux Docker host from the project root")
    os.umask(0o077)
    report = Path(tempfile.mkdtemp(prefix="grounded-chat-api-memory.", dir="data")).resolve()
    print(f"Reports: {report}", flush=True)
    since = utc()
    llm = app = index_path = before_index = None
    order = CACHE_RAM_ZERO_ORDER if args.cache_ram_zero_experiment else ORDER
    verdict = {"state": "incomplete", "manual_review_required": True, "order": order,
               "cache_ram_zero_experiment": args.cache_ram_zero_experiment,
               "started_at": since, "stop_threshold_kib": THRESHOLD, "sample_interval_s": 1}
    stage = "host_memory"
    try:
        if host_memory()["MemAvailable"] < THRESHOLD:
            raise Stop("memory_pressure_before_start")
        stage = "case_selection"
        cases = select_cases(Path("eval/questions.yaml"), order)
        stage = "container_inspect"
        app_id = command("docker", "compose", "ps", "-q", "app").strip()
        llm_id = command("docker", "compose", "ps", "-q", "llm").strip()
        if not app_id or not llm_id:
            raise Stop("running_app_and_llm_required")
        app, llm = docker_json("inspect", app_id, llm_id)
        stage = "deployed_code"
        code_hashes = check_code_identity(app_id, report)
        stage = "chat_settings"
        env = dict(item.split("=", 1) for item in app["Config"]["Env"])
        settings = {key: value for key, value in env.items() if key in SETTING_NAMES}
        effective_chat_settings = check_chat_identity(app_id, env, report)
        stage = "llm_image_and_model"
        digests = docker_json("image", "inspect", llm["Image"])[0]["RepoDigests"]
        if DIGEST not in digests or sha(bound_path(llm, "/models/model.gguf")) != MODEL_HASH:
            raise Stop("llm_identity_mismatch")
        stage = "llm_flags_and_ports"
        check_llm_command(llm, args.cache_ram_zero_experiment)
        stage = "index_path"
        index_path = bound_path(app, env["INDEX_PATH"])
        stage = "index_metadata"
        before_index = index_identity(index_path)
        stage = "frozen_manifest"
        manifest = json.loads(Path("eval/manifest.json").read_text(encoding="utf-8"))["live"]
        expected_documents = sorted((doc["page_id"], doc["locale"], doc["path"], doc["content_sha256"])
                                    for doc in manifest["documents"])
        if (before_index["documents"] != expected_documents
                or before_index["snapshot_metadata"][0][1] != manifest["source"]):
            raise Stop("app_index_is_not_frozen_live_corpus")
        stage = "identity_report"
        write_json(report / "identity-before.json", {
            "app": inspect_summary(app), "llm": inspect_summary(llm), "settings": settings,
            "effective_chat_settings": effective_chat_settings,
            "image_digests": digests, "model_sha256": MODEL_HASH, "code_sha256": code_hashes,
            "index": before_index, "questions_sha256": sha(Path("eval/questions.yaml")),
            "manifest_sha256": sha(Path("eval/manifest.json")), "harness_sha256": sha(Path(__file__)),
            "required_operator_preconditions": "No uncertain generation, other traffic or index replacement since app start"})
        stage = "app_readiness"
        if http(args.app_url.rstrip("/") + "/health", timeout=5) != (200, {"status": "ok"}):
            raise Stop("app_not_ready")
        stage = "llm_readiness"
        readiness = command("docker", "exec", app_id, "python", "-c",
                            "import urllib.request; print(urllib.request.build_opener(urllib.request.ProxyHandler({})).open('http://llm:8080/health',timeout=5).read().decode())")
        if json.loads(readiness) != {"status": "ok"}:
            raise Stop("llm_not_ready")
        stage = "baseline_telemetry"
        monitor = Monitor(app, llm, report)
        monitor.sample("baseline")
        if args.preflight_only:
            verdict["state"] = "preflight_passed_no_chat"
        else:
            stage = "memory_series"
            run_series(cases, args.app_url.rstrip("/"), monitor, report)
            if args.cache_ram_zero_experiment:
                stage = "post_series_idle"
                for _ in range(10):
                    time.sleep(1)
                    monitor.sample("post_series_idle")
            stage = "final_telemetry"
            monitor.sample("final")
            verdict["state"] = ("4_responses_experiment_review_pending" if args.cache_ram_zero_experiment
                                else "20_responses_completed_review_pending")
    except (Stop, OSError, ValueError, KeyError, sqlite3.Error) as error:
        reason = str(error) if isinstance(error, Stop) else stage + ":" + type(error).__name__
        verdict["reason"] = reason
        verdict["failure_stage"] = stage
        verdict["exception_type"] = type(error).__name__
        print("STOP: " + reason + ". No retry or next completion.", flush=True)
        if llm and reason in {"memory_pressure", "new_host_oom", "new_container_oom"}:
            try:
                stop_llm(llm, report)
                verdict["llm_stop_confirmed"] = True
            except Stop:
                verdict["llm_stop_confirmed"] = False
                print("LLM stop not confirmed; operator must stop it and verify PID=0.", flush=True)
    except KeyboardInterrupt:
        verdict["reason"] = "operator_interrupt_generation_may_continue"
        print("Interrupted; do not retry. Client cancellation does not stop server generation.", flush=True)
    finally:
        if app and llm:
            try:
                # Docker forwards stdout and stderr separately; collect both.
                metrics = []
                for name, container in (("app", app), ("llm", llm)):
                    result = subprocess.run(["docker", "logs", "--timestamps", "--since", since, container["Id"]],
                                            capture_output=True, text=True, timeout=15, check=True)
                    metrics.extend(metric_rows(name, result.stdout + "\n" + result.stderr))
                write_json(report / "metrics.json", metrics)
                verdict["counts_and_timings_need_manual_correlation"] = True
                verdict["llm_numeric_metrics_present"] = any(item["service"] == "llm" for item in metrics)
                verdict["app_numeric_metrics_present"] = any(item["service"] == "app" for item in metrics)
                write_json(report / "containers-after.json", [inspect_summary(item) for item in
                           docker_json("inspect", app["Id"], llm["Id"])])
            except (OSError, Stop, subprocess.SubprocessError):
                verdict["metrics_or_final_state_missing"] = True
        if index_path and before_index:
            try:
                after = index_identity(index_path)
                write_json(report / "index-after.json", after)
                verdict["index_unchanged"] = after == before_index
            except (OSError, Stop, sqlite3.Error):
                verdict["index_unchanged"] = False
        verdict["ended_at"] = utc()
        write_json(report / "summary.json", verdict)
        print(f"Reports: {report}\nState: {verdict['state']}; gate 7.6 remains open pending review.", flush=True)
    return 0 if verdict["state"] in {"20_responses_completed_review_pending", "preflight_passed_no_chat",
                                      "4_responses_experiment_review_pending"} else 1


if __name__ == "__main__":
    sys.exit(main())
