import base64
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from apatch_studio.edition import StudioEdition, product_projection
from apatch_studio.execution_intents import (
    ExecutionIntentConfirmation,
    ExecutionIntentError,
    ExecutionIntentManager,
    ExecutionIntentTrust,
)

ROOT = Path(__file__).resolve().parents[2]
TRUSTED_ORIGIN = "https://trust-chain.ai"
PUBLIC_KEY = "ebVWLo_mVPlAeLES6KmLp5AfhTrmlb7X4OORC60ElmQ"
KEY_ID = "ed25519:sha256:65b60673d6ed884bf01c2c222d82ada0740f29ac3355d6a925c81f17f47a27b8"


class FakeRuns:
    def __init__(self, events=None):
        self.started = []
        self.events = events

    def runners(self):
        return [{"id": "codex", "label": "Codex", "available": True}]

    def start(self, request, *, retry_of=None, execution_context=None):
        record = {
            "run_id": "apr_" + "1" * 32,
            "request": request,
            "execution_context": execution_context,
        }
        self.started.append(record)
        if self.events is not None:
            self.events.append(("run", record["run_id"]))
        return {"run_id": record["run_id"], "status": "queued"}


def fixture() -> bytes:
    return (ROOT / "tests/fixtures/execution_intent.json").read_bytes().rstrip(b"\n")


def trust() -> ExecutionIntentTrust:
    raw_key = base64.urlsafe_b64decode(PUBLIC_KEY + "=")
    assert KEY_ID == "ed25519:sha256:" + hashlib.sha256(raw_key).hexdigest()
    return ExecutionIntentTrust.from_document(
        {
            "schema": "apatch.studio.execution-intent-trust.v1",
            "trusted_origins": [TRUSTED_ORIGIN],
            "keys": [{"key_id": KEY_ID, "public_key": PUBLIC_KEY}],
        }
    )


def test_verified_import_has_no_local_effect_until_owner_confirmation(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runs = FakeRuns()
    manager = ExecutionIntentManager(
        workspace,
        run_manager=runs,
        trust=trust(),
        state_root=tmp_path / "state",
        clock=lambda: datetime(2026, 8, 31, 12, 2, tzinfo=timezone.utc),
    )

    preview = manager.import_raw(fixture())
    assert preview["status"] == "awaiting_local_confirmation"
    assert preview["can_confirm"] is True
    assert runs.started == []

    confirmation = ExecutionIntentConfirmation(
        confirmed=True,
        workspace_id=manager.workspace_id,
        runner_id="codex",
    )
    confirmed = manager.confirm(preview["intent_id"], confirmation)
    assert confirmed["status"] == "consumed"
    assert confirmed["cowork"]["required"] is False
    assert confirmed["cowork"]["status"] == "local_only"
    assert len(runs.started) == 1

    with pytest.raises(ExecutionIntentError, match="current state"):
        manager.confirm(preview["intent_id"], confirmation)
    assert len(runs.started) == 1






class GatewayDomain:
    @staticmethod
    def governed_work_root(target_dir):
        return Path(target_dir) / ".apatch" / "governed_work"

    @staticmethod
    def document_hash(document):
        unsigned = {key: value for key, value in document.items() if key != "signature"}
        raw = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
        return "sha256:" + hashlib.sha256(raw).hexdigest()

    @staticmethod
    def load_project_source_binding(target_dir, binding_id):
        path = (
            GatewayDomain.governed_work_root(target_dir)
            / "bindings"
            / f"{binding_id}.json"
        )
        return json.loads(path.read_text(encoding="utf-8"))


class GatewayKeyProvider:
    def __init__(self, public_key=b"g" * 32):
        self.public_key = public_key

    def get_public_key(self):
        return self.public_key


class GatewayIdentity:
    def __init__(self, provider= None):
        self.key_provider = provider or GATEWAY_PROVIDER


GATEWAY_PROVIDER = GatewayKeyProvider()
GATEWAY_KEY_ID = "sha256:" + hashlib.sha256(
    GATEWAY_PROVIDER.get_public_key()
).hexdigest()


def gateway_identity_loader(_target_dir):
    return GatewayIdentity()


class GatewayDelivery:
    @staticmethod
    def config_path(target_dir):
        return Path(target_dir) / ".apatch" / "governed_work.json"

    @staticmethod
    def load_config(target_dir):
        return {
            "binding_authority_keys": {"platform:key": "public"},
            "service_request_key_id": GATEWAY_KEY_ID,
        }


class GatewayWorkItemAcceptance:
    @staticmethod
    def validate_binding(document, *, trusted_keys):
        assert trusted_keys == {"platform:key": "public"}
        return document


class GatewayApi:
    def __init__(self, _workspace):
        self.events = []


@pytest.fixture
def signed_inbox(tmp_path, monkeypatch):
    import httpx
    from types import SimpleNamespace
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from apatch import governed_work as G, governed_work_mcp as M, work_item_acceptance as W
    from apatch import governed_work_transport as T
    from apatch_studio.governed_work_gateway import APatchGovernedWorkGateway

    class Signer:
        def __init__(self):
            self.key = Ed25519PrivateKey.generate()

        def sign(self, raw):
            return self.key.sign(raw)

        def get_public_key(self):
            return self.key.public_key().public_bytes_raw()

    actor, authority = Signer(), Signer()
    proposal = json.loads(fixture())
    workspace = tmp_path / "workspace"
    spec_id = "SPEC-ACT-MANDATE-CHAIN-1"
    specs = workspace / "docs" / "specs"
    specs.mkdir(parents=True)
    (specs / (spec_id + ".md")).write_text(
        f"# {spec_id} -- Exact local task\n\n> **apatch artifact:** `spec:{spec_id}`\n"
        "\n## R1 Verify selected assignment\n\nOnly work on the reviewed assignment.\n"
        "\n(verify: python -m pytest tests/test_assignment.py)\n"
    )
    pins = {KEY_ID: PUBLIC_KEY, G.signer_key_id(authority): G._b64url_encode(authority.get_public_key())}
    assert M.configure_governed_work(str(workspace), platform_url="https://platform.example",
        client_id="apatch:test", binding_authority_keys=pins, request_key_provider=actor)["ok"]
    now = datetime(2026, 8, 31, 12, 2, tzinfo=timezone.utc)
    s = SimpleNamespace(events=[], fault=None, workspace=workspace, proposal=proposal, spec_id=spec_id)

    class Native:
        def accept_execution_proposal(self, root, **kwargs):
            s.events.append(("accept", kwargs["confirmation"]))
            assert kwargs["queue_source_binding"] is False and kwargs["request_key_provider"] is actor
            reply = M.accept_execution_proposal(root, now=now, **kwargs)
            if s.fault == "legacy":
                reply.pop("proposal_acceptance", None)
            return reply

    def post(request):
        payload = json.loads(request.content)
        change = payload["change"]
        path = request.url.path
        assert request.url.host == "platform.example" and request.method == "POST"
        assert request.headers["X-TC-Service-Key-Id"] == T.service_request_key_id(actor)
        signed = {"schema": T.SERVICE_REQUEST_SCHEMA, "method": "POST", "path": path,
                  "body_sha256": "sha256:" + hashlib.sha256(request.content).hexdigest(),
                  "subject": payload["subject"], "tenant_id": payload["tenant_id"],
                  "issued_at": int(request.headers["X-TC-Service-Issued-At"]),
                  "expires_at": int(request.headers["X-TC-Service-Expires-At"]),
                  "nonce": request.headers["X-TC-Service-Nonce"]}
        actor.key.public_key().verify(base64.urlsafe_b64decode(request.headers["X-TC-Service-Signature"] + "=="),
                                      T.SERVICE_REQUEST_DOMAIN + G.canonical_bytes(signed))
        common = {k: change[k] for k in ("tenant_id", "project_group_id", "work_program_id", "work_program_hash", "change_id")}
        common.update(change_hash=G.document_hash(change), actor_ref="member:" + "1" * 32)
        if "proposal_acceptance" in payload:
            a = payload["proposal_acceptance"]
            assert path == f"/api/internal/client/project-groups/{a['project_group_id']}/work-items/{a['work_item_id']}/apatch-studio/acceptances"
            s.events.append(("work_item", a["intent_id"]))
            purpose = W.BINDING_PURPOSE
            body = dict(common, schema=W.BINDING_SCHEMA, binding_id="tcawieb_"+"e"*32,
                        work_item_id=a["work_item_id"], accepted_work_item_hash=a["work_item_hash"],
                        accepted_authority_version=a["authority_version"], current_authority_version=a["authority_version"]+1,
                        current_work_item_hash="sha256:"+"f"*64, intent_id=a["intent_id"],
                        intent_document_hash=a["proposal_document_hash"], intent_envelope_hash=a["proposal_envelope_hash"],
                        proposal_acceptance_hash=G.document_hash(a), binding_authority_version=1, accepted_at=a["accepted_at"])
            if s.fault == "wrong_work_item":
                body["work_item_id"] = "tcpwi_" + "f"*32
        else:
            assert path == f"/api/internal/project-groups/{change['project_group_id']}/governed-work/source-bindings"
            s.events.append(("source", change["change_id"]))
            if s.fault == "offline":
                return httpx.Response(503, json={})
            purpose = G.PLATFORM_SOURCE_BINDING_PURPOSE
            body = dict(common, schema=G.SOURCE_BINDING_SCHEMA, binding_id="tcpsb_"+"f"*32,
                        authority_version=1, issued_at=change["issued_at"])
            body.update({k: change[k] for k in ("source_kind", "context_release_id", "context_release_manifest_hash",
                                                "execution_system", "spec_id", "spec_hash", "requirement_refs")})
            if s.fault == "other_actor":
                body["actor_ref"] = "member:"+"9"*32
        signature = authority.sign(G._platform_signature_payload(body, purpose=purpose))
        if s.fault == "wrong_signature" and purpose == G.PLATFORM_SOURCE_BINDING_PURPOSE:
            signature = bytes(64)
        return httpx.Response(201, json={**body, "signature": {"algorithm": "Ed25519",
            "key_id": G.signer_key_id(authority), "value": G._b64url_encode(signature)}})

    client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **options: client(transport=httpx.MockTransport(post), **options))
    s.gateway = APatchGovernedWorkGateway(workspace, api=Native(), identity_loader=lambda _: GatewayIdentity(actor))
    s.runs = FakeRuns(s.events)
    s.manager = ExecutionIntentManager(workspace, run_manager=s.runs, trust=trust(),
        state_root=tmp_path / "state", clock=lambda: now, governed_work_gateway=s.gateway)
    s.intent_id = s.manager.import_raw(fixture())["intent_id"]
    s.confirmation = ExecutionIntentConfirmation(confirmed=True, workspace_id=s.manager.workspace_id,
        runner_id="codex", mode="specification", spec_id=spec_id)
    return s


@pytest.mark.parametrize("fault", ["legacy", "wrong_work_item", "wrong_signature", "other_actor", "offline"])
def test_apatch_gateway_requires_acceptance_then_source_binding_ack(signed_inbox, fault):
    s = signed_inbox
    s.fault = fault
    with pytest.raises(ExecutionIntentError) as error:
        s.manager.confirm(s.intent_id, s.confirmation)
    assert error.value.code == "cowork_acceptance_incomplete"
    assert not s.runs.started
    assert not list(s.workspace.rglob("bindings/tcpsb_*.json"))
    assert s.manager.get(s.intent_id)["status"] == "awaiting_local_confirmation"
    if fault in {"legacy", "wrong_work_item"}:
        assert "source" not in [event for event, _ in s.events]
    s.fault = None
    completed = s.manager.confirm(s.intent_id, s.confirmation)
    assert completed["cowork"]["source_binding_id"] == "tcpsb_" + "f"*32
    assert [event for event, _ in s.events][-4:] == ["accept", "work_item", "source", "run"]


def test_canonical_work_item_binding_ack_precedes_local_agent_start(signed_inbox):
    s = signed_inbox
    receipt = s.manager.confirm(s.intent_id, s.confirmation)
    assert s.events[0] == ("accept", s.proposal["work_item_id"] + ":" + str(s.proposal["authority_version"]))
    assert [event for event, _ in s.events] == ["accept", "work_item", "source", "run"]
    assert receipt["status"] == "consumed" and receipt["cowork"]["status"] == "source_bound"
    assert receipt["cowork"]["source_binding_id"] == "tcpsb_" + "f"*32
    assert len(list(s.workspace.rglob("work_item_execution_bindings/tcawieb_*.json"))) == 1
    assert len(list(s.workspace.rglob("bindings/tcpsb_*.json"))) == 1
    with pytest.raises(ExecutionIntentError):
        s.manager.confirm(s.intent_id, s.confirmation)
    assert len(s.runs.started) == 1


def test_retry_rechecks_work_item_and_validates_the_selected_cached_source(signed_inbox):
    s = signed_inbox
    def accept():
        return s.gateway.accept_and_bind(s.proposal, spec_id=s.spec_id)

    first = accept()
    assert accept() == first
    assert [event for event, _ in s.events] == ["accept", "work_item", "source", "accept", "work_item"]
    path, = s.workspace.rglob("bindings/tcpsb_*.json")
    record = json.loads(path.read_bytes())
    record["signature"]["value"] = base64.urlsafe_b64encode(bytes(64)).rstrip(b"=").decode()
    path.write_text(json.dumps(record))
    from apatch_studio.governed_work_gateway import GovernedWorkGatewayError
    with pytest.raises(GovernedWorkGatewayError):
        accept()
    assert not s.runs.started


def test_apatch_gateway_uses_workspace_identity_despite_studio_machine_identity(
    tmp_path, monkeypatch
):
    from apatch_studio.governed_work_gateway import APatchGovernedWorkGateway

    workspace = tmp_path / "workspace-identity-precedence"
    (workspace / ".apatch").mkdir(parents=True)
    GatewayDelivery.config_path(workspace).write_text("{}", encoding="utf-8")
    workspace_public_key = GATEWAY_PROVIDER.get_public_key()
    (workspace / ".apatch" / "agent-identity.json").write_text(
        json.dumps(
            {
                "agent_id": "selected-workspace",
                "key_backend": "command",
                "sign_cmd": "trustchain-secrets-sign selected-workspace",
                "public_key": base64.b64encode(workspace_public_key).decode("ascii"),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("APATCH_AGENT_ID", "studio-machine")
    monkeypatch.setenv("APATCH_AGENT_KEY", "/machine/key.pem")
    gateway = APatchGovernedWorkGateway(
        workspace,
        api=GatewayApi(workspace),
        domain=GatewayDomain,
        delivery=GatewayDelivery,
        work_item_acceptance=GatewayWorkItemAcceptance,
    )

    provider = gateway._workspace_key_provider()
    assert provider.get_public_key() == workspace_public_key
    assert provider.get_key_id() == "selected-workspace"


def test_apatch_gateway_rejects_selected_workspace_identity_mismatch(tmp_path):
    from apatch_studio.governed_work_gateway import (
        APatchGovernedWorkGateway,
        GovernedWorkGatewayError,
    )

    workspace = tmp_path / "mismatched-gateway-workspace"
    (workspace / ".apatch").mkdir(parents=True)
    GatewayDelivery.config_path(workspace).write_text("{}", encoding="utf-8")
    api = GatewayApi(workspace)
    wrong_provider = GatewayKeyProvider(b"x" * 32)
    gateway = APatchGovernedWorkGateway(
        workspace,
        api=api,
        domain=GatewayDomain,
        delivery=GatewayDelivery,
        identity_loader=lambda _target_dir: GatewayIdentity(wrong_provider),
    )

    with pytest.raises(GovernedWorkGatewayError, match="does not match"):
        gateway.accept_and_bind(
            json.loads(fixture()),
            spec_id="SPEC-ACT-MANDATE-CHAIN-1",
        )
    assert api.events == []


class FakeCoworkGateway:
    connected = True

    def __init__(self, events, *, fail=False):
        self.events = events
        self.fail = fail

    def accept_and_bind(self, proposal, *, spec_id):
        self.events.append(("cowork", proposal["intent_id"], spec_id))
        if self.fail:
            raise RuntimeError("network detail must not escape")
        return {
            "status": "source_bound",
            "change_id": "apchg_" + "a" * 32,
            "change_hash": "sha256:" + "b" * 64,
            "source_binding_id": "tcpsb_" + "c" * 32,
            "source_binding_hash": "sha256:" + "d" * 64,
        }


def test_connected_inbox_requires_two_cowork_acks_before_start_and_keeps_raw_private(tmp_path):
    workspace = tmp_path / "connected-workspace"
    workspace.mkdir()
    events = []
    runs = FakeRuns(events)
    gateway = FakeCoworkGateway(events)
    manager = ExecutionIntentManager(
        workspace,
        run_manager=runs,
        trust=trust(),
        state_root=tmp_path / "connected-state",
        clock=lambda: datetime(2026, 8, 31, 12, 2, tzinfo=timezone.utc),
        governed_work_gateway=gateway,
    )

    preview = manager.import_raw(fixture())
    private_envelope = manager.store.envelope_path(preview["intent_id"])
    assert private_envelope.read_bytes() == fixture()
    assert private_envelope.stat().st_mode & 0o777 == 0o600
    assert b'"signature"' not in manager.store.journal_path.read_bytes()
    assert preview["cowork"] == {
        "connected": True,
        "required": True,
        "status": "awaiting_local_acceptance",
        "change_id": None,
        "source_binding_id": None,
    }

    with pytest.raises(ExecutionIntentError) as wrong_mode:
        manager.confirm(
            preview["intent_id"],
            ExecutionIntentConfirmation(
                confirmed=True,
                workspace_id=manager.workspace_id,
                runner_id="codex",
            ),
        )
    assert wrong_mode.value.code == "cowork_requires_existing_spec"
    assert events == []
    assert runs.started == []

    confirmed = manager.confirm(
        preview["intent_id"],
        ExecutionIntentConfirmation(
            confirmed=True,
            workspace_id=manager.workspace_id,
            runner_id="codex",
            mode="specification",
            spec_id="SPEC-ACT-MANDATE-CHAIN-1",
        ),
    )
    assert [event[0] for event in events] == ["cowork", "run"]
    assert confirmed["status"] == "consumed"
    assert confirmed["cowork"]["status"] == "source_bound"
    assert confirmed["cowork"]["change_id"] == "apchg_" + "a" * 32
    assert confirmed["cowork"]["source_binding_id"] == "tcpsb_" + "c" * 32
    assert not private_envelope.exists()


def test_connected_inbox_fails_closed_and_remains_retryable_without_ack(tmp_path):
    workspace = tmp_path / "retry-workspace"
    workspace.mkdir()
    events = []
    runs = FakeRuns(events)
    gateway = FakeCoworkGateway(events, fail=True)
    manager = ExecutionIntentManager(
        workspace,
        run_manager=runs,
        trust=trust(),
        state_root=tmp_path / "retry-state",
        clock=lambda: datetime(2026, 8, 31, 12, 2, tzinfo=timezone.utc),
        governed_work_gateway=gateway,
    )
    preview = manager.import_raw(fixture())
    confirmation = ExecutionIntentConfirmation(
        confirmed=True,
        workspace_id=manager.workspace_id,
        runner_id="codex",
        mode="specification",
        spec_id="SPEC-ACT-MANDATE-CHAIN-1",
    )

    with pytest.raises(ExecutionIntentError) as rejected:
        manager.confirm(preview["intent_id"], confirmation)
    assert rejected.value.code == "cowork_acceptance_incomplete"
    pending = manager.get(preview["intent_id"])
    assert pending["status"] == "awaiting_local_confirmation"
    assert pending["cowork"]["status"] == "acceptance_failed"
    assert manager.store.envelope_path(preview["intent_id"]).is_file()
    assert runs.started == []

    gateway.fail = False
    confirmed = manager.confirm(preview["intent_id"], confirmation)
    assert confirmed["cowork"]["status"] == "source_bound"
    assert len(runs.started) == 1




def test_decline_and_expiry_remove_the_private_signed_envelope(tmp_path):
    workspace = tmp_path / "terminal-workspace"
    workspace.mkdir()
    current = [datetime(2026, 8, 31, 12, 2, tzinfo=timezone.utc)]
    manager = ExecutionIntentManager(
        workspace,
        run_manager=FakeRuns(),
        trust=trust(),
        state_root=tmp_path / "terminal-state",
        clock=lambda: current[0],
    )

    declined = manager.import_raw(fixture())
    declined_path = manager.store.envelope_path(declined["intent_id"])
    assert declined_path.is_file()
    assert manager.cancel(declined["intent_id"])["status"] == "cancelled"
    assert not declined_path.exists()

    expiring = ExecutionIntentManager(
        workspace,
        run_manager=FakeRuns(),
        trust=trust(),
        state_root=tmp_path / "expiring-state",
        clock=lambda: current[0],
    )
    pending = expiring.import_raw(fixture())
    pending_path = expiring.store.envelope_path(pending["intent_id"])
    current[0] = datetime(2026, 8, 31, 12, 6, tzinfo=timezone.utc)
    assert expiring.get(pending["intent_id"])["status"] == "expired"
    assert not pending_path.exists()
def test_outside_in_inbox_names_the_cowork_boundary():
    source = (ROOT / "frontend/src/OutsideInAdmin.tsx").read_text(encoding="utf-8")
    assert "Cowork acceptance and source binding are required before the agent starts." in source
    assert "Accept in Cowork & run" in source
    assert "Prepare new contract" in source
def test_inbox_ui_imports_raw_envelope_and_requires_visible_owner_confirmation():
    app = (ROOT / "frontend/src/OutsideInAdmin.tsx").read_text(encoding="utf-8")
    api = (ROOT / "frontend/src/api.ts").read_text(encoding="utf-8")

    assert "Signed envelope" in app
    assert "Import signed task" in app
    assert "Cowork acceptance and source binding are required before the agent starts." in app
    assert "item.can_confirm" in app
    assert "importExecutionIntent" in api
    assert '"/api/v1/execution-intents/import"' in api


def test_inbox_is_explicitly_configured_and_local_work_remains_complete():
    oss = product_projection(StudioEdition.OSS)
    configured_oss = product_projection(StudioEdition.OSS, execution_intents=True)
    assert oss["features"]["local_governed_runs"] is True
    assert oss["features"]["execution_intents"] is False
    assert configured_oss["edition"] == "oss"
    assert configured_oss["features"]["execution_intents"] is True
    assert configured_oss["features"]["local_governed_runs"] is True
