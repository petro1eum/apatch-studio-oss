"""Bridge signed Cowork assignments into the APatch governed-work runtime."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol


ROUND_TRIP_SYNC_ROUNDS = 2


class GovernedWorkGatewayError(RuntimeError):
    """A content-safe failure while proving Cowork acceptance and source binding."""


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
            from apatch.trust_identity import load_local_identity

            identity_loader = load_local_identity
        self._api = api
        self._domain = domain
        self._delivery = delivery
        self._work_item_acceptance = work_item_acceptance
        self._identity_loader = identity_loader

    def _workspace_key_provider(self) -> Any:
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
            queue_source_binding=True,
            request_key_provider=request_key_provider,
        )
        if accepted.get("ok") is not True or accepted.get("work_started") is not False:
            raise GovernedWorkGatewayError("Cowork did not accept the exact assignment")
        source_delivery = accepted.get("source_binding_delivery", {}).get("status")
        work_item_delivery = accepted.get("work_item_acceptance_delivery", {}).get(
            "status"
        )
        legacy_round_trip = source_delivery == "queued_after_work_item_acceptance_ack"
        canonical_round_trip = (
            source_delivery == "superseded_by_work_item_acceptance"
            and work_item_delivery == "queued"
        )
        if not legacy_round_trip and not canonical_round_trip:
            raise GovernedWorkGatewayError(
                "installed APatch runtime cannot complete the Cowork round trip"
            )
        change = accepted.get("change")
        change_hash = accepted.get("change_hash")
        if not isinstance(change, dict) or not isinstance(change_hash, str):
            raise GovernedWorkGatewayError("APatch returned no exact local Change")
        for field in (
            "tenant_id",
            "project_group_id",
            "work_program_id",
            "work_program_hash",
        ):
            if change.get(field) != proposal.get(field):
                raise GovernedWorkGatewayError("APatch Change scope does not match the assignment")
        if self._domain.document_hash(change) != change_hash:
            raise GovernedWorkGatewayError("APatch Change hash does not match its document")

        bound = self._find_exact_binding(change, change_hash, proposal)
        last_sync: Mapping[str, Any] | None = None
        if bound is None:
            for _round in range(ROUND_TRIP_SYNC_ROUNDS):
                last_sync = self._api.sync_governed_work(
                    str(self.workspace),
                    request_key_provider=request_key_provider,
                )
                bound = self._find_exact_binding(change, change_hash, proposal)
                if bound is not None:
                    break
        if bound is None:
            if last_sync is not None and last_sync.get("ok") is not True:
                raise GovernedWorkGatewayError(
                    "Cowork acknowledgement is unavailable or rejected"
                )
            raise GovernedWorkGatewayError(
                "Cowork source binding was not acknowledged after acceptance"
            )
        return {
            "status": "source_bound",
            "change_id": str(change["change_id"]),
            "change_hash": change_hash,
            "source_binding_id": str(bound["binding_id"]),
            "source_binding_hash": self._domain.document_hash(bound),
        }

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
