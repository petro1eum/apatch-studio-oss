import socket

from fastapi.testclient import TestClient

from apatch_studio.app import create_app
from apatch_studio.cli import _loopback_socket_config


class FakeAdapter:
    def overview(self, *, force=False):
        return {"ok": True, "force": force}


def client(tmp_path):
    (tmp_path / "assets").mkdir(exist_ok=True)
    (tmp_path / "assets" / "app.js").write_text("/* test frontend */", encoding="utf-8")
    (tmp_path / "theme-init.js").write_text("/* test theme */", encoding="utf-8")
    (tmp_path / "index.html").write_text(
        '<meta content="__APATCH_STUDIO_SESSION__"><script src="/theme-init.js"></script>'
        '<script src="/assets/app.js"></script>', encoding="utf-8")
    app = create_app(str(tmp_path), adapter=FakeAdapter(), frontend_root=tmp_path)
    return app, TestClient(app, base_url="http://127.0.0.1:8765")


def test_health_is_loopback_only_but_needs_no_session(tmp_path):
    _, studio = client(tmp_path)
    response = studio.get("/api/v1/health")
    assert response.status_code == 200
    assert response.headers["content-security-policy"].startswith("default-src 'self'")
    assert response.headers["cross-origin-opener-policy"] == "same-origin"
    assert response.headers["cross-origin-resource-policy"] == "same-origin"
    assert "camera=()" in response.headers["permissions-policy"]
    assert studio.get("/api/v1/health", headers={"host": "example.com"}).status_code == 400


def test_loopback_socket_config_supports_ipv4_hostname_and_ipv6():
    assert _loopback_socket_config("127.0.0.1", 8765) == (
        socket.AF_INET,
        ("127.0.0.1", 8765),
        "127.0.0.1",
    )
    assert _loopback_socket_config("localhost", 8765) == (
        socket.AF_INET,
        ("localhost", 8765),
        "localhost",
    )
    assert _loopback_socket_config("[::1]", 8765) == (
        socket.AF_INET6,
        ("::1", 8765),
        "[::1]",
    )


def test_non_health_api_requires_process_session(tmp_path):
    app, studio = client(tmp_path)
    assert studio.get("/api/v1/overview").status_code == 401
    response = studio.get(
        "/api/v1/overview",
        headers={"x-apatch-studio-session": app.state.studio_guard.token},
    )
    assert response.status_code == 200


def test_post_requires_exact_same_origin(tmp_path):
    app, studio = client(tmp_path)
    token = app.state.studio_guard.token
    headers = {"x-apatch-studio-session": token, "origin": "http://attacker.invalid"}
    assert studio.post("/api/v1/refresh", headers=headers).status_code == 403

    headers["origin"] = "http://127.0.0.1:8765"
    response = studio.post("/api/v1/refresh", headers=headers)
    assert response.status_code == 200
    assert response.json()["force"] is True
