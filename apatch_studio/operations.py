"""Typed, browser-safe requests for APatch Studio agent work."""

from __future__ import annotations

import re
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

WorkMode = Literal[
    "new_change",
    "requirement",
    "specification",
    "spec_scaffold",
    "recovery",
    "rollback_preview",
]
RunnerId = Literal["codex", "claude"]

_SPEC_ID = re.compile(r"^SPEC-[A-Z0-9][A-Z0-9-]{1,95}$")
_RFP_ID = re.compile(r"^RFP-[A-Z0-9][A-Z0-9-]{1,95}$")
_REQUIREMENT_ID = re.compile(r"^[A-Z][A-Z0-9_-]{0,63}$")
_WORK_ASSET_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{2,127}$")
_SESSION_ID = re.compile(r"^apatch_sess_[0-9]+_[a-f0-9]+$")
_HASH_ID = r"^sha256:[0-9a-f]{64}$"
_REQUEST_ID = r"^apsreq_[a-z0-9][a-z0-9_-]{7,95}$"


class ExecutionContext(BaseModel):
    """Signed external source context accepted only by Studio internals."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema: Literal["apatch.studio.execution-context.v1"] = (
        "apatch.studio.execution-context.v1"
    )
    intent_id: str = Field(pattern=r"^tcapsei_[0-9a-f]{32}$")
    tenant_id: str = Field(
        pattern=(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
            r"[0-9a-f]{4}-[0-9a-f]{12}$"
        )
    )
    project_group_id: str = Field(pattern=r"^tcpg_[0-9a-f]{32}$")
    work_item_id: str = Field(pattern=r"^tcpwi_[0-9a-f]{32}$")
    work_item_hash: str = Field(pattern=_HASH_ID)
    authority_version: int = Field(ge=1, le=2_147_483_647)
    work_program_id: str = Field(pattern=r"^tcwp_[0-9a-f]{32}$")
    work_program_hash: str = Field(pattern=_HASH_ID)
    document_hash: str = Field(pattern=_HASH_ID)
    envelope_hash: str = Field(pattern=_HASH_ID)



class SddExecutionContext(BaseModel):
    """Private exact Core binding for one locally approved requirement run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema: Literal["apatch.studio.sdd-execution-context.v1"] = (
        "apatch.studio.sdd-execution-context.v1"
    )
    spec_id: str = Field(pattern=_SPEC_ID)
    requirement_id: str = Field(pattern=_REQUIREMENT_ID)
    actor_id: str = Field(min_length=3, max_length=128)
    contract_hash: str = Field(pattern=_HASH_ID)
    envelope_hash: str = Field(pattern=_HASH_ID)
    contract: dict[str, Any]
    task_envelope: dict[str, Any]

    @model_validator(mode="after")
    def exact_binding(self) -> Self:
        if self.contract.get("document_hash") != self.contract_hash:
            raise ValueError("contract_hash does not match the frozen contract")
        if self.task_envelope.get("document_hash") != self.envelope_hash:
            raise ValueError("envelope_hash does not match the task envelope")
        if self.task_envelope.get("contract_hash") != self.contract_hash:
            raise ValueError("task envelope does not bind the frozen contract")
        if (
            self.task_envelope.get("requirement")
            != f"{self.spec_id}#{self.requirement_id}"
        ):
            raise ValueError("task envelope does not bind the exact requirement")
        return self


class SddFreezeRequest(BaseModel):
    """One explicit approval of a prepared execution contract.

    There is deliberately no field naming the approver. A caller that can put a
    name on a record can put somebody else's name on it, and the field this
    class used to carry was filled with the same literal for every approval
    anyone ever made. The workspace resolves who approved; the request only
    says that an approval was made.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(pattern=_REQUEST_ID)
    confirmed: Literal[True]
    snapshot: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    offer_id: str | None = Field(default=None, pattern=r"^apsofr_[0-9a-f]{32}$")


class SddTaskOfferRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: str = Field(pattern=_REQUEST_ID)
    confirmed: Literal[True]
    snapshot: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class LockReleaseRequest(BaseModel):
    """One side asking for an agreed boundary to be lifted.

    Like the approval, there is no field naming who is asking. The workspace
    knows which side it is acting as, and a caller that could name the asker
    could ask in somebody else's name.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(pattern=_REQUEST_ID)
    reason: str = Field(min_length=8, max_length=500)


class LockReleaseAnswer(BaseModel):
    """The other side's answer, which is a consent or a reasoned refusal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(pattern=_REQUEST_ID)
    decision: Literal["grant", "refuse"]
    reason: str = Field(min_length=8, max_length=500)


class AgentRunRequest(BaseModel):
    """One fixed-purpose local agent dispatch request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: WorkMode
    runner: RunnerId
    objective: str = Field(min_length=3, max_length=2000)
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=12)
    spec_id: str | None = None
    requirement_id: str | None = None
    rfp_id: str | None = None
    work_asset_id: str | None = None
    governed_session_id: str | None = None

    @field_validator("objective")
    @classmethod
    def normalize_objective(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 3:
            raise ValueError("objective is too short")
        return normalized

    @field_validator("acceptance_criteria")
    @classmethod
    def normalize_criteria(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            criterion = " ".join(value.split())
            if not 3 <= len(criterion) <= 500:
                raise ValueError("each acceptance criterion must contain 3..500 characters")
            normalized.append(criterion)
        return normalized

    @field_validator("spec_id")
    @classmethod
    def validate_spec_id(cls, value: str | None) -> str | None:
        if value is not None and not _SPEC_ID.fullmatch(value):
            raise ValueError("invalid spec_id")
        return value

    @field_validator("rfp_id")
    @classmethod
    def validate_rfp_id(cls, value: str | None) -> str | None:
        if value is not None and not _RFP_ID.fullmatch(value):
            raise ValueError("invalid rfp_id")
        return value

    @field_validator("requirement_id")
    @classmethod
    def validate_requirement_id(cls, value: str | None) -> str | None:
        if value is not None and not _REQUIREMENT_ID.fullmatch(value):
            raise ValueError("invalid requirement_id")
        return value

    @field_validator("work_asset_id")
    @classmethod
    def validate_work_asset_id(cls, value: str | None) -> str | None:
        if value is not None and not _WORK_ASSET_ID.fullmatch(value):
            raise ValueError("invalid work_asset_id")
        return value

    @field_validator("governed_session_id")
    @classmethod
    def validate_session_id(cls, value: str | None) -> str | None:
        if value is not None and not _SESSION_ID.fullmatch(value):
            raise ValueError("invalid governed_session_id")
        return value

    @model_validator(mode="after")
    def validate_mode_shape(self) -> Self:
        if self.mode == "new_change":
            if not self.acceptance_criteria:
                raise ValueError("new_change requires acceptance_criteria")
            if self.spec_id or self.requirement_id or self.rfp_id or self.governed_session_id:
                raise ValueError("new_change cannot carry existing APatch identifiers")
        elif self.mode == "requirement":
            if not self.spec_id or not self.requirement_id:
                raise ValueError("requirement mode needs exact spec_id and requirement_id")
            if self.acceptance_criteria or self.rfp_id or self.work_asset_id or self.governed_session_id:
                raise ValueError("requirement mode cannot carry change, asset or recovery fields")
        elif self.mode == "specification":
            if not self.spec_id:
                raise ValueError("specification mode needs an exact spec_id")
            if self.acceptance_criteria or self.requirement_id or self.rfp_id or self.work_asset_id or self.governed_session_id:
                raise ValueError("specification mode accepts only an exact spec_id")
        elif self.mode == "spec_scaffold":
            if not self.spec_id or not self.rfp_id:
                raise ValueError("spec_scaffold needs exact rfp_id and spec_id")
            if self.acceptance_criteria or self.requirement_id or self.work_asset_id or self.governed_session_id:
                raise ValueError("spec_scaffold cannot carry execution, asset or recovery fields")
        elif self.mode in {"recovery", "rollback_preview"}:
            if not self.governed_session_id:
                raise ValueError(f"{self.mode} mode needs an exact governed_session_id")
            if self.acceptance_criteria or self.spec_id or self.requirement_id or self.rfp_id or self.work_asset_id:
                raise ValueError(
                    f"{self.mode} mode cannot carry change or requirement fields"
                )
        return self
