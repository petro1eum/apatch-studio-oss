from pathlib import Path

from fastapi.testclient import TestClient

from apatch_studio.app import create_app
from apatch_studio.project_documents import (
    InvalidProjectDocumentId,
    ProjectDocumentNotFound,
)


class FakeAdapter:
    def overview(self, *, force=False):
        return {"schema": "test", "force": force}

    def document_catalog(self):
        return {
            "schema": "apatch.studio.project-plans.v1",
            "count": 1,
            "items": [{"id": "RFP-011", "title": "Readable plans"}],
        }

    def document_detail(self, document_id):
        if document_id == "BAD_ID":
            raise InvalidProjectDocumentId(document_id)
        if document_id == "RFP-999":
            raise ProjectDocumentNotFound(document_id)
        return {
            "schema": "apatch.studio.project-document.v1",
            "id": document_id,
            "title": "Readable plans",
            "sections": [],
        }


def _client(tmp_path: Path):
    app = create_app(str(tmp_path), adapter=FakeAdapter(), frontend_root=tmp_path)
    return TestClient(app, base_url="http://127.0.0.1:8765"), {
        "x-apatch-studio-session": app.state.studio_guard.token,
        "origin": "http://127.0.0.1:8765",
    }


def test_document_api_is_session_guarded_and_accepts_only_canonical_ids(tmp_path: Path) -> None:
    client, headers = _client(tmp_path)

    assert client.get("/api/v1/documents").status_code == 401
    catalog = client.get("/api/v1/documents", headers=headers)
    detail = client.get("/api/v1/documents/RFP-011", headers=headers)

    assert catalog.status_code == 200
    assert catalog.json()["items"][0]["title"] == "Readable plans"
    assert detail.status_code == 200
    assert detail.json()["id"] == "RFP-011"
    assert client.get("/api/v1/documents/BAD_ID", headers=headers).status_code == 400
    assert client.get("/api/v1/documents/RFP-999", headers=headers).status_code == 404


def test_document_api_has_no_arbitrary_path_or_external_resource_surface(tmp_path: Path) -> None:
    client, headers = _client(tmp_path)

    response = client.get("/api/v1/documents/%2E%2E%2FREADME.md", headers=headers)

    assert response.status_code in {400, 404}
    routes = {
        route.path
        for route in client.app.routes
        if route.path.startswith("/api/v1/documents")
    }
    assert routes == {"/api/v1/documents", "/api/v1/documents/{document_id}"}
