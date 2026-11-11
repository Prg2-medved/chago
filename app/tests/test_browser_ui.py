"""Optional local real-browser matrix; Node >=22 and a prepared Chromium required."""

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import threading
from time import monotonic, sleep

import pytest
import uvicorn

from app.main import app


def test_browser_matrix(tmp_path, monkeypatch):
    if os.environ.get("RUN_BROWSER_UI") != "1":
        pytest.skip("Opt in with RUN_BROWSER_UI=1 to launch a local headless browser")
    node = shutil.which("node")
    browser = os.environ.get("UI_TEST_BROWSER") or next((str(path) for path in (
        Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
        Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
    ) if path.exists()), None)
    if not node or not browser:
        pytest.skip("Prepared Node >=22 and Chromium required; no browser downloads")
    monkeypatch.setenv("INDEX_PATH", str(tmp_path / "missing.sqlite3"))
    monkeypatch.setenv("LLM_BASE_URL", "invalid")
    # Use the LAN IP to exercise an insecure HTTP origin and session-ID fallback.
    host = socket.gethostbyname(socket.gethostname())
    with socket.socket() as listener:
        listener.bind((host, 0))
        port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = monotonic() + 10
        while not server.started:
            assert thread.is_alive() and monotonic() < deadline, "HTTP server failed to start"
            sleep(.02)
        result = subprocess.run([node, str(Path(__file__).with_name("browser_ui.mjs")), browser,
                                 f"http://{host}:{port}", str(tmp_path / "browser-profile")],
                                capture_output=True, text=True, encoding="utf-8", timeout=90)
        assert result.returncode == 0, result.stdout + result.stderr
        evidence = json.loads(result.stdout)
        print(json.dumps(evidence, ensure_ascii=False, indent=2))
        assert all(item["verdict"] == "PASS" for item in evidence["verdicts"])
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        assert not thread.is_alive()
