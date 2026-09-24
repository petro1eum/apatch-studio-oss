from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from apatch_studio.result_delivery import (
    MAX_RESULT_BYTES,
    CoworkResultDelivery,
    ResultDeliveryError,
)


class FakeDomain:
    @staticmethod
    def canonical_bytes(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()

    @classmethod
    def value_hash(cls, value):
        return "sha256:" + hashlib.sha256(cls.canonical_bytes(value)).hexdigest()

    @staticmethod
    def governed_work_root(target_dir):
        return Path(target_dir) / ".apatch" / "governed_work"

    @classmethod
    def load_project_source_binding(cls, target_dir, binding_id):
        path = cls.governed_work_root(target_dir) / "bindings" / f"{binding_id}.json"
        return json.loads(path.read_text(encoding="utf-8"))


class FakeBindingDelivery:
    @staticmethod
    def load_config(_target_dir):
        return {"binding_authority_keys": {"platform:key": "public"}}


class FakeWorkItemAcceptance:
    @staticmethod
    def validate_binding(document, *, trusted_keys):
        assert trusted_keys == {"platform:key": "public"}
        return document


class FakeApi:
    def __init__(self):
        self.calls = []
        self.bundle_id = "apweb_" + "7" * 32
        self.bundle_hash = "sha256:" + "8" * 64

    def build_governed_evidence(self, target_dir, **request):
        self.calls.append(("build", target_dir, request))
        return {
            "operation": "build_evidence",
            "evidence_bundle": {"bundle_id": self.bundle_id},
        }

    def preview_governed_evidence_publication(self, target_dir, **request):
        self.calls.append(("preview", target_dir, request))
        return {
            "ok": True,
            "plan": {
                "schema": "apatch.governed-work.share-plan.v1",
                "platform_origin": "https://trust-chain.ai",
                "client_subject": "member:" + "9" * 32,
                "tenant_id": "11111111-1111-4111-8111-111111111111",
                "project_group_id": "tcpg_" + "2" * 32,
                "scope": "governed_work.evidence_admission",
                "evidence_bundle_ref": {
                    "bundle_id": self.bundle_id,
                    "bundle_hash": self.bundle_hash,
                },
                "timesheet_ref": {
                    "timesheet_id": "aptsh_" + "a" * 32,
                    "timesheet_hash": "sha256:" + "b" * 64,
                    "claimed_active_seconds": 321,
                },
                "connection_generation": "sha256:" + "c" * 64,
                "plan_hash": "sha256:" + "d" * 64,
            },
        }


class ExistingEvidenceApi(FakeApi):
    def __init__(self, error="immutable id is already bound to another envelope: apts_test"):
        super().__init__()
        self.error = error

    def build_governed_evidence(self, target_dir, **request):
        self.calls.append(("build", target_dir, request))
        return {
            "ok": False,
            "error_type": "GOVERNED_WORK_INVALID",
            "error": self.error,
        }


def assignment() -> dict:
    return {
        "intent_id": "tcapsei_" + "1" * 32,
        "tenant_id": "11111111-1111-4111-8111-111111111111",
        "project_group_id": "tcpg_" + "2" * 32,
        "work_item_id": "tcpwi_" + "3" * 32,
        "work_item_hash": "sha256:" + "4" * 64,
        "authority_version": 7,
        "work_program_id": "tcwp_" + "5" * 32,
        "work_program_hash": "sha256:" + "6" * 64,
        "status": "consumed",
        "cowork_status": "source_bound",
        "cowork_change_id": "apchg_" + "d" * 32,
        "cowork_source_binding_id": "tcpsb_" + "f" * 32,
    }


def delivery(workspace: Path, api: FakeApi | None = None) -> CoworkResultDelivery:
    return CoworkResultDelivery(
        workspace,
        api=api or FakeApi(),
        domain=FakeDomain,
        delivery=object(),
        transport=object(),
        identity_loader=lambda _root: None,
    )




class ConsentDelivery(CoworkResultDelivery):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.deliveries = []

    def _deliver(self, record, plan, publication):
        self.deliveries.append((dict(record), dict(plan), dict(publication)))
        return {"state": "submitted", "plan_hash": plan["plan_hash"]}


def consent_delivery(workspace: Path, api: FakeApi) -> ConsentDelivery:
    return ConsentDelivery(
        workspace,
        api=api,
        domain=FakeDomain,
        delivery=object(),
        transport=object(),
        identity_loader=lambda _root: None,
    )


def test_submit_requires_fresh_exact_disclosure_confirmation(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    result = workspace / "result.txt"
    result.write_bytes(b"version one\n")
    api = FakeApi()
    service = consent_delivery(workspace, api)
    record = assignment()
    plan = service.preview(record, relative_path="result.txt")
    preview_call_count = len(api.calls)

    with pytest.raises(ResultDeliveryError, match="confirmation"):
        service.submit(
            record,
            relative_path="result.txt",
            plan=plan,
            confirmation="submit:" + "0" * 71,
        )
    assert service.deliveries == []
    assert len(api.calls) == preview_call_count + 2

    changed = dict(plan)
    changed["result"] = {**plan["result"], "size_bytes": plan["result"]["size_bytes"] + 1}
    with pytest.raises(ResultDeliveryError, match="stale or changed"):
        service.submit(
            record,
            relative_path="result.txt",
            plan=changed,
            confirmation=f"submit:{plan['plan_hash']}",
        )
    assert service.deliveries == []

    result.write_bytes(b"version two\n")
    with pytest.raises(ResultDeliveryError, match="stale or changed"):
        service.submit(
            record,
            relative_path="result.txt",
            plan=plan,
            confirmation=f"submit:{plan['plan_hash']}",
        )
    assert service.deliveries == []

    fresh = service.preview(record, relative_path="result.txt")
    receipt = service.submit(
        record,
        relative_path="result.txt",
        plan=fresh,
        confirmation=f"submit:{fresh['plan_hash']}",
    )
    assert receipt == {"state": "submitted", "plan_hash": fresh["plan_hash"]}
    assert len(service.deliveries) == 1

    with pytest.raises(ValueError):
        from apatch_studio.result_delivery import ResultSubmitRequest

        ResultSubmitRequest.model_validate(
            {
                "relative_path": "result.txt",
                "plan": fresh,
                "confirmation": f"submit:{fresh['plan_hash']}",
                "outcome_ref": "sha256:" + "0" * 64,
            }
        )


class Provider:
    def get_public_key(self):
        return b"k" * 32


class Identity:
    key_provider = Provider()


class RoundTripApi(FakeApi):
    def publish_governed_evidence(self, target_dir, **request):
        self.calls.append(("publish", target_dir, request))
        assert request["confirmation"] == "publish:sha256:" + "d" * 64
        return {"ok": True, "delivery": {"status": "queued"}}

    def sync_governed_work(self, target_dir, **request):
        self.calls.append(("sync", target_dir, request))
        assert request["request_key_provider"] is Identity.key_provider
        return {"ok": True, "status": "in_sync", "delivered": 1, "pending": 0}


class RoundTripDelivery:
    httpx = None

    @staticmethod
    def load_config(_target_dir):
        return {
            "platform_url": "https://trust-chain.ai",
            "client_id": "member:" + "9" * 32,
            "service_request_key_id": "sha256:" + "e" * 64,
            "binding_authority_keys": {"platform:key": "public"},
        }


class RoundTripTransport:
    calls = []

    @classmethod
    def service_request_key_id(cls, provider):
        assert provider is Identity.key_provider
        return "sha256:" + "e" * 64

    @classmethod
    def signed_service_headers(cls, target_dir, **request):
        cls.calls.append((target_dir, request))
        assert request["key_provider"] is Identity.key_provider
        return {
            "X-TC-Service-Key-Id": "sha256:" + "e" * 64,
            "X-TC-Service-Signature": "signed",
        }


class Response:
    def __init__(self, body, status_code):
        self._body = body
        self.status_code = status_code
        self.content = FakeDomain.canonical_bytes(body)

    def json(self):
        return self._body


class ResultClient:
    def __init__(self):
        self.calls = []

    def post(self, url, *, content, headers):
        body = json.loads(content)
        self.calls.append((url, body, headers))
        submitted = url.endswith("/submit")
        state = "submitted" if submitted else "draft"
        return Response(
            {
                "schema": "trustchain.apatch-studio.result-delivery.v1",
                "project_group_id": assignment()["project_group_id"],
                "work_item_id": assignment()["work_item_id"],
                "release_id": "tcwr_" + ("b" if submitted else "a") * 32,
                "release_hash": "sha256:" + ("3" if submitted else "2") * 64,
                "state": state,
                "available_actions": {"submit": not submitted},
            },
            200 if submitted else 201,
        )


def test_submission_publishes_evidence_then_creates_and_submits_release(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "result.txt").write_bytes(b"verified result\n")
    api = RoundTripApi()
    client = ResultClient()
    record = {
        **assignment(),
        "cowork_source_binding_id": "tcawieb_" + "c" * 32,
    }
    canonical = {
        "binding_id": record["cowork_source_binding_id"],
        "tenant_id": record["tenant_id"],
        "project_group_id": record["project_group_id"],
        "work_item_id": record["work_item_id"],
        "accepted_work_item_hash": record["work_item_hash"],
        "accepted_authority_version": record["authority_version"],
        "current_work_item_hash": "sha256:" + "9" * 64,
        "current_authority_version": record["authority_version"] + 1,
        "work_program_id": record["work_program_id"],
        "work_program_hash": record["work_program_hash"],
        "intent_id": record["intent_id"],
        "change_id": record["cowork_change_id"],
        "change_hash": "sha256:" + "a" * 64,
        "actor_ref": "member:" + "9" * 32,
    }
    source_binding = {
        "binding_id": "tcpsb_" + "b" * 32,
        "tenant_id": canonical["tenant_id"],
        "project_group_id": canonical["project_group_id"],
        "work_program_id": canonical["work_program_id"],
        "work_program_hash": canonical["work_program_hash"],
        "change_id": canonical["change_id"],
        "change_hash": canonical["change_hash"],
        "actor_ref": canonical["actor_ref"],
    }
    root = FakeDomain.governed_work_root(workspace)
    canonical_directory = root / "work_item_execution_bindings"
    source_directory = root / "bindings"
    canonical_directory.mkdir(parents=True)
    source_directory.mkdir(parents=True)
    (canonical_directory / f"{canonical['binding_id']}.json").write_text(
        json.dumps(canonical), encoding="utf-8"
    )
    (source_directory / f"{source_binding['binding_id']}.json").write_text(
        json.dumps(source_binding), encoding="utf-8"
    )
    service = CoworkResultDelivery(
        workspace,
        api=api,
        domain=FakeDomain,
        delivery=RoundTripDelivery,
        transport=RoundTripTransport,
        work_item_acceptance=FakeWorkItemAcceptance,
        identity_loader=lambda _root: Identity,
        http_client=client,
    )
    plan = service.preview(record, relative_path="result.txt")
    assert plan["work_item_hash"] == canonical["current_work_item_hash"]
    assert plan["authority_version"] == canonical["current_authority_version"]

    receipt = service.submit(
        record,
        relative_path="result.txt",
        plan=plan,
        confirmation=f"submit:{plan['plan_hash']}",
    )

    assert receipt == {
        "schema": "trustchain.apatch-studio.result-delivery.v1",
        "project_group_id": record["project_group_id"],
        "work_item_id": record["work_item_id"],
        "release_id": "tcwr_" + "b" * 32,
        "release_hash": "sha256:" + "3" * 64,
        "state": "submitted",
        "available_actions": {"submit": False},
    }
    assert [call[0] for call in api.calls] == [
        "build", "preview", "build", "preview", "publish", "sync"
    ]
    assert len(client.calls) == 2
    create_url, create_body, create_headers = client.calls[0]
    submit_url, submit_body, submit_headers = client.calls[1]
    assert create_url.endswith(
        f"/work-items/{record['work_item_id']}/apatch-studio/releases"
    )
    assert submit_url == create_url + "/tcwr_" + "a" * 32 + "/submit"
    assert set(create_body) == {
        "subject", "tenant_id", "expected_work_item_hash",
        "expected_work_item_authority_version", "expected_work_program",
        "outcome_ref", "evidence_bundle_id", "idempotency_key",
    }
    assert create_body["outcome_ref"] == plan["result"]["outcome_ref"]
    assert create_body["evidence_bundle_id"] == plan["evidence"]["bundle_id"]
    assert create_body["expected_work_item_hash"] == canonical["current_work_item_hash"]
    assert (
        create_body["expected_work_item_authority_version"]
        == canonical["current_authority_version"]
    )
    assert set(submit_body) == {
        "subject", "tenant_id", "expected_work_item_hash",
        "expected_work_item_authority_version", "expected_work_program",
        "idempotency_key",
    }
    assert submit_body["expected_work_item_hash"] == canonical["current_work_item_hash"]
    assert (
        submit_body["expected_work_item_authority_version"]
        == canonical["current_authority_version"]
    )
    assert create_body["idempotency_key"] != submit_body["idempotency_key"]
    assert create_headers["X-TC-Service-Signature"] == "signed"
    assert submit_headers["X-TC-Service-Signature"] == "signed"
    assert [call[1]["path"] for call in RoundTripTransport.calls[-2:]] == [
        create_url.removeprefix("https://trust-chain.ai"),
        submit_url.removeprefix("https://trust-chain.ai"),
    ]
class ConnectedGateway:
    connected = True


class DurableResultDelivery:
    def __init__(self, receipt):
        self.receipt = receipt
        self.submit_calls = []

    def submit(self, record, **request):
        self.submit_calls.append((dict(record), request))
        return dict(self.receipt)


class NoopRuns:
    pass


def stored_assignment() -> dict:
    now = "2026-09-23T12:00:00+00:00"
    return {
        "schema": "apatch.studio.execution-intent-record.v1",
        **assignment(),
        "objective": "Deliver one governed result",
        "acceptance_criteria": ["Receipt is submitted"],
        "issued_at": now,
        "expires_at": "2026-09-24T12:00:00+00:00",
        "received_at": now,
        "updated_at": now,
        "document_hash": "sha256:" + "9" * 64,
        "envelope_hash": "sha256:" + "a" * 64,
        "nonce_digest": "sha256:" + "b" * 64,
        "run_id": "apr_" + "c" * 32,
        "consumed_at": now,
        "cowork_change_id": "apchg_" + "d" * 32,
        "cowork_result_state": "not_submitted",
        "cowork_result_plan_hash": None,
        "cowork_result_outcome_ref": None,
        "cowork_result_evidence_bundle_id": None,
        "cowork_result_evidence_bundle_hash": None,
        "cowork_result_release_id": None,
        "cowork_result_release_hash": None,
        "cowork_result_updated_at": None,
    }


def submitted_plan() -> dict:
    return {
        "plan_hash": "sha256:" + "1" * 64,
        "result": {
            "relative_path": "result.txt",
            "outcome_ref": "sha256:" + "2" * 64,
            "size_bytes": 17,
            "content_shared": False,
        },
        "evidence": {
            "bundle_id": "apweb_" + "3" * 32,
            "bundle_hash": "sha256:" + "4" * 64,
        },
    }


def test_submitted_receipt_is_minimal_durable_and_retry_safe(tmp_path):
    from apatch_studio.execution_intents import ExecutionIntentManager
    from apatch_studio.result_delivery import ResultSubmitRequest

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    receipt = {
        "schema": "trustchain.apatch-studio.result-delivery.v1",
        "project_group_id": assignment()["project_group_id"],
        "work_item_id": assignment()["work_item_id"],
        "release_id": "tcwr_" + "5" * 32,
        "release_hash": "sha256:" + "6" * 64,
        "state": "submitted",
        "available_actions": {"submit": False},
    }
    delivery = DurableResultDelivery(receipt)
    manager = ExecutionIntentManager(
        workspace,
        run_manager=NoopRuns(),
        state_root=tmp_path / "state",
        clock=lambda: __import__("datetime").datetime(
            2026, 9, 23, 12, 5, tzinfo=__import__("datetime").timezone.utc
        ),
        governed_work_gateway=ConnectedGateway(),
        result_delivery=delivery,
    )
    manager.store.update(lambda records: records.append(stored_assignment()))
    plan = submitted_plan()
    request = ResultSubmitRequest(
        relative_path="result.txt",
        plan=plan,
        confirmation=f"submit:{plan['plan_hash']}",
    )

    first = manager.submit_result(assignment()["intent_id"], request)
    second = manager.submit_result(assignment()["intent_id"], request)

    assert first == second
    assert first["state"] == "submitted"
    assert len(delivery.submit_calls) == 1
    journal = json.loads(manager.store.journal_path.read_text(encoding="utf-8"))
    stored = journal["records"][0]
    assert set(key for key in stored if key.startswith("cowork_result_")) == {
        "cowork_result_state",
        "cowork_result_plan_hash",
        "cowork_result_outcome_ref",
        "cowork_result_evidence_bundle_id",
        "cowork_result_evidence_bundle_hash",
        "cowork_result_release_id",
        "cowork_result_release_hash",
        "cowork_result_updated_at",
    }
    assert stored["cowork_result_plan_hash"] == plan["plan_hash"]
    assert stored["cowork_result_outcome_ref"] == plan["result"]["outcome_ref"]
    assert stored["cowork_result_release_id"] == receipt["release_id"]
    encoded = manager.store.journal_path.read_text(encoding="utf-8")
    assert "result.txt" not in encoded
    assert "verified result" not in encoded

    conflicting = plan | {"plan_hash": "sha256:" + "7" * 64}
    with pytest.raises(ResultDeliveryError, match="conflicts"):
        manager.submit_result(
            assignment()["intent_id"],
            ResultSubmitRequest(
                relative_path="result.txt",
                plan=conflicting,
                confirmation=f"submit:{conflicting['plan_hash']}",
            ),
        )
    assert len(delivery.submit_calls) == 1


def test_preview_is_local_bounded_and_uses_exact_source_binding(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    result = workspace / "result.txt"
    result.write_bytes(b"verified result\n")
    api = FakeApi()
    service = delivery(workspace, api)

    plan = service.preview(assignment(), relative_path="result.txt")

    assert [call[0] for call in api.calls] == ["build", "preview"]
    assert all(
        call[2]["binding_id"] == assignment()["cowork_source_binding_id"]
        for call in api.calls
    )
    assert plan["result"] == {
        "relative_path": "result.txt",
        "outcome_ref": "sha256:" + hashlib.sha256(b"verified result\n").hexdigest(),
        "size_bytes": len(b"verified result\n"),
        "content_shared": False,
    }
    assert plan["evidence"] == {
        "bundle_id": api.bundle_id,
        "bundle_hash": api.bundle_hash,
        "claimed_active_seconds": 321,
        "publication_plan_hash": "sha256:" + "d" * 64,
    }
    assert plan["source_binding_id"] == assignment()["cowork_source_binding_id"]
    assert plan["plan_hash"] == FakeDomain.value_hash(
        {key: value for key, value in plan.items() if key != "plan_hash"}
    )
    encoded = json.dumps(plan)
    for forbidden in ("verified result", str(workspace.resolve()), "prompt", "credential"):
        assert forbidden not in encoded

    existing_api = ExistingEvidenceApi()
    existing_plan = delivery(workspace, existing_api).preview(
        assignment(), relative_path="result.txt"
    )
    assert existing_plan == plan
    assert [call[0] for call in existing_api.calls] == ["build", "preview"]

    failed_api = ExistingEvidenceApi(error="missing current attestations")
    with pytest.raises(ResultDeliveryError, match="could not be prepared"):
        delivery(workspace, failed_api).preview(
            assignment(), relative_path="result.txt"
        )
    assert [call[0] for call in failed_api.calls] == ["build"]

    canonical_id = "tcawieb_" + "c" * 32
    source_id = "tcpsb_" + "b" * 32
    canonical_record = {
        **assignment(),
        "cowork_source_binding_id": canonical_id,
    }
    canonical = {
        "binding_id": canonical_id,
        "tenant_id": canonical_record["tenant_id"],
        "project_group_id": canonical_record["project_group_id"],
        "work_item_id": canonical_record["work_item_id"],
        "accepted_work_item_hash": canonical_record["work_item_hash"],
        "accepted_authority_version": canonical_record["authority_version"],
        "current_work_item_hash": "sha256:" + "9" * 64,
        "current_authority_version": canonical_record["authority_version"] + 1,
        "work_program_id": canonical_record["work_program_id"],
        "work_program_hash": canonical_record["work_program_hash"],
        "intent_id": canonical_record["intent_id"],
        "change_id": canonical_record["cowork_change_id"],
        "change_hash": "sha256:" + "a" * 64,
        "actor_ref": "member:" + "9" * 32,
    }
    source_binding = {
        "binding_id": source_id,
        "tenant_id": canonical["tenant_id"],
        "project_group_id": canonical["project_group_id"],
        "work_program_id": canonical["work_program_id"],
        "work_program_hash": canonical["work_program_hash"],
        "change_id": canonical["change_id"],
        "change_hash": canonical["change_hash"],
        "actor_ref": canonical["actor_ref"],
        "spec_id": "SPEC-STUDIO-COWORK-RESULT-DELIVERY-1",
        "spec_hash": "sha256:" + "e" * 64,
    }
    root = FakeDomain.governed_work_root(workspace)
    canonical_directory = root / "work_item_execution_bindings"
    source_directory = root / "bindings"
    canonical_directory.mkdir(parents=True)
    source_directory.mkdir(parents=True)
    (canonical_directory / f"{canonical_id}.json").write_text(
        json.dumps(canonical), encoding="utf-8"
    )
    (source_directory / f"{source_id}.json").write_text(
        json.dumps(source_binding), encoding="utf-8"
    )
    bridged_api = FakeApi()
    bridged = CoworkResultDelivery(
        workspace,
        api=bridged_api,
        domain=FakeDomain,
        delivery=FakeBindingDelivery,
        transport=object(),
        work_item_acceptance=FakeWorkItemAcceptance,
        identity_loader=lambda _root: None,
    )

    bridged_plan = bridged.preview(canonical_record, relative_path="result.txt")

    assert [call[2]["binding_id"] for call in bridged_api.calls] == [
        source_id,
        source_id,
    ]
    assert bridged_plan["source_binding_id"] == source_id
    assert bridged_plan["work_item_hash"] == canonical["current_work_item_hash"]
    assert bridged_plan["authority_version"] == canonical["current_authority_version"]

    mismatched = dict(canonical)
    mismatched["accepted_work_item_hash"] = "sha256:" + "0" * 64
    (canonical_directory / f"{canonical_id}.json").write_text(
        json.dumps(mismatched), encoding="utf-8"
    )
    rejected_api = FakeApi()
    rejected = CoworkResultDelivery(
        workspace,
        api=rejected_api,
        domain=FakeDomain,
        delivery=FakeBindingDelivery,
        transport=object(),
        work_item_acceptance=FakeWorkItemAcceptance,
        identity_loader=lambda _root: None,
    )
    with pytest.raises(ResultDeliveryError, match="does not match"):
        rejected.preview(canonical_record, relative_path="result.txt")
    assert rejected_api.calls == []

    (canonical_directory / f"{canonical_id}.json").write_text(
        json.dumps(canonical), encoding="utf-8"
    )
    duplicate_id = "tcpsb_" + "d" * 32
    duplicate = {**source_binding, "binding_id": duplicate_id}
    (source_directory / f"{duplicate_id}.json").write_text(
        json.dumps(duplicate), encoding="utf-8"
    )
    ambiguous_api = FakeApi()
    ambiguous = CoworkResultDelivery(
        workspace,
        api=ambiguous_api,
        domain=FakeDomain,
        delivery=FakeBindingDelivery,
        transport=object(),
        work_item_acceptance=FakeWorkItemAcceptance,
        identity_loader=lambda _root: None,
    )
    with pytest.raises(ResultDeliveryError, match="one exact"):
        ambiguous.preview(canonical_record, relative_path="result.txt")
    assert ambiguous_api.calls == []

    before = len(api.calls)
    for invalid in (str(result.resolve()), "../result.txt", ".", "missing.txt"):
        with pytest.raises(ResultDeliveryError):
            service.preview(assignment(), relative_path=invalid)
    directory = workspace / "directory"
    directory.mkdir()
    with pytest.raises(ResultDeliveryError):
        service.preview(assignment(), relative_path="directory")
    symlink = workspace / "link.txt"
    symlink.symlink_to(result)
    with pytest.raises(ResultDeliveryError):
        service.preview(assignment(), relative_path="link.txt")
    oversized = workspace / "oversized.bin"
    with oversized.open("wb") as handle:
        handle.truncate(MAX_RESULT_BYTES + 1)
    with pytest.raises(ResultDeliveryError):
        service.preview(assignment(), relative_path="oversized.bin")
    unbound = {**assignment(), "cowork_status": "acceptance_failed"}
    with pytest.raises(ResultDeliveryError):
        service.preview(unbound, relative_path="result.txt")
    assert len(api.calls) == before
