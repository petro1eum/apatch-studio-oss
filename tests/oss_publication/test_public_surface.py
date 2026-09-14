from __future__ import annotations

from pathlib import Path

from apatch_studio.app import create_app


ROOT = Path(__file__).resolve().parents[2]
PROHIBITED_PREFIXES = ("/api/v1/pro", "/api/v1/fleet", "/api/v1/local-team")


class _Adapter:
    def overview(self, *, force: bool = False) -> dict[str, object]:
        return {"schema": "apatch.studio.workspace-overview.v1", "force": force}


class _Runs:
    def close(self) -> None:
        pass


def test_oss_backend_has_no_private_control_plane_routes(tmp_path: Path) -> None:
    app = create_app(
        str(tmp_path),
        adapter=_Adapter(),
        run_manager=_Runs(),
        frontend_root=ROOT / "frontend/dist",
    )
    paths = {route.path for route in app.routes}
    assert not [path for path in paths if path.startswith(PROHIBITED_PREFIXES)]


def test_compiled_client_has_no_private_navigation_or_api(tmp_path: Path) -> None:
    distribution = ROOT / "frontend/dist"
    assert (distribution / "index.html").is_file()
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in distribution.rglob("*")
        if path.is_file() and path.suffix in {".html", ".js", ".css"}
    )
    for prefix in PROHIBITED_PREFIXES:
        assert prefix not in source
    navigation = (ROOT / "frontend/src/navigation.contract.json").read_text(encoding="utf-8")
    assert '"availability": "pro"' not in navigation
    assert '"id": "team"' not in navigation
    assert '"id": "fleet"' not in navigation
