"""Managed, fixed-purpose local agent runners for APatch Studio."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

from apatch_studio.contribution_workflow import extract_attestation_delivery
from apatch_studio.failure_copy import explain_failure
from apatch_studio.capabilities import apatch_python_command, apatch_python_startup_env
from apatch_studio.plan_handoff import (
    PREPARATION_REQUIRED_KEYS,
    PlanHandoffCollector,
    PlanHandoffError,
    render_preparation_template,
)
from apatch_studio.operations import (
    AgentRunRequest,
    ExecutionContext,
    RunnerId,
    SddExecutionContext,
)
from apatch_studio.run_review import WorkspaceReviewCollector, build_review
from apatch_studio.scope_projection import (
    capture_scope_violation_fingerprints,
    empty_scope_outcome,
    update_scope_outcome,
)
from apatch_studio.run_store import (
    ACTIVE_STATUSES,
    RECORD_SCHEMA,
    RunJournalError,
    RunStore,
    TERMINAL_STATUSES,
)

_TERMINAL = TERMINAL_STATUSES
_RUNNER_DEFINITIONS: dict[RunnerId, tuple[str, str]] = {
    "codex": ("Codex", "codex"),
    "claude": ("Claude Code", "claude"),
}
DEFAULT_PLAN_INSPECTION_LIMIT = 8
DEFAULT_PLAN_STALL_SECONDS = 30.0
DEFAULT_PLAN_TIMEOUT_SECONDS = 300.0
MAX_PLAN_CONTEXT_FILE_BYTES = 20_000
MAX_PLAN_CONTEXT_BYTES = 48_000
MAX_PLAN_CONTEXT_INDEX_ENTRIES = 128


class RunnerUnavailableError(RuntimeError):
    """The selected allowlisted runner is not installed."""


class RunCapacityError(RuntimeError):
    """The bounded local run queue is full."""


class RunNotFoundError(KeyError):
    """The requested opaque Studio run does not exist."""


class RunStateError(RuntimeError):
    """The requested lifecycle transition is not valid."""


class RunnerCatalogProtocol(Protocol):
    def projection(self) -> list[dict[str, Any]]: ...

    def command(self, runner: RunnerId, workspace: Path) -> list[str]: ...


class PlanHandoffCollectorProtocol(Protocol):
    def capture(self) -> object: ...

    def resolve(self, before: object) -> dict[str, Any]: ...


@dataclass(frozen=True)
class RunnerCatalog:
    """Detect code-owned runner executables and construct fixed argv arrays."""

    which: Callable[[str], str | None] = shutil.which

    def _resolve(self, runner: RunnerId) -> str | None:
        _label, executable = _RUNNER_DEFINITIONS[runner]
        return self.which(executable)

    def projection(self) -> list[dict[str, Any]]:
        return [
            {
                "id": runner,
                "label": label,
                "available": self._resolve(runner) is not None,
            }
            for runner, (label, _executable) in _RUNNER_DEFINITIONS.items()
        ]

    def command(self, runner: RunnerId, workspace: Path) -> list[str]:
        executable = self._resolve(runner)
        if executable is None:
            raise RunnerUnavailableError(f"{runner} runner is not installed")
        if runner == "codex":
            return [
                executable,
                "exec",
                "--json",
                "--color",
                "never",
                "--cd",
                str(workspace),
                "--approve-for-me",
                *self._codex_mcp_overrides(),
                "-",
            ]
        return [
            executable,
            "--print",
            "--output-format",
            "stream-json",
            "--verbose",
            "--permission-mode",
            "auto",
            "--mcp-config",
            json.dumps({"mcpServers": {"apatch": self.apatch_mcp_server()}}, sort_keys=True),
            "--strict-mcp-config",
        ]

    @staticmethod
    def apatch_mcp_server() -> dict[str, Any]:
        """The exact apatch MCP server every runner must use (REC-db629a7ee98f).

        Studio never relies on the consumer's ``.apatch/mcp.json`` or on a user's
        global runner configuration: those default to the compact 15-tool profile,
        which lacks the governed mutation tools a plan needs, and the failure is
        silent ("completed without one new reviewable plan"). The runner gets the
        interpreter that runs Studio, the plain launcher bound to the workspace by
        cwd, and the full professional catalog.
        """

        env = {
            **apatch_python_startup_env(),
            "APATCH_MCP_PROFILE": "full",
            "APATCH_MCP_GUIDANCE": "doctor_only",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        }
        command = apatch_python_command("apatch.mcp.launcher")
        return {
            "command": command[0],
            "args": command[1:],
            "env": env,
        }

    @classmethod
    def _codex_mcp_overrides(cls) -> list[str]:
        server = cls.apatch_mcp_server()
        env_table = ", ".join(f'{key}="{value}"' for key, value in server["env"].items())
        return [
            "-c",
            f'mcp_servers.apatch.command="{server["command"]}"',
            "-c",
            "mcp_servers.apatch.args=" + json.dumps(server["args"]),
            "-c",
            "mcp_servers.apatch.env={" + env_table + "}",
            "-c",
            "mcp_servers.apatch.enabled=true",
        ]

    def planning_command(self, runner: RunnerId, workspace: Path) -> list[str]:
        """Use a latency-oriented profile only for contract preparation."""

        command = self.command(runner, workspace)
        if runner != "codex":
            return command
        return [
            *command[:-1],
            "--model",
            "gpt-5.6-luna",
            "-c",
            'model_reasoning_effort="low"',
            command[-1],
        ]


def safe_runner_failure(runner: RunnerId, line: str) -> tuple[str, str] | None:
    """Classify known runner failures without retaining raw process output."""

    lowered = line.lower()
    if (
        runner == "codex"
        and "--sandbox" in lowered
        and "--approve-for-me" in lowered
        and "cannot be used" in lowered
    ):
        return (
            "runner_options_incompatible",
            "Codex runner options are incompatible. Update APatch Studio and retry.",
        )
    if "authentication" in lowered or "not logged in" in lowered:
        return (
            "runner_authentication_required",
            f"{_RUNNER_DEFINITIONS[runner][0]} needs authentication before it can run.",
        )
    if "usage limit" in lowered or "rate limit" in lowered:
        return (
            "runner_capacity_unavailable",
            f"{_RUNNER_DEFINITIONS[runner][0]} is temporarily unavailable. Retry later.",
        )
    return None


_APATCH_PHASES = (
    (("rollback",), "rolling_back", "APatch is preparing or executing rollback"),
    (("recover", "resume_session"), "recovering", "APatch is recovering exact governed state"),
    (("attest",), "attesting", "APatch is recording governed evidence"),
    (("verify", "lint", "probe"), "verifying", "APatch is running verification gates"),
    (("apply", "generate", "simulate", "mutation"), "applying", "APatch is applying governed changes"),
    (("session_start", "spec_next", "spec_plan", "execute_next"), "planning", "APatch is planning the work"),
    (("session_end",), "finishing", "APatch is closing the work"),
)
_PLAN_CONTRACT_TOOL_FRAGMENTS = (
    "rfp",
    "spec_scaffold",
    "spec_lint",
    "generate_batch",
    "apply_session",
    "execute_next",
)


def _tool_names(event: dict[str, Any]) -> list[str]:
    candidates: list[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {"tool", "tool_name", "name"} and isinstance(child, str):
                    candidates.append(child.lower())
                elif key in {"item", "call", "data", "content"}:
                    collect(child)
        elif isinstance(value, list):
            for child in value[:32]:
                collect(child)

    collect(event)
    return candidates


def _event_item_type(event: dict[str, Any]) -> str:
    item = event.get("item")
    if not isinstance(item, dict):
        return ""
    item_type = item.get("type")
    return item_type.lower() if isinstance(item_type, str) else ""


def apatch_phase_from_event(event: dict[str, Any]) -> tuple[str, str] | None:
    """Derive a safe lifecycle phase from a structured APatch tool event."""

    for candidate in _tool_names(event):
        if "apatch" not in candidate:
            continue
        for fragments, phase, message in _APATCH_PHASES:
            if any(fragment in candidate for fragment in fragments):
                return phase, message
    return None


def _is_contract_authoring_event(event: dict[str, Any]) -> bool:
    if _event_item_type(event) in {"file_change", "file_write"}:
        return True
    return any(
        "apatch" in tool
        and any(fragment in tool for fragment in _PLAN_CONTRACT_TOOL_FRAGMENTS)
        for tool in _tool_names(event)
    )


def runner_phase_from_event(
    event: dict[str, Any],
    *,
    mode: str,
) -> tuple[str, str] | None:
    """Project structured runner work without reading command or content fields."""

    tools = _tool_names(event)
    if mode == "new_change":
        if any(
            "apatch" in tool
            and any(fragment in tool for fragment in _PLAN_CONTRACT_TOOL_FRAGMENTS)
            for tool in tools
        ):
            return "preparing_contract", "Agent is preparing the review package"

    apatch_phase = apatch_phase_from_event(event)
    if apatch_phase is not None:
        phase, _message = apatch_phase
        if mode == "new_change":
            if phase in {"planning", "applying"}:
                return "preparing_contract", "Agent is preparing the review package"
            if phase == "verifying":
                return "verifying", "Agent is validating plan scope and checks"
            if phase in {"attesting", "finishing"}:
                return "finalizing", "Agent is finalizing the review handoff"
        return apatch_phase

    if mode != "new_change":
        return None
    item_type = _event_item_type(event)
    if item_type == "command_execution":
        return "inspecting", "Agent is inspecting the minimum project contract"
    if item_type in {"file_change", "file_write"}:
        return "preparing_contract", "Agent is preparing the review package"
    if item_type in {"reasoning", "analysis"}:
        return "planning", "Agent is choosing the smallest safe contract"
    if item_type in {"agent_message", "message"}:
        return "finalizing", "Agent is summarizing the review-ready plan"
    return None

def _preparation_package_lines(request: AgentRunRequest, spec_id: str | None) -> list[str]:
    """Hand the runner the exact review-package shape Studio accepts (REC-bf36f1001fd7)."""

    keys = ", ".join(sorted(PREPARATION_REQUIRED_KEYS))
    template_spec = spec_id or "<preallocated SPEC id>"
    return [
        f"Write the bounded review package to .apatch/sdd/prepared/{template_spec}.json in exactly the shape of the template below; Studio rejects any other top-level key set.",
        f"Package rules: the top-level keys are exactly {keys}; schema stays apatch.studio.sdd-preparation.v1; source_mutation_count stays 0; prepared_at is an ISO-8601 timestamp with a timezone; task_envelopes holds one entry per '## Rk' heading of the SPEC and nothing else, each with requirement '<SPEC id>#Rk'; never add authority, status, frozen_at, document_hash, implementation_allowed or contract_hash fields.",
        "Preparation package template (replace every <placeholder>, keep every key, add one obligation per RFP acceptance row):",
        render_preparation_template(template_spec, request.objective),
        "Verify the contract-authoring session with an explicit check instead of the project default suite: apatch_verify_run(verify=['python3', '-m', 'pytest', '<frozen test file>', '-q', '--collect-only']) proves the frozen tests collect; the frozen tests themselves are expected to fail until implementation, so never run them as the blocking verification.",
        "If apatch_apply_session or verification fails, repair the batch inside the same session (apatch_resume_session when the session reports failed) and retry until the package lands; ending the run without the package is a failed plan.",
    ]


def build_governed_prompt(
    request: AgentRunRequest,
    *,
    retry: bool = False,
    execution_context: ExecutionContext | None = None,
    sdd_execution: SddExecutionContext | None = None,
    studio_run_id: str | None = None,
    planning_contract_run_id: str | None = None,
    planning_context: str | None = None,
) -> str:
    """Build mode-specific instructions; user content is transported over stdin."""

    common = [
        "You are executing work from APatch Studio in the current Git workspace.",
        "Use the installed full APatch MCP/CLI as the governed execution runtime.",
        "Begin with APatch doctor and inspect only the context required by this exact mode.",
        "All source mutations must belong to an exact governed APatch session and requirement.",
        "Verify every completed requirement and finish with attestation or an exact rollback.",
        "Never push, deploy, publish, restart production, or weaken a safety boundary.",
        "Do not bypass APatch with an ungoverned patch when protected files are involved.",
        "Before reporting success, call apatch_sandbox_audit with auto_revert=false and inspect the exact report.",
        "Never request automatic reversion unless APatch proves the violating write belongs to this exact run; otherwise stop and report it for owner review.",
        "Never claim that scope is clean unless that explicit report-only audit is clean.",
        "Treat the frozen verification contract and task envelope as the only authority for source work.",
        "Do not approve the contract or amendment as the implementation actor.",
    ]
    if retry:
        if request.mode == "new_change":
            common.extend(
                [
                    "This is a planning retry: continue the prior exact contract lineage in this "
                    "attempt's fresh run-owned lane; never recover or mutate the prior lane.",
                    "This retry must write exactly one new review-package revision attributable to "
                    "the current Studio planning run, even when the existing contract is complete.",
                    "Carry the valid contract forward, update prepared_at and "
                    "contract_request.planning_run.run_id to the current Studio planning run, and "
                    "preserve the proposed judges and task envelopes unless a real correction is required.",
                    "When no real contract correction is required, mutate only the preparation-package JSON; "
                    "do not rewrite RFP or SPEC planning labels solely for retry attribution.",
                    "Use byte-exact anchors from the supplied preparation-package JSON and never guess a "
                    "Markdown anchor that is unnecessary for Studio attribution.",
                    "Never call apatch_execute_next with an empty needles list before that revision "
                    "has been written; an unchanged preparation package is a failed retry.",
                ]
            )
        else:
            common.append(
                "This is a retry: inspect existing APatch state first and recover an exact interrupted "
                "session or checkpoint instead of duplicating work."
            )
    if execution_context is not None:
        common.extend(
            [
                "This run was locally confirmed from a verified signed project intent.",
                f"External intent: {execution_context.intent_id}",
                f"Project group: {execution_context.project_group_id}",
                (
                    "Work item: "
                    f"{execution_context.work_item_id} at {execution_context.work_item_hash}"
                ),
                (
                    "Work program: "
                    f"{execution_context.work_program_id} at "
                    f"{execution_context.work_program_hash}"
                ),
                f"Authority version: {execution_context.authority_version}",
                f"Signed intent document: {execution_context.document_hash}",
                "Preserve these exact source references in the resulting Change/evidence context.",
                "They authorize no runner, path, command, environment, session or business acceptance.",
            ]
        )

    if sdd_execution is not None:
        from apatch.sdd_integrity import canonical_json

        common.extend(
            [
                "The human owner has frozen the exact verification contract for this requirement.",
                "Open the fixed-purpose implementation session before any mutation:",
                f"sdd_contract_json={canonical_json(sdd_execution.contract)}",
                f"task_envelope_json={canonical_json(sdd_execution.task_envelope)}",
                f"actor_id={sdd_execution.actor_id}",
                "Call apatch_session_start with those exact sdd_contract and task_envelope objects plus the exact actor_id.",
                "The MCP fixes the capability role to implementation; never request verifier or authority capability.",
                "After that exact session is open, call apatch_execute_next only for the selected requirement.",
            ]
        )

    if request.mode == "new_change":
        template_spec_id: str | None = None
        if studio_run_id is not None:
            planning_lane = planning_lane_for_run(studio_run_id)
            contract_run_id = planning_contract_run_id or studio_run_id
            planning_rfp_id, planning_spec_id = planning_contract_ids(contract_run_id)
            template_spec_id = planning_spec_id
            common.extend(
                [
                    f"Studio planning run: {studio_run_id}",
                    f"Use only the exact APatch lane: {planning_lane}",
                    f"Use the preallocated RFP id exactly: {planning_rfp_id}",
                    f"Use the preallocated SPEC id exactly: {planning_spec_id}",
                    "Do not choose or repair another RFP or SPEC identifier.",
                    f"For a fresh lineage, open the contract-authoring session with artifacts ['spec-bootstrap:{planning_spec_id}#R0', 'rfp:{planning_rfp_id}'] so APatch authorizes creating that new SPEC file.",
                    "A retry may continue only valid partial artifacts with these exact identifiers.",
                    "Keep every contract-authoring operation in this lane and reuse only this run's exact lineage for fix-forward.",
                    "Never recover, resume, attest, roll back or close a pre-existing or sibling session.",
                ]
            )
        if planning_context:
            common.extend(
                [
                    "Studio supplied the only authorized pre-authoring context below.",
                    "Do not inspect additional repository files before contract authoring; APatch doctor is the only permitted pre-authoring tool call.",
                    "<studio-planning-context>",
                    planning_context,
                    "</studio-planning-context>",
                ]
            )
        criteria = "\n".join(f"- {item}" for item in request.acceptance_criteria)
        asset_context = (
            [
                f"Recall and apply the exact WorkAsset: {request.work_asset_id}",
                "Inspect its provenance and constraints before mutation.",
                "After successful verification and attestation, record actual use with the exact proof ref.",
                "Opening or recalling the asset alone must not count as reuse.",
            ]
            if request.work_asset_id
            else []
        )
        task = [
            "Prepare a new governed change contract.",
            "Bounded preparation path (in this order):",
            "1. Use only the Studio-supplied context capsule; do not open project files.",
            "2. Run APatch doctor, then continue an exact-lineage partial contract when the capsule contains one.",
            "3. Draft the RFP, SPEC, frozen test contract and preparation package completely before writing.",
            "4. For a fresh lineage, open one contract-authoring session with apatch_session_start(intent=..., artifacts=['spec-bootstrap:<preallocated SPEC id>#R0', 'rfp:<preallocated RFP id>']) and create the complete RFP, complete SPEC, frozen test/fixture files and preparation package in one mutation batch of that session (apatch_generate_batch, apatch_simulate, apatch_apply_session), then verify, attest and end it.",
            "5. If the exact-lineage SPEC scaffold already exists, call apatch_session_start once for the exact SPEC#R0, then call apatch_execute_next with that same session id/token, the complete ordered needles list and no finalize flag.",
            "6. Repeat apatch_execute_next for the same session with no new needles while each response says continue=true. Only after continue=false, call it once with finalize=true and no needles. Do not place generate_batch, resume_session or rollback between these calls.",
            "Use at most 8 structured repository inspection command starts before the first contract write.",
            "After the first contract-authoring event, do not perform further repository inspection.",
            "Never attest or close an RFP-only or SPEC-only partial package.",
            "Do not inventory the whole source tree, test tree or historical specification archive.",
            "Do not call apatch_spec_scaffold in new-change mode; author the complete SPEC directly so ownership cannot freeze a TODO scaffold.",
            "Use apatch_rfp_lint and apatch_spec_lint only after the complete package has landed.",
            *asset_context,
            f"Intended outcome: {request.objective}",
            "Acceptance criteria:",
            criteria,
            "Source implementation is forbidden until a human owner or named authority has reviewed and frozen the verification contract.",
            "Prepare a versioned brief, stable RFP acceptance IDs, an exact SPEC, independent oracles, frozen tests, fixtures and commands, plus positive, negative, boundary and regression perspectives.",
            "Record a relevant red baseline and a reversible falsification plan for every material gate.",
            "Derive the complete task envelope, but do not mutate application source while the owner freeze is absent.",
            *_preparation_package_lines(request, template_spec_id),
            "Stop at a review-ready contract when owner approval is required; never self-approve and continue into implementation.",
        ]
    elif request.mode == "requirement":
        task = [
            "Execute exactly the selected executable requirement.",
            "Before source mutation, require the frozen verification contract and exact task envelope; stop for owner review if either is absent or drifted.",
            f"SPEC: {request.spec_id}",
            f"Requirement: {request.requirement_id}",
            f"Work intent: {request.objective}",
            "Do not invent a parallel SPEC or silently widen the requirement.",
        ]
    elif request.mode == "specification":
        task = [
            "Execute the prepared executable specification through APatch.",
            f"SPEC: {request.spec_id}",
            f"Work intent: {request.objective}",
            "Inspect the current plan and interference first, then call apatch_spec_run for this exact SPEC.",
            "Do not invent another SPEC or silently skip a failed requirement.",
        ]
    elif request.mode == "spec_scaffold":
        task = [
            "Create one executable SPEC scaffold from an existing RFP through APatch.",
            f"RFP: {request.rfp_id}",
            f"New SPEC: {request.spec_id}",
            f"Work intent: {request.objective}",
            "Lint the exact RFP, scaffold the exact SPEC id, then lint and report coverage.",
            "Do not overwrite an existing SPEC or edit unrelated source files.",
        ]
    elif request.mode == "recovery":
        task = [
            "Recover exactly the interrupted governed work.",
            f"Governed session: {request.governed_session_id}",
            f"Recovery intent: {request.objective}",
            "Call apatch_recover for this exact governed_session_id, obey the returned action and continue from "
            "its authoritative checkpoint. Never guess a newer or sibling session.",
        ]
    else:
        task = [
            "Preview rollback for exactly the selected governed session.",
            f"Governed session: {request.governed_session_id}",
            f"Review intent: {request.objective}",
            "Call apatch_rollback with preview=true for this exact governed_session_id.",
            "Do not execute rollback, mutate files, attest new work, or select another session.",
            "Return the content-safe affected-file count and whether execution would be permitted.",
        ]
    return "\n".join([*common, "", *task, "", "Return a concise completion or blocker summary."])


@dataclass
class _RunRecord:
    run_id: str
    request: AgentRunRequest
    retry_of: str | None
    execution_context: ExecutionContext | None = None
    sdd_execution: SddExecutionContext | None = None
    status: str = "queued"
    phase: str = "queued"
    created_at: str = field(default_factory=lambda: _now())
    started_at: str | None = None
    ended_at: str | None = None
    outcome: str | None = None
    message: str = "Waiting for a local runner slot"
    thread_id: str | None = None
    event_count: int = 0
    review: dict[str, Any] | None = None
    timeline: list[dict[str, str]] = field(default_factory=list)
    reviewer_note: dict[str, str] | None = None
    contribution: dict[str, Any] | None = None
    plan_handoff: dict[str, Any] | None = None
    scope: dict[str, Any] = field(default_factory=empty_scope_outcome)
    updated_at: str = field(default_factory=lambda: _now())
    cancel_requested: bool = False
    planning_inspection_events: int = 0
    planning_contract_started: bool = False
    planning_stop_reason: str | None = None
    planning_started_monotonic: float = field(default=0.0, repr=False)
    planning_last_event_monotonic: float = field(default=0.0, repr=False)
    planning_last_activity_at: str | None = None
    planning_cleanup: str = "not_needed"
    scope_baseline: frozenset[str] = field(default_factory=frozenset, repr=False)
    process: subprocess.Popen[str] | None = field(default=None, repr=False)
    done: threading.Event = field(default_factory=threading.Event, repr=False)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def planning_lane_for_run(run_id: str) -> str:
    """Return the opaque APatch lane owned by one Studio planning run."""

    suffix = run_id.removeprefix("apr_")
    if len(suffix) != 32 or any(character not in "0123456789abcdef" for character in suffix):
        raise ValueError("invalid Studio run id")
    return f"studio-plan-{run_id}"


def planning_contract_ids(run_id: str) -> tuple[str, str]:
    """Return collision-free contract identifiers reserved for one planning run."""

    suffix = planning_lane_for_run(run_id).removeprefix("studio-plan-apr_")[:12].upper()
    return f"RFP-STUDIO-{suffix}", f"SPEC-STUDIO-CHANGE-{suffix}"



def _read_planning_context_file(
    root: Path,
    relative: str | Path,
    *,
    byte_limit: int = MAX_PLAN_CONTEXT_FILE_BYTES,
) -> str | None:
    path = root / relative
    try:
        if path.is_symlink():
            return None
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
        if not resolved.is_file():
            return None
        with resolved.open("rb") as handle:
            raw = handle.read(byte_limit + 1)
    except (OSError, ValueError):
        return None
    truncated = len(raw) > byte_limit
    text = raw[:byte_limit].decode("utf-8", errors="replace").strip()
    if not text:
        return None
    return text + ("\n[Studio context truncated]" if truncated else "")


def build_planning_context(
    workspace: str | os.PathLike[str],
    contract_run_id: str,
) -> str:
    """Build a private, bounded contract capsule without reading application source."""

    root = Path(workspace).expanduser().resolve()
    rfp_id, spec_id = planning_contract_ids(contract_run_id)
    sections: list[str] = []
    for label, relative, byte_limit in (
        ("Project operating contract", Path("AGENTS.md"), 8_000),
        ("Project summary", Path("README.md"), 12_000),
    ):
        text = _read_planning_context_file(root, relative, byte_limit=byte_limit)
        if text is not None:
            sections.append(f"## {label}\n{text}")

    docs_root = root / "docs"
    partial_paths = (
        sorted(docs_root.glob(f"{rfp_id}-*.md"))[:1]
        if docs_root.is_dir()
        else []
    )
    exact_spec = root / "docs" / "specs" / f"{spec_id}.md"
    if exact_spec.exists():
        partial_paths.append(exact_spec)
    for path in partial_paths:
        text = _read_planning_context_file(root, path.relative_to(root))
        if text is not None:
            sections.append(f"## Existing exact-lineage contract: {path.name}\n{text}")

    prepared = root / ".apatch" / "sdd" / "prepared" / f"{spec_id}.json"
    if prepared.exists():
        text = _read_planning_context_file(root, prepared.relative_to(root))
        if text is not None:
            sections.append(f"## Existing exact-lineage preparation package: {prepared.name}\n{text}")

    indexed: list[str] = []
    candidates = []
    if docs_root.is_dir():
        candidates.extend(sorted(docs_root.glob("RFP-*.md")))
    specs_root = docs_root / "specs"
    if specs_root.is_dir():
        candidates.extend(sorted(specs_root.glob("SPEC-*.md")))
    for path in candidates[:MAX_PLAN_CONTEXT_INDEX_ENTRIES]:
        text = _read_planning_context_file(root, path.relative_to(root), byte_limit=512)
        if text is None:
            continue
        title = next((line.strip() for line in text.splitlines() if line.strip()), path.name)
        indexed.append(f"- {path.name}: {title[:240]}")
    if indexed:
        sections.append("## Existing contract index (titles only)\n" + "\n".join(indexed))

    capsule = "\n\n".join(sections).encode("utf-8")
    if len(capsule) > MAX_PLAN_CONTEXT_BYTES:
        capsule = capsule[:MAX_PLAN_CONTEXT_BYTES]
        while True:
            try:
                rendered = capsule.decode("utf-8")
                break
            except UnicodeDecodeError:
                capsule = capsule[:-1]
        return rendered.rstrip() + "\n[Studio context capsule truncated]"
    return capsule.decode("utf-8")

def cleanup_planning_session(workspace: str | os.PathLike[str], run_id: str) -> str:
    """Recover and close only the APatch lane owned by one failed planning run."""

    root = Path(workspace).expanduser().resolve()
    state_path = root / ".apatch" / "lanes" / planning_lane_for_run(run_id) / "session_state.json"
    if not state_path.is_file():
        return "not_needed"
    try:
        raw = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "failed"
    session_id = raw.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return "not_needed"
    if raw.get("ended_at"):
        return "already_closed"

    try:
        from apatch.runtime.runtime import MutationRuntime

        recovered = MutationRuntime(
            root,
            session_id=session_id,
            enforce_binding=True,
        ).recover_session()
        if not recovered.get("ok"):
            return "failed"
        if recovered.get("recovery") == "closed":
            return "closed"
        token = recovered.get("session_token")
        if not isinstance(token, str) or not token:
            return "failed"
        runtime = MutationRuntime(
            root,
            session_id=session_id,
            session_token=token,
            enforce_binding=True,
        )
        checkpoint = raw.get("checkpoint")
        rolled_back = False
        if isinstance(checkpoint, str) and checkpoint:
            rollback = runtime.rollback(preview=False)
            if rollback.get("ok"):
                rolled_back = True
            elif rollback.get("error_type") != "ROLLBACK_CHECKPOINT_MISSING":
                return "failed"
        closed = runtime.close_session()
        if not closed.get("ok"):
            return "failed"
        return "rolled_back" if rolled_back else "closed"
    except Exception:
        return "failed"


class AgentRunManager:
    """Bounded durable supervisor for allowlisted local coding agents."""

    def __init__(
        self,
        workspace: str | os.PathLike[str],
        *,
        catalog: RunnerCatalogProtocol | None = None,
        max_concurrent: int = 2,
        max_pending: int = 16,
        planning_inspection_limit: int = DEFAULT_PLAN_INSPECTION_LIMIT,
        planning_stall_seconds: float = DEFAULT_PLAN_STALL_SECONDS,
        planning_timeout_seconds: float = DEFAULT_PLAN_TIMEOUT_SECONDS,
        planning_session_cleanup: Callable[[str], str] | None = None,
        popen: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
        review_collector: Callable[[], dict[str, Any]] | None = None,
        plan_handoff_collector: PlanHandoffCollectorProtocol | None = None,
        scope_baseline_collector: Callable[[], frozenset[str]] | None = None,
        state_root: str | os.PathLike[str] | None = None,
        history_limit: int = 200,
        store: RunStore | None = None,
    ):
        root = Path(workspace).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"workspace does not exist: {root}")
        if not 1 <= max_concurrent <= 8:
            raise ValueError("max_concurrent must be in 1..8")
        if not max_concurrent <= max_pending <= 100:
            raise ValueError("max_pending must be between max_concurrent and 100")
        if not 1 <= planning_inspection_limit <= 100:
            raise ValueError("planning_inspection_limit must be in 1..100")
        if not 0.01 <= planning_stall_seconds < planning_timeout_seconds <= 3600:
            raise ValueError(
                "planning limits require 0.01 <= stall < timeout <= 3600 seconds"
            )
        self._workspace = root
        self._catalog = catalog or RunnerCatalog()
        self._max_pending = max_pending
        self._planning_inspection_limit = planning_inspection_limit
        self._planning_stall_seconds = float(planning_stall_seconds)
        self._planning_timeout_seconds = float(planning_timeout_seconds)
        self._planning_session_cleanup = planning_session_cleanup or (
            lambda run_id: cleanup_planning_session(root, run_id)
        )
        self._popen = popen
        self._review_collector = review_collector or WorkspaceReviewCollector(root).capture
        self._plan_handoff_collector = plan_handoff_collector or PlanHandoffCollector(root)
        self._scope_baseline_collector = scope_baseline_collector or (
            lambda: capture_scope_violation_fingerprints(str(root))
        )
        self._slots = threading.BoundedSemaphore(max_concurrent)
        self._lock = threading.RLock()
        self._runs: dict[str, _RunRecord] = {}
        self._order: list[str] = []
        self._closed = False
        self._store = store or RunStore(root, state_root=state_root, retention=history_limit)
        self._journal_status = "ready"
        self._journal_warning: str | None = None
        self._interrupted_on_start = 0
        self._store.acquire_instance()
        loaded = self._store.load()
        self._journal_status = loaded.status
        self._journal_warning = loaded.warning
        for raw in loaded.records:
            record = self._restore_record(raw)
            self._runs[record.run_id] = record
            self._order.append(record.run_id)
        for record in self._runs.values():
            if record.status in ACTIVE_STATUSES:
                self._finish(
                    record,
                    "interrupted",
                    "studio_restart",
                    "Studio restarted before the local agent reported completion",
                )
                record.done.set()
                self._interrupted_on_start += 1
        if self._interrupted_on_start:
            self._persist_locked()
            self._journal_status = "reconciled"
            self._journal_warning = "inflight_runs_marked_interrupted"

    def runners(self) -> list[dict[str, Any]]:
        return self._catalog.projection()

    def _runner_command(self, request: AgentRunRequest) -> list[str]:
        if request.mode == "new_change":
            planning_command = getattr(self._catalog, "planning_command", None)
            if callable(planning_command):
                return planning_command(request.runner, self._workspace)
        return self._catalog.command(request.runner, self._workspace)

    def _planning_contract_run_id(self, record: _RunRecord) -> str:
        """Resolve the first retained attempt that owns retry-stable contract IDs."""

        with self._lock:
            cursor = record
            visited = {cursor.run_id}
            while cursor.retry_of is not None:
                if cursor.retry_of in visited:
                    raise RunStateError("planning retry lineage contains a cycle")
                parent = self._runs.get(cursor.retry_of)
                if parent is None:
                    raise RunStateError("planning retry lineage is unavailable")
                cursor = parent
                visited.add(cursor.run_id)
            return cursor.run_id

    def start(
        self,
        request: AgentRunRequest,
        *,
        retry_of: str | None = None,
        execution_context: ExecutionContext | None = None,
        sdd_execution: SddExecutionContext | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if sdd_execution is not None and not isinstance(sdd_execution, SddExecutionContext):
            sdd_execution = SddExecutionContext.model_validate(sdd_execution)
        self._runner_command(request)
        with self._lock:
            if self._closed:
                raise RunStateError("run manager is closed")
            active = sum(record.status not in _TERMINAL for record in self._runs.values())
            if active >= self._max_pending:
                raise RunCapacityError("local run queue is full")
            run_id = f"apr_{uuid.uuid4().hex}"
            record = _RunRecord(
                run_id=run_id,
                request=request,
                retry_of=retry_of,
                execution_context=execution_context,
                sdd_execution=sdd_execution,
            )
            self._append_timeline(record)
            self._runs[run_id] = record
            self._order.append(run_id)
            try:
                self._persist_locked(required=True)
            except RunJournalError:
                self._runs.pop(run_id, None)
                self._order.remove(run_id)
                raise
            worker = threading.Thread(
                target=self._execute,
                args=(record,),
                name=f"apatch-studio-{run_id[-8:]}",
                daemon=True,
            )
            worker.start()
            return self._project(record)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self._project(self._runs[run_id]) for run_id in reversed(self._order[-200:])]

    def journal(self) -> dict[str, Any]:
        with self._lock:
            return {
                "schema": "apatch.studio.run-journal-status.v1",
                "persistent": True,
                "status": self._journal_status,
                "warning": self._journal_warning,
                "record_count": len(self._runs),
                "retention": self._store.retention,
                "interrupted_on_start": self._interrupted_on_start,
            }

    def get(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            return self._project(self._record(run_id))

    def wait(self, run_id: str, timeout: float = 10.0) -> dict[str, Any]:
        with self._lock:
            record = self._record(run_id)
            done = record.done
        if not done.wait(timeout):
            raise TimeoutError(f"run did not finish within {timeout} seconds")
        return self.get(run_id)

    def cancel(self, run_id: str) -> dict[str, Any]:
        process: subprocess.Popen[str] | None
        with self._lock:
            record = self._record(run_id)
            if record.status in _TERMINAL:
                return self._project(record)
            record.cancel_requested = True
            record.message = "Cancellation requested"
            if record.status == "queued":
                self._finish(record, "cancelled", "cancelled", "Cancelled before execution")
                self._persist_locked()
                record.done.set()
                return self._project(record)
            record.phase = "cancelling"
            record.updated_at = _now()
            process = record.process
            self._persist_locked()
            projection = self._project(record)
        if process is not None:
            self._terminate(process)
        return projection

    def retry(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            record = self._record(run_id)
            if record.status not in {"failed", "cancelled", "interrupted"}:
                raise RunStateError("only failed, cancelled or interrupted runs can be retried")
            request = record.request
            execution_context = record.execution_context
            sdd_execution = record.sdd_execution
        return self.start(
            request,
            retry_of=run_id,
            execution_context=execution_context,
            sdd_execution=sdd_execution,
        )

    def save_reviewer_note(self, run_id: str, note: str) -> dict[str, Any]:
        clean = " ".join(note.split())
        if not 3 <= len(clean) <= 1000:
            raise RunStateError("reviewer note must contain 3..1000 characters")
        with self._lock:
            record = self._record(run_id)
            record.reviewer_note = {
                "schema": "apatch.studio.reviewer-note.v1",
                "text": clean,
                "updated_at": _now(),
            }
            record.updated_at = record.reviewer_note["updated_at"]
            self._persist_locked(required=True)
            return self._project(record)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            active = [record for record in self._runs.values() if record.status not in _TERMINAL]
        for record in active:
            self.cancel(record.run_id)
        for record in active:
            record.done.wait(5.0)
        with self._lock:
            self._persist_locked()
        self._store.close()

    def _record(self, run_id: str) -> _RunRecord:
        try:
            return self._runs[run_id]
        except KeyError as exc:
            raise RunNotFoundError(run_id) from exc

    @staticmethod
    def _restore_record(raw: dict[str, Any]) -> _RunRecord:
        record = _RunRecord(
            run_id=raw["run_id"],
            request=AgentRunRequest.model_validate(raw["request"]),
            retry_of=raw.get("retry_of"),
            execution_context=(
                ExecutionContext.model_validate(raw["execution_context"])
                if raw.get("execution_context") is not None
                else None
            ),
            sdd_execution=(
                SddExecutionContext.model_validate(raw["sdd_execution"])
                if raw.get("sdd_execution") is not None
                else None
            ),
            status=raw["status"],
            phase=raw["phase"],
            created_at=raw["created_at"],
            started_at=raw.get("started_at"),
            ended_at=raw.get("ended_at"),
            outcome=raw.get("outcome"),
            message=raw["message"],
            thread_id=raw.get("thread_id"),
            event_count=int(raw.get("event_count") or 0),
            review=raw.get("review"),
            timeline=list(raw.get("timeline") or []),
            reviewer_note=raw.get("reviewer_note"),
            contribution=raw.get("contribution"),
            plan_handoff=raw.get("plan_handoff"),
            scope=raw.get("scope") or empty_scope_outcome(),
            updated_at=raw.get("updated_at") or raw["created_at"],
            planning_last_activity_at=raw.get("planning_last_activity_at"),
            planning_cleanup=str(raw.get("planning_cleanup") or "not_needed"),
        )
        if not record.timeline:
            AgentRunManager._append_timeline(record)
        if record.status in _TERMINAL:
            record.done.set()
        return record

    @staticmethod
    def _serialize_record(record: _RunRecord) -> dict[str, Any]:
        return {
            "schema": RECORD_SCHEMA,
            "run_id": record.run_id,
            "request": record.request.model_dump(),
            "execution_context": (
                record.execution_context.model_dump()
                if record.execution_context is not None
                else None
            ),
            "sdd_execution": (
                record.sdd_execution.model_dump()
                if record.sdd_execution is not None
                else None
            ),
            "retry_of": record.retry_of,
            "status": record.status,
            "phase": record.phase,
            "created_at": record.created_at,
            "started_at": record.started_at,
            "ended_at": record.ended_at,
            "outcome": record.outcome,
            "message": record.message,
            "thread_id": record.thread_id,
            "event_count": record.event_count,
            "review": record.review,
            "timeline": record.timeline,
            "reviewer_note": record.reviewer_note,
            "contribution": record.contribution,
            "plan_handoff": record.plan_handoff,
            "scope": record.scope,
            "updated_at": record.updated_at,
            "planning_last_activity_at": record.planning_last_activity_at,
            "planning_cleanup": record.planning_cleanup,
        }

    def _persist_locked(self, *, required: bool = False) -> None:
        try:
            accepted = self._store.save(
                [self._serialize_record(self._runs[run_id]) for run_id in self._order]
            )
        except RunJournalError:
            self._journal_status = "error"
            self._journal_warning = "journal_write_failed"
            if required:
                raise
            return
        keep = {record["run_id"] for record in accepted}
        self._order = [run_id for run_id in self._order if run_id in keep]
        self._runs = {run_id: record for run_id, record in self._runs.items() if run_id in keep}
        if self._journal_status == "error":
            self._journal_status = "ready"
            self._journal_warning = None

    @staticmethod
    def _append_timeline(record: _RunRecord) -> None:
        event = {"at": record.updated_at, "phase": record.phase, "message": record.message}
        if record.timeline and record.timeline[-1]["phase"] == event["phase"] and record.timeline[-1]["message"] == event["message"]:
            return
        record.timeline = [*record.timeline, event][-64:]

    def _capture_review(self) -> dict[str, Any] | None:
        try:
            return self._review_collector()
        except Exception:
            return None

    def _execute(self, record: _RunRecord) -> None:
        acquired = False
        plan_baseline: object | None = None
        watchdog_stop: threading.Event | None = None
        try:
            while not acquired:
                if record.done.is_set():
                    return
                acquired = self._slots.acquire(timeout=0.1)
            if record.request.mode == "new_change":
                plan_baseline = self._plan_handoff_collector.capture()
            try:
                record.scope_baseline = self._scope_baseline_collector()
            except Exception:
                record.scope_baseline = frozenset()
            baseline = self._capture_review()
            with self._lock:
                if record.cancel_requested:
                    self._finish(record, "cancelled", "cancelled", "Cancelled before execution")
                    return
                record.status = "running"
                record.phase = "starting"
                record.review = build_review(baseline, None)
                record.started_at = _now()
                record.updated_at = record.started_at
                if record.request.mode == "new_change":
                    monotonic_now = time.monotonic()
                    record.planning_started_monotonic = monotonic_now
                    record.planning_last_event_monotonic = monotonic_now
                    record.planning_last_activity_at = record.started_at
                record.message = "Starting the local agent"
                self._append_timeline(record)
                self._persist_locked()

            argv = self._runner_command(record.request)
            planning_contract_run_id = (
                self._planning_contract_run_id(record)
                if record.request.mode == "new_change"
                else None
            )
            planning_context = (
                build_planning_context(self._workspace, planning_contract_run_id)
                if planning_contract_run_id is not None
                else None
            )
            prompt = build_governed_prompt(
                record.request,
                retry=record.retry_of is not None,
                execution_context=record.execution_context,
                sdd_execution=record.sdd_execution,
                studio_run_id=(record.run_id if record.request.mode == "new_change" else None),
                planning_contract_run_id=planning_contract_run_id,
                planning_context=planning_context,
            )
            process_env = os.environ.copy()
            if record.request.mode == "new_change":
                process_env["APATCH_LANE"] = planning_lane_for_run(record.run_id)
            process = self._popen(
                argv,
                cwd=str(self._workspace),
                env=process_env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                shell=False,
                start_new_session=True,
            )
            with self._lock:
                record.process = process
                if record.cancel_requested:
                    self._terminate(process)
            if record.request.mode == "new_change":
                watchdog_stop = threading.Event()
                threading.Thread(
                    target=self._watch_planning,
                    args=(record, watchdog_stop),
                    name=f"apatch-studio-plan-watch-{record.run_id[-8:]}",
                    daemon=True,
                ).start()

            if process.stdin is not None:
                process.stdin.write(prompt)
                process.stdin.close()
            runner_failure: tuple[str, str] | None = None
            if process.stdout is not None:
                for line in process.stdout:
                    runner_failure = (
                        runner_failure
                        or safe_runner_failure(record.request.runner, line)
                    )
                    self._consume_event(record, line)
            return_code = process.wait()

            with self._lock:
                if record.cancel_requested:
                    self._finish(record, "cancelled", "cancelled", "Agent run cancelled")
                elif record.planning_stop_reason == "plan_timeout":
                    self._finish(
                        record,
                        "failed",
                        "plan_timeout",
                        f"Plan preparation stopped at the {int(self._planning_timeout_seconds)}-second limit; nothing in the project was changed",
                    )
                elif record.planning_stop_reason == "plan_discovery_budget_exceeded":
                    self._finish(
                        record,
                        "failed",
                        "plan_discovery_budget_exceeded",
                        f"Plan preparation stopped after {self._planning_inspection_limit} project checks without writing the plan",
                    )
                elif return_code == 0 and record.request.mode == "new_change":
                    try:
                        record.plan_handoff = self._plan_handoff_collector.resolve(plan_baseline)
                    except PlanHandoffError as exc:
                        self._finish(record, "failed", exc.code, str(exc))
                    else:
                        self._finish(
                            record,
                            "succeeded",
                            "plan_ready",
                            "Plan is ready for owner review; nothing in the project was changed",
                        )
                elif return_code == 0:
                    self._finish(
                        record,
                        "succeeded",
                        "complete",
                        "The agent finished the work",
                    )
                elif runner_failure is not None:
                    outcome, message = runner_failure
                    self._finish(record, "failed", outcome, message)
                else:
                    self._finish(
                        record,
                        "failed",
                        "runner_exit",
                        "The agent stopped before it finished",
                    )
        except RunnerUnavailableError:
            with self._lock:
                self._finish(record, "failed", "runner_unavailable", "Local runner unavailable")
        except Exception:
            with self._lock:
                if record.cancel_requested:
                    self._finish(record, "cancelled", "cancelled", "Agent run cancelled")
                elif record.planning_stop_reason == "plan_timeout":
                    self._finish(record, "failed", "plan_timeout", "Plan preparation stopped at its time limit")
                elif record.planning_stop_reason == "plan_discovery_budget_exceeded":
                    self._finish(record, "failed", "plan_discovery_budget_exceeded", "Plan preparation stopped without writing the plan")
                else:
                    self._finish(record, "failed", "manager_error", "Local runner failed to start")
        finally:
            if watchdog_stop is not None:
                watchdog_stop.set()
            if (
                record.request.mode == "new_change"
                and record.status in {"failed", "cancelled", "interrupted"}
            ):
                try:
                    record.planning_cleanup = self._planning_session_cleanup(record.run_id)
                except Exception:
                    record.planning_cleanup = "failed"
            result_observation = self._capture_review()
            with self._lock:
                record.process = None
                terminal = record.status in _TERMINAL
                if terminal:
                    baseline_observation = (record.review or {}).get("baseline")
                    record.review = build_review(baseline_observation, result_observation)
                self._persist_locked()
                if terminal:
                    record.done.set()
            if acquired:
                self._slots.release()

    def _watch_planning(
        self,
        record: _RunRecord,
        stop: threading.Event,
    ) -> None:
        interval = max(0.01, min(0.25, self._planning_stall_seconds / 2))
        while not stop.wait(interval):
            process: subprocess.Popen[str] | None = None
            with self._lock:
                if (
                    record.status in _TERMINAL
                    or record.cancel_requested
                    or record.planning_stop_reason is not None
                ):
                    return
                now = time.monotonic()
                if record.planning_started_monotonic <= 0:
                    continue
                elapsed = now - record.planning_started_monotonic
                inactive = now - record.planning_last_event_monotonic
                if elapsed >= self._planning_timeout_seconds:
                    record.planning_stop_reason = "plan_timeout"
                    record.phase = "stopping"
                    record.message = "Studio is stopping a plan that reached its safety limit"
                    record.updated_at = _now()
                    self._append_timeline(record)
                    self._persist_locked()
                    process = record.process
                elif inactive >= self._planning_stall_seconds and record.phase != "waiting":
                    record.phase = "waiting"
                    record.message = (
                        "No new runner event; Studio is still supervising the bounded plan"
                    )
                    record.updated_at = _now()
                    self._append_timeline(record)
                    self._persist_locked()
            if process is not None:
                self._terminate(process)
                return

    def _consume_event(self, record: _RunRecord, line: str) -> None:
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            return
        if not isinstance(event, dict):
            return
        event_type = str(event.get("type") or "")
        item_type = _event_item_type(event)
        thread_id = event.get("thread_id")
        if event_type == "system":
            thread_id = event.get("session_id")
        projected_phase = runner_phase_from_event(event, mode=record.request.mode)
        contribution = extract_attestation_delivery(event)
        scope = update_scope_outcome(
            record.scope,
            event,
            baseline_violations=record.scope_baseline,
        )
        scope_changed = scope != record.scope
        terminate_for_budget: subprocess.Popen[str] | None = None
        with self._lock:
            record.event_count += 1
            if record.request.mode == "new_change":
                record.planning_last_event_monotonic = time.monotonic()
                record.planning_last_activity_at = _now()
                if _is_contract_authoring_event(event):
                    record.planning_contract_started = True
                if (
                    event_type == "item.started"
                    and item_type == "command_execution"
                    and not record.planning_contract_started
                ):
                    record.planning_inspection_events += 1
                    if (
                        record.planning_inspection_events
                        > self._planning_inspection_limit
                        and record.planning_stop_reason is None
                    ):
                        record.planning_stop_reason = "plan_discovery_budget_exceeded"
                        record.phase = "stopping"
                        record.message = (
                            "Studio is stopping the agent: it kept exploring instead of planning"
                        )
                        terminate_for_budget = record.process
            if contribution is not None:
                record.contribution = contribution
            if scope_changed:
                record.scope = scope
            if isinstance(thread_id, str) and 1 <= len(thread_id) <= 200:
                record.thread_id = thread_id
            if record.planning_stop_reason is None:
                if projected_phase is not None:
                    record.phase, record.message = projected_phase
                elif event_type in {"thread.started", "system", "turn.started"}:
                    record.phase = "working"
                    record.message = (
                        "Agent is starting bounded plan preparation"
                        if record.request.mode == "new_change"
                        else "Agent is working through APatch"
                    )
                elif event_type in {"turn.completed", "result"}:
                    record.phase = "finishing"
                    record.message = (
                        "Agent is finalizing the review handoff"
                        if record.request.mode == "new_change"
                        else "Agent is finishing the work"
                    )
            should_persist = (
                projected_phase is not None
                or event_type
                in {
                    "thread.started",
                    "system",
                    "turn.started",
                    "turn.completed",
                    "result",
                }
                or contribution is not None
                or scope_changed
                or record.planning_stop_reason is not None
            )
            if should_persist:
                record.updated_at = _now()
                self._append_timeline(record)
                self._persist_locked()
        if terminate_for_budget is not None:
            self._terminate(terminate_for_budget)

    @staticmethod
    def _terminate(process: subprocess.Popen[str]) -> None:
        try:
            if process.poll() is not None:
                return
            if os.name == "posix":
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            else:
                process.terminate()
        except (ProcessLookupError, OSError):
            try:
                process.terminate()
            except (ProcessLookupError, OSError):
                pass

    @staticmethod
    def _finish(record: _RunRecord, status: str, outcome: str, message: str) -> None:
        record.status = status
        record.phase = "complete"
        record.outcome = outcome
        record.message = message
        record.ended_at = _now()
        record.updated_at = record.ended_at
        AgentRunManager._append_timeline(record)

    def _project(self, record: _RunRecord) -> dict[str, Any]:
        prepared_requirements = (
            record.plan_handoff.get("requirement_ids", [])
            if record.plan_handoff is not None
            else []
        )
        work_ref = {
            "spec_id": record.request.spec_id or (record.plan_handoff or {}).get("spec_id"),
            "requirement_id": record.request.requirement_id or (prepared_requirements[0] if prepared_requirements else None),
            "governed_session_id": record.request.governed_session_id,
        }
        available_actions: list[str] = []
        if record.status in _TERMINAL and record.request.mode != "new_change":
            available_actions.append("open_review")
        if record.status == "succeeded" and record.plan_handoff is not None:
            available_actions.append("review_plan")
        if record.status in {"queued", "running"}:
            available_actions.append("cancel")
        if record.status in {"failed", "cancelled", "interrupted"}:
            available_actions.append("fix_forward")
        if (
            record.request.governed_session_id
            and record.request.mode != "rollback_preview"
            and record.status in _TERMINAL
        ):
            available_actions.extend(["recover", "rollback_preview"])

        planning = (
            {
                "schema": "apatch.studio.planning-progress.v1",
                "inspection_events": record.planning_inspection_events,
                "inspection_limit": self._planning_inspection_limit,
                "stall_after_seconds": self._planning_stall_seconds,
                "timeout_after_seconds": self._planning_timeout_seconds,
                "last_activity_at": record.planning_last_activity_at or record.started_at or record.updated_at,
                "cleanup": record.planning_cleanup,
            }
            if record.request.mode == "new_change"
            else None
        )
        projection = {
            "schema": "apatch.studio.agent-run.v1",
            "run_id": record.run_id,
            "runner": record.request.runner,
            "mode": record.request.mode,
            "objective": record.request.objective,
            "status": record.status,
            "phase": record.phase,
            "message": record.message,
            "created_at": record.created_at,
            "started_at": record.started_at,
            "ended_at": record.ended_at,
            "outcome": record.outcome,
            "thread_id": record.thread_id,
            "retry_of": record.retry_of,
            "execution_context": (
                record.execution_context.model_dump()
                if record.execution_context is not None
                else None
            ),
            "execution_contract": (
                {
                    "status": "frozen",
                    "spec_id": record.sdd_execution.spec_id,
                    "requirement_id": record.sdd_execution.requirement_id,
                    "actor_id": record.sdd_execution.actor_id,
                    "contract_hash": record.sdd_execution.contract_hash,
                    "envelope_hash": record.sdd_execution.envelope_hash,
                }
                if record.sdd_execution is not None
                else None
            ),
            "event_count": record.event_count,
            "planning": planning,
            "review": record.review,
            "timeline": record.timeline,
            "reviewer_note": record.reviewer_note,
            "contribution": record.contribution,
            "plan_handoff": record.plan_handoff,
            "scope": record.scope,
            "work_ref": work_ref,
            "available_actions": available_actions,
            "persisted": self._journal_status != "error",
            "can_cancel": record.status in {"queued", "running"},
            "can_retry": record.status in {"failed", "cancelled", "interrupted"},
            "failure": explain_failure(
                record.outcome,
                record.status,
                timeout_seconds=self._planning_timeout_seconds,
                inspection_limit=self._planning_inspection_limit,
            ),
        }
        forbidden = {
            "argv",
            "command",
            "cwd",
            "environment",
            "path",
            "pid",
            "prompt",
            "raw",
            "session_token",
            "source",
        }
        if forbidden.intersection(projection):
            raise AssertionError("unsafe run projection")
        return projection
