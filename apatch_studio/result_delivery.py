"""Local-first preparation for APatch Studio result delivery to Cowork."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

MAX_RESULT_BYTES = 32 * 1024 * 1024
RESULT_PLAN_SCHEMA = "apatch.studio.cowork-result-delivery-plan.v1"
_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_INTENT_RE = re.compile(r"^tcapsei_[0-9a-f]{32}$")
_GROUP_RE = re.compile(r"^tcpg_[0-9a-f]{32}$")
_ITEM_RE = re.compile(r"^tcpwi_[0-9a-f]{32}$")
_PROGRAM_RE = re.compile(r"^tcwp_[0-9a-f]{32}$")
_CHANGE_RE = re.compile(r"^apchg_[0-9a-f]{32}$")
_BINDING_RE = re.compile(r"^(?:tcpsb|tcawieb)_[0-9a-f]{32}$")
_BUNDLE_RE = re.compile(r"^apweb_[0-9a-f]{32}$")

_PUBLICATION_PLAN_KEYS = {
    "schema",
    "platform_origin",
    "client_subject",
    "tenant_id",
    "project_group_id",
    "scope",
    "evidence_bundle_ref",
    "timesheet_ref",
    "connection_generation",
    "plan_hash",
}
_EVIDENCE_REF_KEYS = {"bundle_id", "bundle_hash"}
_TIMESHEET_REF_KEYS = {
    "timesheet_id",
    "timesheet_hash",
    "claimed_active_seconds",
}


class ResultDeliveryError(RuntimeError):
    """A stable failure that never includes source or result content."""


class ResultPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    relative_path: str = Field(min_length=1, max_length=1024)


class ResultSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    relative_path: str = Field(min_length=1, max_length=1024)
    plan: dict[str, Any]
    confirmation: str = Field(min_length=8, max_length=160)


class CoworkResultDelivery:
    """Prepare one content-free disclosure plan from exact local APatch facts."""

    def __init__(
        self,
        workspace: str | Path,
        *,
        api: Any | None = None,
        domain: Any | None = None,
        delivery: Any | None = None,
        transport: Any | None = None,
        work_item_acceptance: Any | None = None,
        identity_loader: Any | None = None,
        http_client: Any | None = None,
    ):
        self.workspace = Path(workspace).expanduser().resolve()
        if api is None or domain is None or delivery is None or transport is None:
            from apatch import governed_work as runtime_domain
            from apatch import governed_work_delivery as runtime_delivery
            from apatch import governed_work_mcp as runtime_api
            from apatch import governed_work_transport as runtime_transport

            api = api or runtime_api
            domain = domain or runtime_domain
            delivery = delivery or runtime_delivery
            transport = transport or runtime_transport
        if identity_loader is None:
            from apatch_studio.governed_work_gateway import (
                _load_exact_workspace_identity,
            )

            identity_loader = _load_exact_workspace_identity
        self._api = api
        self._domain = domain
        self._delivery = delivery
        self._transport = transport
        self._work_item_acceptance = work_item_acceptance
        self._identity_loader = identity_loader
        self._http_client = http_client

    def preview(
        self,
        record: Mapping[str, Any],
        *,
        relative_path: str,
    ) -> dict[str, Any]:
        plan, _publication = self._prepare(record, relative_path=relative_path)
        return plan

    def submit(
        self,
        record: Mapping[str, Any],
        *,
        relative_path: str,
        plan: Mapping[str, Any],
        confirmation: str,
    ) -> dict[str, Any]:
        candidate = self._result_plan(plan)
        current, publication = self._prepare(record, relative_path=relative_path)
        if self._domain.canonical_bytes(candidate) != self._domain.canonical_bytes(
            current
        ):
            raise ResultDeliveryError("result delivery plan is stale or changed")
        if confirmation != f"submit:{current['plan_hash']}":
            raise ResultDeliveryError("exact submit:<plan_hash> confirmation is required")
        return self._deliver(self._accepted_record(record), current, publication)

    def _deliver(
        self,
        record: Mapping[str, Any],
        plan: Mapping[str, Any],
        publication: Mapping[str, Any],
    ) -> dict[str, Any]:
        provider = self._workspace_key_provider()
        published = self._api.publish_governed_evidence(
            str(self.workspace),
            plan=dict(publication),
            confirmation=f"publish:{publication['plan_hash']}",
        )
        if not isinstance(published, dict) or published.get("ok") is not True:
            raise ResultDeliveryError("APatch evidence publication could not be queued")
        queued = published.get("delivery")
        if (
            published.get("plan_hash") != publication["plan_hash"]
            or not isinstance(queued, dict)
            or queued.get("status") != "queued"
        ):
            raise ResultDeliveryError("APatch evidence publication differs from the plan")
        synchronized = self._api.sync_governed_work(
            str(self.workspace),
            request_key_provider=provider,
        )
        if not isinstance(synchronized, dict) or not self._evidence_acknowledged(
            queued, plan
        ):
            raise ResultDeliveryError("Cowork did not acknowledge the APatch evidence")

        config = self._delivery.load_config(str(self.workspace))
        platform_url = str(config.get("platform_url") or "").rstrip("/")
        client_subject = str(config.get("client_id") or "")
        expected_key_id = str(config.get("service_request_key_id") or "")
        if (
            platform_url != plan["platform_origin"]
            or client_subject != plan["client_subject"]
            or self._transport.service_request_key_id(provider) != expected_key_id
        ):
            raise ResultDeliveryError("Cowork connection changed after preview")

        base_path = (
            f"/api/internal/client/project-groups/{record['project_group_id']}"
            f"/work-items/{record['work_item_id']}/apatch-studio/releases"
        )
        common = {
            "subject": client_subject,
            "tenant_id": record["tenant_id"],
            "expected_work_item_hash": plan["work_item_hash"],
            "expected_work_item_authority_version": plan["authority_version"],
            "expected_work_program": {
                "program_id": plan["work_program_id"],
                "program_hash": plan["work_program_hash"],
            },
        }
        create = {
            **common,
            "outcome_ref": plan["result"]["outcome_ref"],
            "evidence_bundle_id": plan["evidence"]["bundle_id"],
            "idempotency_key": (
                f"studio-result:create:{record['intent_id']}:{plan['plan_hash']}"
            ),
        }
        draft = self._post_result(
            platform_url=platform_url,
            path=base_path,
            body=create,
            config=config,
            provider=provider,
            expected_state="draft",
        )
        submit_path = f"{base_path}/{draft['release_id']}/submit"
        submitted = self._post_result(
            platform_url=platform_url,
            path=submit_path,
            body={
                **common,
                "idempotency_key": (
                    f"studio-result:submit:{record['intent_id']}:{plan['plan_hash']}"
                ),
            },
            config=config,
            provider=provider,
            expected_state="submitted",
        )
        return submitted

    def _evidence_acknowledged(
        self, queued: Mapping[str, Any], plan: Mapping[str, Any]
    ) -> bool:
        entry_id = str(queued.get("entry_id") or "")
        request_hash = str(queued.get("request_hash") or "")
        if not re.fullmatch(r"apgwo_[0-9a-f]{32}", entry_id) or not _HASH_RE.fullmatch(
            request_hash
        ):
            return False
        try:
            entry_path, entry = self._delivery._find_outbox_entry(
                str(self.workspace), entry_id
            )
            ack_path = self._delivery._ack_path(entry_path)
            if not ack_path.is_file():
                return False
            ack = self._delivery._read_document(ack_path)
            bundle = entry["payload"]["evidence_bundle"]
            evidence = plan["evidence"]
            expected_endpoint = (
                f"/api/internal/project-groups/{plan['project_group_id']}"
                "/governed-work/evidence-admissions"
            )
            return (
                entry.get("schema") == "apatch.governed-work-outbox-entry.v1"
                and entry.get("entry_id") == entry_id
                and entry.get("request_hash") == request_hash
                and entry.get("command") == "evidence_admission"
                and entry.get("tenant_id") == plan["tenant_id"]
                and entry.get("project_group_id") == plan["project_group_id"]
                and entry.get("client_id") == plan["client_subject"]
                and entry.get("endpoint") == expected_endpoint
                and entry.get("idempotency_key")
                == f"evidence-admission:{evidence['bundle_id']}"
                and bundle.get("bundle_id") == evidence["bundle_id"]
                and self._domain.document_hash(bundle) == evidence["bundle_hash"]
                and ack.get("schema") == "apatch.governed-work-ack.v1"
                and ack.get("entry_id") == entry_id
                and ack.get("request_hash") == request_hash
                and ack.get("command") == "evidence_admission"
                and ack.get("resource_id") == evidence["bundle_id"]
                and ack.get("resource_hash") == evidence["bundle_hash"]
                and _HASH_RE.fullmatch(str(ack.get("platform_receipt_hash") or ""))
                and type(ack.get("projection_cursor")) is int
                and ack["projection_cursor"] >= 0
            )
        except (AttributeError, KeyError, OSError, TypeError, ValueError):
            return False

    def _workspace_key_provider(self) -> Any:
        identity = self._identity_loader(str(self.workspace))
        provider = getattr(identity, "key_provider", None) if identity else None
        try:
            public_key = provider.get_public_key()
        except Exception as exc:
            raise ResultDeliveryError(
                "selected workspace APatch signing identity is unavailable"
            ) from exc
        if not isinstance(public_key, bytes) or len(public_key) != 32:
            raise ResultDeliveryError(
                "selected workspace APatch signing identity is invalid"
            )
        return provider

    def _post_result(
        self,
        *,
        platform_url: str,
        path: str,
        body: Mapping[str, Any],
        config: Mapping[str, Any],
        provider: Any,
        expected_state: str,
    ) -> dict[str, Any]:
        raw = self._domain.canonical_bytes(dict(body))
        try:
            signed = self._transport.signed_service_headers(
                str(self.workspace),
                method="POST",
                path=path,
                raw_body=raw,
                tenant_id=str(body["tenant_id"]),
                subject=str(body["subject"]),
                expected_key_id=str(config["service_request_key_id"]),
                key_provider=provider,
            )
        except Exception as exc:
            raise ResultDeliveryError("APatch could not sign the Cowork result request") from exc
        client = self._http_client
        close = False
        if client is None:
            httpx_module = getattr(self._delivery, "httpx", None)
            if httpx_module is None:
                raise ResultDeliveryError("Cowork result transport is unavailable")
            client = httpx_module.Client(timeout=20.0)
            close = True
        try:
            response = client.post(
                platform_url + path,
                content=raw,
                headers={
                    "Content-Type": "application/json",
                    "Idempotency-Key": str(body["idempotency_key"]),
                    "X-Apatch-Client-Id": str(config["client_id"]),
                    **signed,
                },
            )
            if int(response.status_code) not in {200, 201}:
                raise ResultDeliveryError("Cowork rejected the result delivery")
            receipt = response.json()
            return self._result_receipt(
                receipt,
                expected_group_id=path.split("/project-groups/", 1)[1].split("/", 1)[0],
                expected_work_item_id=path.split("/work-items/", 1)[1].split("/", 1)[0],
                expected_state=expected_state,
            )
        except ResultDeliveryError:
            raise
        except Exception as exc:
            raise ResultDeliveryError("Cowork result delivery is unavailable") from exc
        finally:
            if close:
                client.close()

    @staticmethod
    def _result_receipt(
        raw: Any,
        *,
        expected_group_id: str,
        expected_work_item_id: str,
        expected_state: str,
    ) -> dict[str, Any]:
        if not isinstance(raw, dict) or set(raw) != {
            "schema",
            "project_group_id",
            "work_item_id",
            "release_id",
            "release_hash",
            "state",
            "available_actions",
        }:
            raise ResultDeliveryError("Cowork returned an invalid result receipt")
        actions = raw.get("available_actions")
        release_id = str(raw.get("release_id") or "")
        if (
            raw.get("schema") != "trustchain.apatch-studio.result-delivery.v1"
            or raw.get("project_group_id") != expected_group_id
            or raw.get("work_item_id") != expected_work_item_id
            or not re.fullmatch(r"^tcwr_[0-9a-f]{32}$", release_id)
            or not _HASH_RE.fullmatch(str(raw.get("release_hash") or ""))
            or raw.get("state") != expected_state
            or not isinstance(actions, dict)
            or set(actions) != {"submit"}
            or not isinstance(actions.get("submit"), bool)
            or actions["submit"] is not (expected_state == "draft")
        ):
            raise ResultDeliveryError("Cowork returned an invalid result receipt")
        return dict(raw)

    def _prepare(
        self,
        record: Mapping[str, Any],
        *,
        relative_path: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        exact = self._accepted_record(record)
        result = self._read_result(relative_path)
        (
            evidence_binding_id,
            current_work_item_hash,
            current_authority_version,
        ) = self._evidence_binding(exact)
        built = self._api.build_governed_evidence(
            str(self.workspace),
            binding_id=evidence_binding_id,
            queue_for_admission=False,
        )
        if not isinstance(built, dict):
            raise ResultDeliveryError("local APatch evidence could not be prepared")
        build_error = str(built.get("error") or "")
        reused_persisted_evidence = (
            built.get("error_type") == "GOVERNED_WORK_INVALID"
            and build_error.startswith(
                "immutable id is already bound to another envelope:"
            )
        )
        if build_error and not reused_persisted_evidence:
            raise ResultDeliveryError("local APatch evidence could not be prepared")
        evidence_bundle_id: str | None = None
        if not reused_persisted_evidence:
            evidence_bundle = built.get("evidence_bundle")
            if not isinstance(evidence_bundle, dict):
                raise ResultDeliveryError("local APatch evidence bundle is unavailable")
            evidence_bundle_id = str(evidence_bundle.get("bundle_id") or "")

        previewed = self._api.preview_governed_evidence_publication(
            str(self.workspace),
            binding_id=evidence_binding_id,
        )
        if not isinstance(previewed, dict) or previewed.get("ok") is not True:
            raise ResultDeliveryError("local APatch disclosure preview is unavailable")
        publication = self._publication_plan(previewed.get("plan"))
        evidence_ref = publication["evidence_bundle_ref"]
        if (
            evidence_bundle_id is not None
            and evidence_bundle_id != evidence_ref["bundle_id"]
        ):
            raise ResultDeliveryError("APatch evidence changed while preparing the preview")
        if (
            publication["tenant_id"] != exact["tenant_id"]
            or publication["project_group_id"] != exact["project_group_id"]
        ):
            raise ResultDeliveryError("APatch evidence scope differs from the assignment")

        body = {
            "schema": RESULT_PLAN_SCHEMA,
            "intent_id": exact["intent_id"],
            "platform_origin": publication["platform_origin"],
            "client_subject": publication["client_subject"],
            "tenant_id": exact["tenant_id"],
            "project_group_id": exact["project_group_id"],
            "work_item_id": exact["work_item_id"],
            "work_item_hash": current_work_item_hash,
            "authority_version": current_authority_version,
            "work_program_id": exact["work_program_id"],
            "work_program_hash": exact["work_program_hash"],
            "source_binding_id": evidence_binding_id,
            "result": {
                "relative_path": result["relative_path"],
                "outcome_ref": result["outcome_ref"],
                "size_bytes": result["size_bytes"],
                "content_shared": False,
            },
            "evidence": {
                "bundle_id": evidence_ref["bundle_id"],
                "bundle_hash": evidence_ref["bundle_hash"],
                "claimed_active_seconds": publication["timesheet_ref"][
                    "claimed_active_seconds"
                ],
                "publication_plan_hash": publication["plan_hash"],
            },
            "connection_generation": publication["connection_generation"],
        }
        return {**body, "plan_hash": self._domain.value_hash(body)}, publication

    def _evidence_binding(
        self,
        exact: Mapping[str, Any],
    ) -> tuple[str, str, int]:
        selected = str(exact["cowork_source_binding_id"])
        if selected.startswith("tcpsb_"):
            return (
                selected,
                str(exact["work_item_hash"]),
                int(exact["authority_version"]),
            )

        root = self._domain.governed_work_root(str(self.workspace))
        canonical_path = root / "work_item_execution_bindings" / f"{selected}.json"
        try:
            raw = json.loads(canonical_path.read_text(encoding="utf-8"))
            config = self._delivery.load_config(str(self.workspace))
            validator = self._work_item_acceptance
            if validator is None:
                from apatch import work_item_acceptance as validator
            canonical = validator.validate_binding(
                raw,
                trusted_keys=config["binding_authority_keys"],
            )
        except Exception as exc:
            raise ResultDeliveryError(
                "local Cowork work-item binding could not be verified"
            ) from exc

        expected = {
            "binding_id": selected,
            "tenant_id": exact["tenant_id"],
            "project_group_id": exact["project_group_id"],
            "work_item_id": exact["work_item_id"],
            "accepted_work_item_hash": exact["work_item_hash"],
            "accepted_authority_version": exact["authority_version"],
            "work_program_id": exact["work_program_id"],
            "work_program_hash": exact["work_program_hash"],
            "intent_id": exact["intent_id"],
            "change_id": exact["cowork_change_id"],
        }
        if any(canonical.get(field) != value for field, value in expected.items()):
            raise ResultDeliveryError(
                "local Cowork work-item binding does not match the assignment"
            )
        current_work_item_hash = canonical.get("current_work_item_hash")
        current_authority_version = canonical.get("current_authority_version")
        if (
            not isinstance(current_work_item_hash, str)
            or not _HASH_RE.fullmatch(current_work_item_hash)
            or isinstance(current_authority_version, bool)
            or not isinstance(current_authority_version, int)
            or current_authority_version < 1
        ):
            raise ResultDeliveryError(
                "local Cowork work-item binding has invalid current task pins"
            )

        source_bindings: list[dict[str, Any]] = []
        source_directory = root / "bindings"
        if source_directory.is_dir():
            for path in sorted(source_directory.glob("tcpsb_*.json")):
                try:
                    candidate = self._domain.load_project_source_binding(
                        str(self.workspace), path.stem
                    )
                except Exception as exc:
                    raise ResultDeliveryError(
                        "local APatch source binding could not be verified"
                    ) from exc
                if all(
                    candidate.get(field) == canonical.get(field)
                    for field in (
                        "tenant_id",
                        "project_group_id",
                        "work_program_id",
                        "work_program_hash",
                        "change_id",
                        "change_hash",
                        "actor_ref",
                    )
                ):
                    source_bindings.append(candidate)
        if len(source_bindings) != 1:
            raise ResultDeliveryError(
                "assignment does not resolve to one exact APatch source binding"
            )
        return (
            str(source_bindings[0]["binding_id"]),
            current_work_item_hash,
            current_authority_version,
        )

    def _read_result(self, relative_path: str) -> dict[str, Any]:
        if (
            not isinstance(relative_path, str)
            or not relative_path
            or relative_path != relative_path.strip()
            or "\x00" in relative_path
            or "\\" in relative_path
        ):
            raise ResultDeliveryError("result path must be a workspace-relative file")
        relative = Path(relative_path)
        if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
            raise ResultDeliveryError("result path must be a workspace-relative file")
        candidate = self.workspace.joinpath(*relative.parts)
        cursor = self.workspace
        try:
            for part in relative.parts:
                cursor = cursor / part
                if cursor.is_symlink():
                    raise ResultDeliveryError("result path cannot contain a symlink")
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(self.workspace)
        except ResultDeliveryError:
            raise
        except (OSError, ValueError) as exc:
            raise ResultDeliveryError("result file is unavailable") from exc

        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(resolved, flags)
        except OSError as exc:
            raise ResultDeliveryError("result file is unavailable") from exc
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise ResultDeliveryError("result must be a regular file")
            if metadata.st_size <= 0 or metadata.st_size > MAX_RESULT_BYTES:
                raise ResultDeliveryError("result file size is outside the allowed range")
            digest = hashlib.sha256()
            read_bytes = 0
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                read_bytes += len(chunk)
                if read_bytes > MAX_RESULT_BYTES:
                    raise ResultDeliveryError("result file size is outside the allowed range")
                digest.update(chunk)
            if read_bytes != metadata.st_size:
                raise ResultDeliveryError("result file changed while it was read")
        finally:
            os.close(descriptor)
        return {
            "relative_path": relative.as_posix(),
            "outcome_ref": "sha256:" + digest.hexdigest(),
            "size_bytes": read_bytes,
        }

    @staticmethod
    def _accepted_record(record: Mapping[str, Any]) -> dict[str, Any]:
        candidate = dict(record)
        required_text = (
            ("intent_id", _INTENT_RE),
            ("project_group_id", _GROUP_RE),
            ("work_item_id", _ITEM_RE),
            ("work_item_hash", _HASH_RE),
            ("work_program_id", _PROGRAM_RE),
            ("work_program_hash", _HASH_RE),
            ("cowork_change_id", _CHANGE_RE),
            ("cowork_source_binding_id", _BINDING_RE),
        )
        if (
            candidate.get("status") != "consumed"
            or candidate.get("cowork_status") != "source_bound"
            or not isinstance(candidate.get("tenant_id"), str)
            or isinstance(candidate.get("authority_version"), bool)
            or not isinstance(candidate.get("authority_version"), int)
            or candidate["authority_version"] < 1
        ):
            raise ResultDeliveryError("assignment is not ready for Cowork result delivery")
        for field, pattern in required_text:
            if not isinstance(candidate.get(field), str) or not pattern.fullmatch(
                candidate[field]
            ):
                raise ResultDeliveryError("assignment is not ready for Cowork result delivery")
        return candidate

    @staticmethod
    def _result_plan(raw: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(raw, Mapping):
            raise ResultDeliveryError("result delivery plan is invalid")
        candidate = dict(raw)
        if set(candidate) != {
            "schema",
            "intent_id",
            "platform_origin",
            "client_subject",
            "tenant_id",
            "project_group_id",
            "work_item_id",
            "work_item_hash",
            "authority_version",
            "work_program_id",
            "work_program_hash",
            "source_binding_id",
            "result",
            "evidence",
            "connection_generation",
            "plan_hash",
        }:
            raise ResultDeliveryError("result delivery plan is invalid")
        if candidate.get("schema") != RESULT_PLAN_SCHEMA:
            raise ResultDeliveryError("result delivery plan is invalid")
        result = candidate.get("result")
        evidence = candidate.get("evidence")
        if (
            not isinstance(result, dict)
            or set(result)
            != {"relative_path", "outcome_ref", "size_bytes", "content_shared"}
            or result.get("content_shared") is not False
            or not isinstance(evidence, dict)
            or set(evidence)
            != {
                "bundle_id",
                "bundle_hash",
                "claimed_active_seconds",
                "publication_plan_hash",
            }
            or not _HASH_RE.fullmatch(str(candidate.get("plan_hash") or ""))
        ):
            raise ResultDeliveryError("result delivery plan is invalid")
        return candidate

    @staticmethod
    def _publication_plan(raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict) or set(raw) != _PUBLICATION_PLAN_KEYS:
            raise ResultDeliveryError("APatch disclosure plan is invalid")
        evidence = raw.get("evidence_bundle_ref")
        timesheet = raw.get("timesheet_ref")
        if (
            not isinstance(evidence, dict)
            or set(evidence) != _EVIDENCE_REF_KEYS
            or not _BUNDLE_RE.fullmatch(str(evidence.get("bundle_id") or ""))
            or not _HASH_RE.fullmatch(str(evidence.get("bundle_hash") or ""))
            or not isinstance(timesheet, dict)
            or set(timesheet) != _TIMESHEET_REF_KEYS
            or isinstance(timesheet.get("claimed_active_seconds"), bool)
            or not isinstance(timesheet.get("claimed_active_seconds"), int)
            or timesheet["claimed_active_seconds"] < 0
            or not _HASH_RE.fullmatch(str(raw.get("plan_hash") or ""))
        ):
            raise ResultDeliveryError("APatch disclosure plan is invalid")
        return dict(raw)
