"""Bridge signed Cowork assignments into the APatch governed-work runtime."""

from __future__ import annotations

import hashlib
import json
import inspect
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Protocol
from threading import RLock

from pydantic import BaseModel, ConfigDict, Field
from apatch.trust_identity import workspace_identity_scope


ROUND_TRIP_SYNC_ROUNDS = 2


def _load_exact_workspace_identity(workspace_root: str) -> Any | None:
    """Load only the selected workspace signer, ignoring Studio process identity."""

    from apatch import trust_identity
    from apatch.workspace_identity import load_workspace_identity

    record = load_workspace_identity(workspace_root)
    if record is None:
        return None
    try:
        if record.get("key_backend") == "command":
            provider = trust_identity.CommandKeyProvider(
                record["sign_cmd"],
                record["public_key"],
                key_id=record["agent_id"],
            )
        elif record.get("key_backend") == "pem":
            provider = trust_identity._PemKeyProvider(
                record["key"],
                key_id=record["agent_id"],
            )
        else:
            return None
    except Exception:
        return None
    return SimpleNamespace(key_provider=provider)


class GovernedWorkGatewayError(RuntimeError):
    """A content-safe failure while proving Cowork acceptance and source binding."""

    def __init__(self, message, *, code="cowork_acceptance_incomplete"):
        super().__init__(message)
        self.code = code


class EvidencePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    binding_id: str = Field(pattern=r"^tcpsb_[0-9a-f]{32}$")
    evidence_bundle_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")


class EvidencePublicationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    plan: dict[str, Any]
    confirmation: str = Field(min_length=1, max_length=80)


class GovernedWorkGateway(Protocol):
    @property
    def connected(self) -> bool: ...

    def accept_and_bind(
        self,
        proposal: Mapping[str, Any],
        *,
        spec_id: str,
    ) -> dict[str, str]: ...


class APatchGovernedWorkGateway:
    """Require APatch's two signed Cowork acknowledgements before local work."""

    def __init__(
        self,
        workspace: str | Path,
        *,
        api: Any | None = None,
        domain: Any | None = None,
        delivery: Any | None = None,
        work_item_acceptance: Any | None = None,
        identity_loader: Any | None = None,
    ):
        self.workspace = Path(workspace).expanduser().resolve()
        if (
            api is None
            or domain is None
            or delivery is None
            or work_item_acceptance is None
        ):
            from apatch import governed_work as runtime_domain
            from apatch import governed_work_delivery as runtime_delivery
            from apatch import governed_work_mcp as runtime_api
            from apatch import work_item_acceptance as runtime_work_item_acceptance

            api = api or runtime_api
            domain = domain or runtime_domain
            delivery = delivery or runtime_delivery
            work_item_acceptance = (
                work_item_acceptance or runtime_work_item_acceptance
            )
        if identity_loader is None:
            identity_loader = _load_exact_workspace_identity
        self._api = api
        self._domain = domain
        self._delivery = delivery
        self._work_item_acceptance = work_item_acceptance
        self._identity_loader = identity_loader
        self._publication_lock = RLock()
        self._publication_selection = None

    def _workspace_key_provider(self) -> Any:
        # Use the same non-mutating native sharing gate as the public sync API.
        # A config file or cached binding is not permission after disconnect.
        from apatch import governed_work_mcp as runtime_api
        try:
            config = self._delivery.load_config(str(self.workspace))
            runtime_api._assert_sharing_available(str(self.workspace), config)
        except Exception as exc:
            raise GovernedWorkGatewayError("Cowork connection is unavailable or disconnected", code="cowork_connection_required") from exc
        identity = self._identity_loader(str(self.workspace))
        provider = getattr(identity, "key_provider", None) if identity else None
        if provider is None:
            raise GovernedWorkGatewayError(
                "selected workspace has no enrolled APatch signing identity"
            )
        try:
            public_key = provider.get_public_key()
        except Exception as exc:
            raise GovernedWorkGatewayError(
                "selected workspace APatch signing identity is unavailable"
            ) from exc
        if not isinstance(public_key, bytes) or len(public_key) != 32:
            raise GovernedWorkGatewayError(
                "selected workspace APatch signing identity is invalid"
            )
        config = self._delivery.load_config(str(self.workspace))
        expected_key_id = str(config.get("service_request_key_id") or "")
        actual_key_id = "sha256:" + hashlib.sha256(public_key).hexdigest()
        if expected_key_id != actual_key_id:
            raise GovernedWorkGatewayError(
                "selected workspace APatch signing identity does not match "
                "the configured Cowork service identity"
            )
        return provider

    @property
    def connected(self) -> bool:
        return self._delivery.config_path(str(self.workspace)).is_file()

    def accept_and_bind(
        self,
        proposal: Mapping[str, Any],
        *,
        spec_id: str,
    ) -> dict[str, str]:
        if not self.connected:
            raise GovernedWorkGatewayError("Cowork connection is not configured")
        intent_id = str(proposal.get("intent_id") or "")
        work_item_id = str(proposal.get("work_item_id") or "")
        authority_version = proposal.get("authority_version")
        if (
            not intent_id
            or not work_item_id
            or isinstance(authority_version, bool)
            or not isinstance(authority_version, int)
        ):
            raise GovernedWorkGatewayError("execution proposal identity is incomplete")

        request_key_provider = self._workspace_key_provider()
        accepted = self._api.accept_execution_proposal(
            str(self.workspace),
            proposal=dict(proposal),
            confirmation=f"{work_item_id}:{authority_version}",
            spec_id=spec_id,
            purpose=(
                "Execute the owner-selected SPEC for Cowork work item "
                f"{work_item_id} under execution intent {intent_id}"
            ),
            queue_source_binding=False,
            request_key_provider=request_key_provider,
        )
        if accepted.get("ok") is not True or accepted.get("work_started") is not False:
            raise GovernedWorkGatewayError("Cowork did not accept the exact assignment")
        change = accepted.get("change")
        change_hash = accepted.get("change_hash")
        acceptance = accepted.get("proposal_acceptance")
        if not isinstance(change, dict) or not isinstance(change_hash, str) or not isinstance(acceptance, dict):
            raise GovernedWorkGatewayError("APatch returned no exact native acceptance")
        for field in ("tenant_id", "project_group_id", "work_program_id", "work_program_hash"):
            if change.get(field) != proposal.get(field):
                raise GovernedWorkGatewayError("APatch Change scope does not match the assignment")
        if self._domain.document_hash(change) != change_hash:
            raise GovernedWorkGatewayError("APatch Change hash does not match its document")
        bound = self.refresh_canonical_binding(change, acceptance)
        return {
            "status": "source_bound",
            "change_id": str(change["change_id"]),
            "change_hash": change_hash,
            "source_binding_id": str(bound["binding_id"]),
            "source_binding_hash": self._domain.document_hash(bound),
        }

    def refresh_canonical_binding(self, change, acceptance):
        """A new signed HTTP exchange, never outbox/cache as current authority."""
        import httpx
        from apatch import governed_work_transport as transport

        if not self.connected:
            raise GovernedWorkGatewayError("Cowork connection is not configured")
        provider = self._workspace_key_provider()
        config = self._delivery.load_config(str(self.workspace))
        public = provider.get_public_key()
        actor_keys = {self._domain.signer_key_id(provider): public}
        exact_change = self._domain.validate_change(change, trusted_actor_keys=actor_keys)
        exact_acceptance = self._work_item_acceptance.validate_acceptance(acceptance)
        self._domain.verify_document_signature(exact_acceptance, actor_keys)
        if exact_acceptance["signature"]["key_id"] != exact_change["actor_key_id"]:
            raise GovernedWorkGatewayError("acceptance and Change identities differ")
        expected = {
            "tenant_id": exact_change["tenant_id"],
            "project_group_id": exact_change["project_group_id"],
            "work_program_id": exact_change["work_program_id"],
            "work_program_hash": exact_change["work_program_hash"],
            "change_id": exact_change["change_id"],
            "change_hash": self._domain.document_hash(exact_change),
        }
        if any(exact_acceptance[key] != value for key, value in expected.items()):
            raise GovernedWorkGatewayError("acceptance and Change scopes differ")
        group, item = exact_acceptance["project_group_id"], exact_acceptance["work_item_id"]
        path = f"/api/internal/client/project-groups/{group}/work-items/{item}/apatch-studio/acceptances"
        raw = self._domain.canonical_bytes({
            "subject": config["client_id"], "tenant_id": exact_acceptance["tenant_id"],
            "change": exact_change, "proposal_acceptance": exact_acceptance,
            "idempotency_key": f"work-item-acceptance:{exact_change['change_id']}",
        })
        headers = {"Content-Type": "application/json", "X-Apatch-Client-Id": config["client_id"],
            "Idempotency-Key": f"work-item-acceptance:{exact_change['change_id']}",
            **transport.signed_service_headers(str(self.workspace), method="POST", path=path,
                raw_body=raw, tenant_id=exact_acceptance["tenant_id"], subject=config["client_id"],
                expected_key_id=config["service_request_key_id"], key_provider=provider)}
        try:
            with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
                response = client.post(config["platform_url"] + path, content=raw, headers=headers)
            reply = response.json()
        except Exception as exc:
            raise GovernedWorkGatewayError("current canonical acknowledgement unavailable") from exc
        if response.status_code not in {200, 201}:
            if isinstance(reply, dict) and reply.get("detail") == "exact_contract_required":
                raise GovernedWorkGatewayError("this task requires its agreed exact contract", code="exact_contract_required")
            raise GovernedWorkGatewayError("current canonical acknowledgement rejected")
        result = self._work_item_acceptance.store_binding(str(self.workspace), binding=reply,
            acceptance=exact_acceptance, change=exact_change, trusted_keys=config["binding_authority_keys"])
        return result["binding"]

    def guard_execution(self, request, execution_context, sdd_execution, *, stage):
        """Revalidate external authority at start and immediately before Popen."""
        if execution_context is None:
            return
        from apatch import execution_proposal

        root = self._domain.governed_work_root(str(self.workspace)) / "proposal_acceptances"
        matches = []
        if root.is_dir():
            for path in sorted(root.glob("apchg_*.json")):
                acceptance = self._work_item_acceptance.validate_acceptance(json.loads(path.read_text(encoding="utf-8")))
                if acceptance["intent_id"] != execution_context.intent_id:
                    continue
                change = self._domain.load_change(str(self.workspace), acceptance["change_id"])
                if (change["spec_id"] == request.spec_id and acceptance["proposal_document_hash"] == execution_context.document_hash
                        and acceptance["proposal_envelope_hash"] == execution_context.envelope_hash
                        and acceptance["work_item_hash"] == execution_context.work_item_hash
                        and acceptance["authority_version"] == execution_context.authority_version
                        and all(acceptance[field] == getattr(execution_context, field)
                            for field in ("tenant_id", "project_group_id", "work_item_id", "work_program_id", "work_program_hash"))):
                    matches.append((change, acceptance))
        if len(matches) != 1:
            raise GovernedWorkGatewayError("one exact native acceptance is required")
        self.refresh_canonical_binding(*matches[0])

    def _publication_context(self):
        """Pin the selected directory, current connection and physical signer."""
        provider = self._workspace_key_provider()
        config = self._delivery.load_config(str(self.workspace))
        # The older public publication API has no key-provider argument.
        # Never let its ambient signer silently replace the selected one.
        native_provider = self._domain._load_local_provider(str(self.workspace))
        if native_provider.get_public_key() != provider.get_public_key():
            raise GovernedWorkGatewayError(
                "The SDK identity differs from the selected workspace identity",
                code="publication_identity_mismatch",
            )
        if self.workspace.resolve() != self.workspace:
            raise GovernedWorkGatewayError(
                "The selected workspace changed", code="publication_context_changed"
            )
        state = self.workspace.stat()
        return {
            "workspace_id": hashlib.sha256(str(self.workspace).encode("utf-8")).hexdigest()[:32],
            "directory_identity": [state.st_dev, state.st_ino],
            "connection_generation": self._domain.value_hash(config),
            "service_request_key_id": config["service_request_key_id"],
        }, provider

    def _require_publication_context(self, expected):
        try:
            current, provider = self._publication_context()
            if current != expected:
                raise ValueError("publication context changed")
            return provider
        except (GovernedWorkGatewayError, OSError, ValueError):
            self._publication_selection = None
            raise GovernedWorkGatewayError(
                "The selected workspace or Cowork account changed; preview again",
                code="publication_context_changed",
            ) from None

    def preview_evidence(self, *, binding_id, evidence_bundle_hash=None):
        """Read only one content-free native plan; replace prior selection."""
        with self._publication_lock, workspace_identity_scope(str(self.workspace)):
            self._publication_selection = None
            try:
                context, _provider = self._publication_context()
                preview = self._api.preview_governed_evidence_publication
                params = inspect.signature(preview).parameters
                accepts_exact = ('evidence_bundle_hash' in params or
                    any(param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values()))
                # Older supported Core selects exactly one signed bundle per
                # source binding. It has no hash selector; the returned plan
                # must still equal the requested hash below, before consent.
                if evidence_bundle_hash is not None and not accepts_exact and set(params) != {'target_dir', 'binding_id'}:
                    raise ValueError('unsupported evidence preview ABI')
                result = preview(str(self.workspace), binding_id=binding_id,
                    **({'evidence_bundle_hash': evidence_bundle_hash} if evidence_bundle_hash is not None and accepts_exact else {}))
                if result.get("ok") is not True:
                    raise GovernedWorkGatewayError(
                        "The selected signed evidence is unavailable or invalid",
                        code="publication_evidence_invalid",
                    )
                from apatch import governed_work_mcp as runtime_api

                plan = runtime_api._validated_share_plan(result["plan"])
                body = {key: value for key, value in plan.items() if key != "plan_hash"}
                if ((evidence_bundle_hash is not None and plan["evidence_bundle_ref"]["bundle_hash"] != evidence_bundle_hash)
                        or plan["plan_hash"] != self._domain.value_hash(body)
                        or plan["connection_generation"] != context["connection_generation"]):
                    raise GovernedWorkGatewayError(
                        "The native publication plan is invalid",
                        code="publication_evidence_invalid",
                    )
                self._require_publication_context(context)
                # Do not add fields to the closed Core v1 share-plan schema.
                selected = json.loads(self._domain.canonical_bytes(plan))
                self._publication_selection = (context, selected)
                return {"ok": True, "operation": "preview_evidence_publication", "plan": selected}
            except GovernedWorkGatewayError:
                raise
            except (OSError, TypeError, ValueError):
                raise GovernedWorkGatewayError(
                    "The selected signed evidence is unavailable or invalid",
                    code="publication_evidence_invalid",
                ) from None

    def publish_evidence(self, *, plan, confirmation):
        """Publish only the previewed selection; ACK is never customer review."""
        with self._publication_lock, workspace_identity_scope(str(self.workspace)):
            selection = self._publication_selection
            if selection is None:
                raise GovernedWorkGatewayError(
                    "Preview the exact evidence selection before publishing",
                    code="publication_preview_required",
                )
            context, selected = selection
            if (self._domain.canonical_bytes(plan) != self._domain.canonical_bytes(selected)
                    or confirmation != "publish:" + selected["plan_hash"]):
                raise GovernedWorkGatewayError(
                    "Confirm exactly the current selected evidence plan",
                    code="publication_confirmation_mismatch",
                )
            provider = self._require_publication_context(context)
            self._selected_delivery_contract()
            published = self._api.publish_governed_evidence(
                str(self.workspace), plan=selected, confirmation=confirmation
            )
            if published.get("ok") is not True:
                raise GovernedWorkGatewayError(
                    "The current signed evidence no longer matches its preview",
                    code="publication_evidence_invalid",
                )
            self._require_publication_context(context)
            delivery = published["delivery"]
            entry_id = delivery["entry_id"]
            request_hash = delivery["request_hash"]
            synchronized = self._deliver_selected_evidence(
                selected=selected, context=context, provider=provider,
                entry_id=entry_id, request_hash=request_hash,
            )
            # A late result from an old account/workspace cannot become success
            # for the new one. Keep the immutable queued/ACK history intact.
            self._require_publication_context(context)
            selected_errors = [error["code"] for error in synchronized.get("errors", [])
                if error.get("entry_id") == entry_id and isinstance(error.get("code"), str)]
            if synchronized.get("delivered") == 1 and not selected_errors:
                status, pending = "acknowledged", 0
            elif delivery.get("pending") is False and not selected_errors:
                status, pending = "not_checked_this_request", 0
            else:
                status, pending = "queued", 1
            return {
                "ok": True, "operation": "publish_evidence", "plan_hash": selected["plan_hash"],
                "delivery": {"status": "queued", "entry_id": entry_id, "request_hash": request_hash},
                "synchronization": {"status": status, "delivered": 1 if status == "acknowledged" else 0,
                    "pending": pending, "error_codes": selected_errors},
                "customer_decision": "not_requested",
            }

    def _selected_delivery_contract(self):
        from apatch_studio.selected_governed_work_delivery import qualify_native_delivery, SelectedDeliveryError
        try:
            qualify_native_delivery()
        except SelectedDeliveryError as error:
            raise GovernedWorkGatewayError(str(error), code=error.code) from None

    def _deliver_selected_evidence(self, *, selected, context, provider, entry_id, request_hash):
        from apatch_studio.selected_governed_work_delivery import dispatch_selected, SelectedDeliveryError
        scope = {"command":"evidence_admission", "tenant_id":selected["tenant_id"],
            "project_group_id":selected["project_group_id"], "client_id":selected["client_subject"]}
        try:
            return dispatch_selected(str(self.workspace),entry_id=entry_id,request_hash=request_hash,
                key_provider=provider,expected_scope=scope,
                context_guard=lambda: self._require_publication_context(context))
        except SelectedDeliveryError as error:
            raise GovernedWorkGatewayError(str(error),code=error.code) from None

    def _find_exact_binding(
        self,
        change: Mapping[str, Any],
        change_hash: str,
        proposal: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        root = self._domain.governed_work_root(str(self.workspace))
        legacy_directory = root / "bindings"
        if legacy_directory.is_dir():
            for path in sorted(legacy_directory.glob("tcpsb_*.json")):
                binding = self._domain.load_project_source_binding(
                    str(self.workspace), path.stem
                )
                if (
                    binding.get("change_id") == change.get("change_id")
                    and binding.get("change_hash") == change_hash
                    and binding.get("tenant_id") == change.get("tenant_id")
                    and binding.get("project_group_id") == change.get("project_group_id")
                    and binding.get("work_program_id") == change.get("work_program_id")
                    and binding.get("work_program_hash") == change.get("work_program_hash")
                    and binding.get("spec_id") == change.get("spec_id")
                    and binding.get("spec_hash") == change.get("spec_hash")
                ):
                    return binding

        canonical_directory = root / "work_item_execution_bindings"
        if not canonical_directory.is_dir():
            return None
        config = self._delivery.load_config(str(self.workspace))
        for path in sorted(canonical_directory.glob("tcawieb_*.json")):
            raw = json.loads(path.read_text(encoding="utf-8"))
            binding = self._work_item_acceptance.validate_binding(
                raw,
                trusted_keys=config["binding_authority_keys"],
            )
            if (
                binding.get("change_id") == change.get("change_id")
                and binding.get("change_hash") == change_hash
                and binding.get("tenant_id") == change.get("tenant_id")
                and binding.get("project_group_id") == change.get("project_group_id")
                and binding.get("work_program_id") == change.get("work_program_id")
                and binding.get("work_program_hash") == change.get("work_program_hash")
                and binding.get("work_item_id") == proposal.get("work_item_id")
                and binding.get("accepted_work_item_hash")
                == proposal.get("work_item_hash")
                and binding.get("accepted_authority_version")
                == proposal.get("authority_version")
                and binding.get("intent_id") == proposal.get("intent_id")
            ):
                return binding
        return None
