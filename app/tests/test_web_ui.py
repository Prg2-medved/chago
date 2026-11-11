from fastapi.testclient import TestClient
import pytest

from app.main import app


@pytest.mark.parametrize("elsewhere", [False, True])
def test_package_assets_and_app_only(tmp_path, monkeypatch, elsewhere):
    monkeypatch.setenv("INDEX_PATH", str(tmp_path / "missing.sqlite3"))
    monkeypatch.setenv("LLM_BASE_URL", "invalid")
    if elsewhere:
        monkeypatch.chdir(tmp_path)
    with TestClient(app) as client:
        html = client.get("/")
        assert html.status_code == 200 and html.headers["content-type"].startswith("text/html")
        assert html.headers["cache-control"] == "no-store"
        assert "script-src 'self'" in html.headers["content-security-policy"]
        assert 'lang="ru"' in html.text and "Ваш вопрос" in html.text
        assert 'src="/static/app.js"' in html.text and 'href="/static/app.css"' in html.text
        for asset, content_type in (("app.js", "javascript"), ("app.css", "text/css")):
            response = client.get(f"/static/{asset}")
            assert response.status_code == 200 and content_type in response.headers["content-type"]
        for payload in ({}, {"session_id": "test", "message": "question"}):
            response = client.post("/api/chat", json=payload)
            assert response.status_code in (422, 503)
            assert response.headers["cache-control"] == "no-store"
        assert client.get("/health").headers["cache-control"] == "no-store"
    assert not (tmp_path / "missing.sqlite3").exists()
