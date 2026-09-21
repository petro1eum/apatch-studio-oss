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
    def __init__(self, workspace, *, legacy=False, canonical=False):
        self.workspace = Path(workspace)
        self.legacy = legacy
        self.canonical = canonical
        self.events = []
        self.sync_providers = []
        self.change = None
        self.change_hash = None
        self.proposal = None

    def accept_execution_proposal(self, target_dir, **request):
        self.events.append(("accept", request))
        proposal = request["proposal"]
        self.proposal = proposal
        self.change = {
            "change_id": "apchg_" + "e" * 32,
            "tenant_id": proposal["tenant_id"],
            "project_group_id": proposal["project_group_id"],
            "work_program_id": proposal["work_program_id"],
            "work_program_hash": proposal["work_program_hash"],
            "spec_id": request["spec_id"],
            "spec_hash": "sha256:" + "f" * 64,
        }
        self.change_hash = GatewayDomain.document_hash(self.change)
        return {
            "ok": True,
            "work_started": False,
            "change": self.change,
            "change_hash": self.change_hash,
            "work_item_acceptance_delivery": {
                "status": "queued" if self.canonical else "not_requested"
            },
            "source_binding_delivery": {
                "status": (
                    "superseded_by_work_item_acceptance"
                    if self.canonical
                    else (
                        "not_requested"
                        if self.legacy
                        else "queued_after_work_item_acceptance_ack"
                    )
                )
            },
        }

    def sync_governed_work(self, target_dir, **request):
        self.sync_providers.append(request.get("request_key_provider"))
        self.events.append(("sync", len(self.events)))
        if sum(event[0] == "sync" for event in self.events) == 2:
            if self.canonical:
                binding = {
                    "binding_id": "tcawieb_" + "f" * 32,
                    "change_id": self.change["change_id"],
                    "change_hash": self.change_hash,
                    "tenant_id": self.change["tenant_id"],
                    "project_group_id": self.change["project_group_id"],
                    "work_program_id": self.change["work_program_id"],
                    "work_program_hash": self.change["work_program_hash"],
                    "work_item_id": self.proposal["work_item_id"],
                    "accepted_work_item_hash": self.proposal["work_item_hash"],
                    "accepted_authority_version": self.proposal["authority_version"],
                    "intent_id": self.proposal["intent_id"],
                }
                directory = (
                    GatewayDomain.governed_work_root(target_dir)
                    / "work_item_execution_bindings"
                )
            else:
                binding = {
                    "binding_id": "tcpsb_" + "f" * 32,
                    "change_id": self.change["change_id"],
                    "change_hash": self.change_hash,
                    "tenant_id": self.change["tenant_id"],
                    "project_group_id": self.change["project_group_id"],
                    "work_program_id": self.change["work_program_id"],
                    "work_program_hash": self.change["work_program_hash"],
                    "spec_id": self.change["spec_id"],
                    "spec_hash": self.change["spec_hash"],
                }
                directory = GatewayDomain.governed_work_root(target_dir) / "bindings"
            directory.mkdir(parents=True)
            (directory / f"{binding['binding_id']}.json").write_text(
                json.dumps(binding), encoding="utf-8"
            )
        return {"ok": not self.canonical}


def test_apatch_gateway_requires_acceptance_then_source_binding_ack(tmp_path):
    from apatch_studio.governed_work_gateway import (
        APatchGovernedWorkGateway,
        GovernedWorkGatewayError,
    )

    workspace = tmp_path / "gateway-workspace"
    (workspace / ".apatch").mkdir(parents=True)
    GatewayDelivery.config_path(workspace).write_text("{}", encoding="utf-8")
    proposal = json.loads(fixture())
    api = GatewayApi(workspace)
    gateway = APatchGovernedWorkGateway(
        workspace,
        api=api,
        domain=GatewayDomain,
        delivery=GatewayDelivery,
        identity_loader=gateway_identity_loader,
    )

    receipt = gateway.accept_and_bind(
        proposal,
        spec_id="SPEC-ACT-MANDATE-CHAIN-1",
    )
    assert [event[0] for event in api.events] == ["accept", "sync", "sync"]
    request = api.events[0][1]
    assert request["confirmation"] == (
        proposal["work_item_id"] + ":" + str(proposal["authority_version"])
    )
    assert request["queue_source_binding"] is True
    assert request["request_key_provider"] is GATEWAY_PROVIDER
    assert api.sync_providers == [GATEWAY_PROVIDER, GATEWAY_PROVIDER]
    assert request["purpose"] == (
        "Execute the owner-selected SPEC for Cowork work item "
        f"{proposal['work_item_id']} under execution intent {proposal['intent_id']}"
    )
    assert receipt["change_id"] == "apchg_" + "e" * 32
    assert receipt["source_binding_id"] == "tcpsb_" + "f" * 32

    legacy = GatewayApi(workspace, legacy=True)
    old_gateway = APatchGovernedWorkGateway(
        workspace,
        api=legacy,
        domain=GatewayDomain,
        delivery=GatewayDelivery,
        identity_loader=gateway_identity_loader,
    )
    with pytest.raises(GovernedWorkGatewayError, match="cannot complete"):
        old_gateway.accept_and_bind(
            proposal,
            spec_id="SPEC-ACT-MANDATE-CHAIN-1",
        )
    assert [event[0] for event in legacy.events] == ["accept"]
def test_canonical_work_item_binding_ack_precedes_local_agent_start(tmp_path):
    from apatch_studio.governed_work_gateway import APatchGovernedWorkGateway

    workspace = tmp_path / "canonical-gateway-workspace"
    (workspace / ".apatch").mkdir(parents=True)
    GatewayDelivery.config_path(workspace).write_text("{}", encoding="utf-8")
    events = []
    runs = FakeRuns(events)
    api = GatewayApi(workspace, canonical=True)
    gateway = APatchGovernedWorkGateway(
        workspace,
        api=api,
        domain=GatewayDomain,
        delivery=GatewayDelivery,
        work_item_acceptance=GatewayWorkItemAcceptance,
        identity_loader=gateway_identity_loader,
    )
    manager = ExecutionIntentManager(
        workspace,
        run_manager=runs,
        trust=trust(),
        state_root=tmp_path / "canonical-gateway-state",
        clock=lambda: datetime(2026, 8, 31, 12, 2, tzinfo=timezone.utc),
        governed_work_gateway=gateway,
    )

    preview = manager.import_raw(fixture())
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

    assert [event[0] for event in api.events] == ["accept", "sync", "sync"]
    assert [event[0] for event in events] == ["run"]
    assert confirmed["status"] == "consumed"
    assert confirmed["cowork"]["status"] == "source_bound"
    assert confirmed["cowork"]["source_binding_id"] == "tcawieb_" + "f" * 32


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
