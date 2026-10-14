"""FastAPI application for the local APatch Studio workspace."""

from __future__ import annotations

from contextlib import asynccontextmanager
import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from apatch_studio import __version__
from apatch_studio.action_facade import (
    AssetActionRequest,
    AssetSearchRequest,
    AssetSuggestRequest,
    EvidenceActionRequest,
    SpecInspectRequest,
    SpecRebindRequest,
    StudioWorkflowError,
    StudioWorkflowFacade,
    SystemActionRequest,
)
from apatch_studio.adapter import APatchStudioAdapter
from apatch_studio.change_details import (
    ChangeDetailNotFound,
    InvalidChangeId,
    recorded_change_patch,
)
from apatch_studio.change_feed import build_unified_change_feed
from apatch_studio.agent_runs import (
    AgentRunManager,
    RunCapacityError,
    RunNotFoundError,
    RunnerUnavailableError,
    RunStateError,
)
from apatch_studio.contribution_workflow import ContributionWorkflow, TimesheetRequest
from apatch_studio.delivery_pack import (
    AcceptanceActRequest,
    AcceptedTimeDecisionRequest,
    DeliveryPackError,
    DeliveryPackWorkflow,
)
from apatch_studio.delivery_workflow import DeliveryActionRequest, GitDeliveryWorkflow
from apatch_studio.edition import StudioEdition, product_projection
from apatch_studio.execution_intents import (
    ExecutionIntentConfirmation,
    ExecutionIntentError,
    ExecutionIntentManager,
    ExecutionIntentTrust,
)
from apatch_studio.intent_store import IntentJournalError
from apatch_studio.governed_work_gateway import (
    APatchGovernedWorkGateway, EvidencePreviewRequest, EvidencePublicationRequest, GovernedWorkGatewayError,
)
from apatch_studio.local_review import (
    LocalReviewHandoff,
    LocalReviewRequest,
    ReviewerNoteRequest,
    ReviewWorkflowError,
)
from apatch_studio.operations import (
    LockReleaseAnswer,
    LockReleaseRequest,
    AgentRunRequest,
    SddExecutionContext,
    SddFreezeRequest,
)
from apatch_studio.policy_workflow import PolicyActionRequest
from apatch_studio.project_documents import (
    InvalidProjectDocumentId,
    ProjectDocumentNotFound,
)
from apatch_studio.run_review import WorkspaceReviewCollector
from apatch_studio.settings_workflow import WorkspaceActionRequest
from apatch_studio.run_store import RunJournalError
from apatch_studio.security import StudioRequestGuard, security_headers
from apatch_studio.lock_authority import LockAuthority, LockAuthorityError, approver_for
from apatch_studio.run_store import default_state_root
from apatch_studio.sdd_workflow import SddWorkflowError, SddWorkflowFacade
from apatch_studio.draft_amendment_workflow import DraftAmendmentWorkflow, DraftProposalRequest, DraftApprovalRequest
from apatch_studio.authoring_workflow import AuthoringWorkflow, AuthoringProposalRequest, AuthoringApprovalRequest, ImplementationCandidateRequest
from apatch_studio.candidate_workflow import CandidateWorkflow
from apatch_studio.judge_amendment_workflow import JudgeAmendmentWorkflow, JudgeAmendmentRequest
from apatch_studio.document_publication_workflow import install_routes as install_document_publication_routes
from apatch_studio.ownership_handoff_workflow import install_routes as install_ownership_handoff_routes
from apatch_studio.contract_intake_workflow import install_routes as install_contract_intake_routes
from apatch_studio.exact_contract_handoffs import ExactContractConfirmation, ExactContractManager, ExactContractTrust
from apatch_studio.exact_contract_delivery import EvidenceBuildRequest


def _frontend_root() -> Path:
    package = Path(__file__).resolve().parent
    bundled = package / "_web"
    if bundled.is_dir():
        return bundled
    checkout = package.parent
    if (checkout / "pyproject.toml").is_file() and (checkout / "frontend" / "package.json").is_file():
        return checkout / "frontend" / "dist"
    return bundled


def _frontend_ready(frontend: Path) -> bool:
    try:
        index = frontend / "index.html"
        if index.stat().st_size > 1024 * 1024:
            return False
        html = index.read_text(encoding="utf-8")
        references = re.findall(r'(?:src|href)\s*=\s*["\']([^"\']+)["\']', html)
        return (
            "__APATCH_STUDIO_SESSION__" in html
            and "/theme-init.js" in references
            and any(ref.startswith("/assets/") and ref.endswith(".js") for ref in references)
            and all(
                ref.startswith(("/assets/", "/theme-init.js"))
                and (frontend / ref.removeprefix("/")).resolve().is_relative_to(frontend.resolve())
                and (frontend / ref.removeprefix("/")).is_file()
                for ref in references
            )
        )
    except (OSError, UnicodeError):
        return False


def _execution_intent_summary(
    manager: ExecutionIntentManager | None,
) -> dict[str, Any]:
    if manager is None:
        return {
            "schema": "apatch.studio.execution-intent-summary.v1",
            "available": False,
            "configured": False,
            "workspace_id": None,
            # Without an intent manager there is no owner-approved Cowork link.
            "cowork_connected": False,
            "pending": 0,
            "attention": 0,
        }
    try:
        return manager.summary()
    except IntentJournalError:
        return {
            "schema": "apatch.studio.execution-intent-summary.v1",
            "available": True,
            "configured": bool(manager.trusted_origins),
            "workspace_id": manager.workspace_id,
            "cowork_connected": manager.cowork_connected,
            "pending": 0,
            "attention": 1,
        }


def _install_owner_preparation_boundary_routes(app, workspace, lock_authority):
    """One missing-boundary preparation gate; never an execution grant.

    A completed signed UI5 metadata intake and the existing certified owner are
    prerequisites. The new boundary only enables the ordinary release/authoring
    workflow. Existing envelopes, profile, tests and sibling locks are untouched.
    """
    import hashlib
    import json
    import re
    from apatch import sdd_contract_intake as native
    from apatch.sdd_integrity import _verify_seal, canonical_hash, freeze_contract
    from apatch.spec import parse_spec_file
    from apatch.spec_ownership import resolve_spec_owned_targets
    from apatch_studio.contract_intake_workflow import ContractIntakeWorkflow

    root = Path(workspace).resolve()

    def refuse(message):
        raise SddWorkflowError(message, code="sdd_preparation_boundary_refused", status_code=409)

    def raw(relative):
        return native._capture(root, relative)

    def digest(data):
        return "sha256:" + hashlib.sha256(data).hexdigest()

    def state(spec_id, requirement_id):
        if not re.fullmatch(r"SPEC-[A-Z0-9][A-Z0-9-]{1,95}", spec_id) or requirement_id != "R1":
            refuse("Only the existing declared R1 preparation boundary is supported")
        if native._capture(root, f".apatch/sdd/envelopes/{spec_id}/R1.json", optional=True) is not None:
            refuse("An existing canonical envelope must use its ordinary boundary workflow")
        if native._capture(root, f".apatch/locks/{spec_id}/R1.json", optional=True) is not None:
            refuse("An existing lock must use its ordinary release workflow")
        if lock_authority.status(spec_id, requirement_id).get("state") != "unlocked":
            refuse("A previous or broken lock boundary must use its ordinary recovery workflow")
        profile_raw = raw(native.PROFILE)
        profile = json.loads(profile_raw)
        _verify_seal(profile, "current preparation boundary owner profile")
        if freeze_contract(profile) != profile:
            refuse("The current frozen owner profile is invalid")
        owner = approver_for(lock_authority.identity_root)
        if (owner.get("kind") != "machine" or owner.get("certified") is not True
                or owner.get("id") != profile["authority"]["actor_id"]):
            refuse("The existing certified profile owner must confirm this boundary")
        workflow = ContractIntakeWorkflow(root, identity_root=lock_authority.identity_root)
        intake = workflow.review(spec_id)
        if intake.get("status") != "prepared" or not isinstance(intake.get("result"), dict):
            refuse("A genuine completed native owner metadata intake is required")
        reviewed = intake.get("review") or {}
        outputs = intake["result"].get("files") or {}
        if (reviewed.get("active_contract_hash") != profile["document_hash"]
                or reviewed.get("authority_id") != owner["id"]
                or reviewed.get("actor_id") == owner["id"]):
            refuse("The signed metadata intake must bind this current owner and a distinct requester")
        candidate_path = f".apatch/sdd/prepared/{spec_id}.json"
        candidate_raw = raw(candidate_path)
        if outputs.get(candidate_path) != digest(candidate_raw):
            refuse("Prepared scope is not the exact completed native intake output")
        package = json.loads(candidate_raw)
        native._candidate(json.dumps(package), spec_id)
        request = package["contract_request"]
        proposed = request.get("obligations") or []
        old = profile["obligations"]
        if (request.get("supersedes_hash") != profile["document_hash"]
                or request.get("baseline_hash") != profile["baseline_hash"]
                or proposed[:-1] != old or len(proposed) != len(old) + 1):
            refuse("All current owner obligations and baseline must remain byte-equivalent")
        gate = proposed[-1]
        envelope = package["task_envelopes"].get("R1")
        ref = spec_id + "#R1"
        if (not isinstance(envelope, dict) or envelope.get("requirement") != ref
                or gate.get("test_id") != ref or gate.get("material") is not True
                or envelope.get("checks") != [gate.get("acceptance_id")]
                or envelope.get("commands") != [gate.get("command")]
                or gate.get("command_hash") != canonical_hash(gate.get("command"))):
            refuse("Exactly one immutable material gate must cover the selected R1")
        assets = gate.get("judge_assets") or []
        bundle_paths = [item["path"] for item in assets if item["path"].endswith("/ui5-inputs.json")]
        if len(bundle_paths) != 1:
            refuse("The approved source-bound UI5 input bundle is required")
        for asset in assets:
            if outputs.get(asset["path"]) != asset["sha256"] or digest(raw(asset["path"])) != asset["sha256"]:
                refuse("Every new judge must be the unchanged completed native intake output")
        bundle = json.loads(raw(bundle_paths[0]))
        writes = envelope.get("allowed_writes")
        if (bundle.get("schema") != "cowork.ui5.source-bound-inputs.v1"
                or bundle.get("actual_source") != str(root)
                or bundle.get("original_profile") != profile
                or bundle.get("source_overlay") is not False
                or writes != bundle.get("source_paths") or len(writes or []) != 5
                or len(set(writes)) != 5 or any(envelope.get(name) for name in ("network", "remote", "services", "allowed_symbols"))):
            refuse("Only the exact five-file source-bound UI5 scope is eligible")
        for item in old:
            for asset in item["judge_assets"]:
                if digest(raw(asset["path"])) != asset["sha256"]:
                    refuse("A preserved current owner judge changed")
        original = bundle.get("original_spec") or {}
        before = original.get("content")
        if not isinstance(before, str) or hashlib.sha256(before.encode()).hexdigest() != original.get("sha256"):
            refuse("Original strict requirement bytes are required")
        spec_path = f"docs/specs/{spec_id}.md"
        source_row = next((row for row in reviewed.get("files", []) if row.get("path") == spec_path), None)
        if source_row is None or source_row.get("before_hash") != digest(before.encode()):
            refuse("The original requirement must be the signed pre-intake source")
        archive_matches = []
        for path, pin in reviewed.get("input_hashes", {}).items():
            if path.startswith(".apatch/sdd/frozen/"):
                value = json.loads(raw(path))
                if value.get("spec_hash") == digest(before.encode()):
                    if digest(raw(path)) != pin or freeze_contract(value) != value or value.get("authority") != profile["authority"]:
                        refuse("Original requirement authority archive changed or belongs to another owner")
                    archive_matches.append(path)
        if not archive_matches:
            refuse("An existing functional owner archive for this original strict SPEC is required")
        after = raw(spec_path).decode()
        if digest(after.encode()) != request.get("spec_hash") or outputs.get(spec_path) != request.get("spec_hash"):
            refuse("Current SPEC is not the exact owner-approved metadata output")
        # Keep every sibling block and the original R1 verification command.
        pattern = r"(?m)^## R1[^\n]*\n"
        start = re.search(pattern, before)
        current_start = re.search(pattern, after)
        if start is None or current_start is None or before[:start.end()] != after[:current_start.end()]:
            refuse("The original strict SPEC preamble changed")
        old_tail = before[start.end():]
        new_tail = after[current_start.end():]
        old_next = re.search(r"(?m)^## R(?:[2-9]|[1-9][0-9]+)\b", old_tail)
        new_next = re.search(r"(?m)^## R(?:[2-9]|[1-9][0-9]+)\b", new_tail)
        if old_next is None or new_next is None or old_tail[old_next.start():] != new_tail[new_next.start():]:
            refuse("Existing sibling requirements must stay unchanged")
        old_block, new_block = old_tail[:old_next.start()], new_tail[:new_next.start()]
        old_owns = re.search(r"(?m)^owns:.*$", old_block)
        new_owns = re.search(r"(?m)^owns:.*$", new_block)
        if old_owns is None or new_owns is None:
            refuse("The original and additive R1 ownership must be explicit")
        owned = lambda row: {part.strip().strip("`") for part in row.split(":", 1)[1].split(",")}
        if owned(new_owns.group(0)) != owned(old_owns.group(0)) | set(writes):
            refuse("Original ownership must remain and only the exact UI5 paths may be added")
        normalized = new_block.replace(new_owns.group(0), old_owns.group(0), 1)
        verify = re.search(r"\(verify: ([^\n]+)\)", old_block)
        if verify is None or not normalized.startswith(old_block.rstrip() + "\n"):
            refuse("The complete original R1 block and verification command cannot be weakened")
        test_paths = re.findall(r"(?:src|tests)/[^\s,)]+", verify.group(1))
        for path in test_paths:
            pin = (bundle.get("regression_pins") or {}).get(path)
            if pin is None or hashlib.sha256(raw(path)).hexdigest() != pin:
                refuse("The original R1 executable judge must remain immutable")
        parsed = parse_spec_file(str(root / spec_path))
        if parsed.id != spec_id or not parsed.strict_ownership:
            refuse("Strict existing SPEC ownership is mandatory")
        resolved = resolve_spec_owned_targets(str(root), [{"target_file": path, "action": "replace" if (root/path).exists() else "create"} for path in writes])
        if not resolved.get("ok") or any({row.get("requirement") for row in resolved.get("owned", []) if row.get("path") == path} != {ref} for path in writes):
            refuse("Each UI5 path must belong only to this declared R1")
        protected = reviewed["input_hashes"]
        subject = {"schema": "apatch.studio.owner-preparation-boundary.v1", "requirement": ref,
            "owner": owner["id"], "profile_raw_hash": digest(profile_raw), "profile": profile["document_hash"],
            "native_intake_snapshot": reviewed["document_hash"], "candidate_hash": digest(candidate_raw),
            "source_scope": writes, "original_requirement_sha256": original["sha256"],
            "protected_authority_inputs": protected, "original_judge_pins": bundle["regression_pins"],
            "preparation_only": True, "implementation_allowed": False, "functional_acceptance": False}
        return {**subject, "snapshot": canonical_hash(subject)}

    route = "/api/v1/specs/{spec_id}/requirements/{requirement_id}/preparation-boundary"

    @app.get(route)
    def review_preparation_boundary(spec_id: str, requirement_id: str):
        return state(spec_id, requirement_id)

    @app.post(route + "/approve")
    def approve_preparation_boundary(spec_id: str, requirement_id: str, request: AuthoringApprovalRequest):
        from apatch import sdd_draft_amendment as draft
        try:
            # Same interprocess boundary and pending-transaction guard as the
            # normal freeze route; every input/owner/snapshot is re-read inside.
            with draft.freeze_lock(root):
                draft.assert_can_freeze(root)
                selected = state(spec_id, requirement_id)
                if request.snapshot != selected["snapshot"]:
                    refuse("Review the exact current preparation-only scope before confirmation")
                # Restrictive lock only: no grant, envelope, signing or Source.
                lock_authority.lock_solo(spec_id, requirement_id)
        except (ValueError, OSError) as exc:
            refuse("Complete or recover the pending owner transaction before preparation: " + str(exc))
        return {"status": "preparation_boundary_locked", "snapshot": selected["snapshot"],
            "lock": lock_authority.view(spec_id, requirement_id), "preparation_only": True,
            "implementation_allowed": False, "functional_acceptance": False,
            "next_action": "Use the normal release request/answer and authoring workflow"}

def create_app(
    workspace: str,
    *,
    adapter: Any | None = None,
    run_manager: Any | None = None,
    frontend_root: str | Path | None = None,
    guard: StudioRequestGuard | None = None,
    edition: StudioEdition | str = StudioEdition.OSS,
    execution_intent_trust: ExecutionIntentTrust | None = None,
    intent_state_root: str | Path | None = None,
    intent_manager: ExecutionIntentManager | None = None,
    workflow_facade: Any | None = None,
    review_handoff: LocalReviewHandoff | None = None,
    delivery_workflow: GitDeliveryWorkflow | None = None,
    contribution_workflow: ContributionWorkflow | None = None,
    delivery_pack_workflow: DeliveryPackWorkflow | None = None,
    sdd_facade: Any | None = None,
    identity_root: str | Path | None = None,
    governed_work_gateway: Any | None = None,
    exact_contract_trust: ExactContractTrust | None = None,
    exact_contract_manager: ExactContractManager | None = None,
    exact_contract_state_root: str | Path | None = None,
) -> FastAPI:
    frontend = Path(frontend_root) if frontend_root else _frontend_root()
    active_edition = StudioEdition.parse(edition)
    runtime_adapter = adapter or APatchStudioAdapter(workspace, nonblocking=True)
    runtime_workflows = workflow_facade or StudioWorkflowFacade(workspace)
    runtime_review = review_handoff or LocalReviewHandoff(workspace)
    runtime_delivery = delivery_workflow or GitDeliveryWorkflow(workspace)
    runtime_contribution = contribution_workflow or ContributionWorkflow(workspace)
    runtime_delivery_pack = delivery_pack_workflow or DeliveryPackWorkflow(workspace)
    runtime_sdd = sdd_facade or SddWorkflowFacade(workspace)
    runtime_authoring = AuthoringWorkflow(workspace)
    runtime_candidates = CandidateWorkflow(workspace)
    runtime_judge_amendments = JudgeAmendmentWorkflow(workspace)
    lock_authority = LockAuthority(
        Path(workspace) / ".apatch",
        identity_root=identity_root or default_state_root(),
    )
    runtime_runs = run_manager or AgentRunManager(
        workspace,
        review_collector=WorkspaceReviewCollector(
            workspace,
            overview_supplier=runtime_adapter.overview,
        ).capture,
    )
    runtime_drafts = DraftAmendmentWorkflow(workspace, runtime_runs)
    runtime_intents = None
    if (
        intent_manager is not None
        or execution_intent_trust is not None
    ):
        runtime_intents = intent_manager or ExecutionIntentManager(
            workspace,
            run_manager=runtime_runs,
            trust=execution_intent_trust,
            state_root=intent_state_root,
        )

    runtime_exact = exact_contract_manager
    if runtime_exact is None and exact_contract_trust is not None:
        runtime_exact = ExactContractManager(
            workspace, run_manager=runtime_runs, trust=exact_contract_trust,
            state_root=exact_contract_state_root, sdd_facade=runtime_sdd,
            actor_id="studio:implementation",
            gateway=(runtime_intents.governed_work_gateway if runtime_intents is not None else None),
        )
    exact_origins = runtime_exact.trust.trusted_origins if runtime_exact is not None else frozenset()
    legacy_origins = runtime_intents.trusted_origins if runtime_intents is not None else frozenset()
    runtime_publication = (governed_work_gateway
        or (runtime_exact.gateway if runtime_exact is not None else None)
        or (runtime_intents.governed_work_gateway if runtime_intents is not None else None)
        or APatchGovernedWorkGateway(workspace))

    request_guard = guard or StudioRequestGuard(
        trusted_execution_origins=legacy_origins | exact_origins
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            yield
        finally:
            runtime_runs.close()

    app = FastAPI(
        title="APatch Studio",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.studio_adapter = runtime_adapter
    app.state.studio_runs = runtime_runs
    app.state.studio_workflows = runtime_workflows
    app.state.studio_review = runtime_review
    app.state.studio_delivery = runtime_delivery
    app.state.studio_contribution = runtime_contribution
    app.state.studio_delivery_pack = runtime_delivery_pack
    app.state.studio_sdd = runtime_sdd
    app.state.studio_guard = request_guard
    app.state.lock_authority = lock_authority
    app.state.studio_edition = active_edition
    app.state.studio_intents = runtime_intents
    app.state.studio_exact_contracts = runtime_exact

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        preflight = request_guard.preflight(request)
        if preflight is not None:
            response = preflight
        else:
            rejected = request_guard.authenticate(request)
            response = rejected if rejected is not None else await call_next(request)
        security_headers(response)
        request_guard.cors_headers(response, request)
        return response

    @app.exception_handler(StudioWorkflowError)
    async def workflow_error(_request: Request, error: StudioWorkflowError):
        return JSONResponse(
            {"ok": False, "error": str(error), "error_code": error.code},
            status_code=error.status_code,
        )

    @app.exception_handler(SddWorkflowError)
    async def sdd_workflow_error(_request: Request, error: SddWorkflowError):
        return JSONResponse(
            {"ok": False, "error": str(error), "error_code": error.code},
            status_code=error.status_code,
        )

    @app.exception_handler(LockAuthorityError)
    async def lock_authority_error(_request: Request, error: LockAuthorityError):
        return JSONResponse(
            {"ok": False, "error": str(error), "error_code": "lock_approver_unknown"},
            status_code=422,
        )

    @app.exception_handler(DeliveryPackError)
    async def delivery_pack_error(_request: Request, error: DeliveryPackError):
        return JSONResponse(
            {"ok": False, "error": str(error), "error_code": error.code},
            status_code=error.status_code,
        )

    @app.exception_handler(RunNotFoundError)
    async def run_not_found(_request: Request, _error: RunNotFoundError):
        return JSONResponse({"ok": False, "error": "run not found"}, status_code=404)

    @app.exception_handler(RunnerUnavailableError)
    async def runner_unavailable(_request: Request, error: RunnerUnavailableError):
        return JSONResponse({"ok": False, "error": str(error)}, status_code=409)

    @app.exception_handler(RunCapacityError)
    async def queue_full(_request: Request, error: RunCapacityError):
        return JSONResponse({"ok": False, "error": str(error)}, status_code=429)

    @app.exception_handler(RunStateError)
    async def invalid_run_state(_request: Request, error: RunStateError):
        return JSONResponse({"ok": False, "error": str(error)}, status_code=409)

    @app.exception_handler(RunJournalError)
    async def journal_unavailable(_request: Request, _error: RunJournalError):
        return JSONResponse({"ok": False, "error": "run journal unavailable"}, status_code=503)

    @app.exception_handler(ReviewWorkflowError)
    async def review_workflow_error(_request: Request, error: ReviewWorkflowError):
        return JSONResponse(
            {"ok": False, "error": str(error), "error_code": error.code},
            status_code=error.status_code,
        )

    @app.exception_handler(InvalidChangeId)
    async def invalid_change_id(_request: Request, _error: InvalidChangeId):
        return JSONResponse({"ok": False, "error": "invalid change id"}, status_code=400)

    @app.exception_handler(ChangeDetailNotFound)
    async def change_not_found(_request: Request, _error: ChangeDetailNotFound):
        return JSONResponse({"ok": False, "error": "change not found"}, status_code=404)

    @app.exception_handler(InvalidProjectDocumentId)
    async def invalid_project_document(
        _request: Request,
        _error: InvalidProjectDocumentId,
    ):
        return JSONResponse(
            {"ok": False, "error": "invalid project document id"},
            status_code=400,
        )

    @app.exception_handler(ProjectDocumentNotFound)
    async def project_document_not_found(
        _request: Request,
        _error: ProjectDocumentNotFound,
    ):
        return JSONResponse(
            {"ok": False, "error": "project document not found"},
            status_code=404,
        )

    @app.exception_handler(IntentJournalError)
    async def intent_journal_unavailable(_request: Request, _error: IntentJournalError):
        return JSONResponse(
            {"ok": False, "error": "execution-intent ledger unavailable"},
            status_code=503,
        )

    @app.exception_handler(ExecutionIntentError)
    async def execution_intent_error(_request: Request, error: ExecutionIntentError):
        return JSONResponse(
            {"ok": False, "error": str(error), "error_code": error.code},
            status_code=error.status_code,
        )

    @app.get("/api/v1/health")
    def health() -> JSONResponse:
        ready = _frontend_ready(frontend)
        return JSONResponse({
            "ok": ready,
            "product": "APatch Studio",
            "edition": active_edition.value,
            "version": __version__,
            "frontend_ready": ready,
        }, status_code=200 if ready else 503)

    def workspace_projection(*, force: bool = False) -> dict[str, Any]:
        projection = dict(runtime_adapter.overview(force=force))
        projection["product"] = product_projection(
            active_edition, execution_intents=runtime_intents is not None,
        )
        projection["execution_intents"] = _execution_intent_summary(runtime_intents)
        return projection

    @app.get("/api/v1/overview")
    def overview() -> dict[str, Any]:
        return workspace_projection()

    @app.post("/api/v1/refresh")
    def refresh() -> dict[str, Any]:
        return workspace_projection(force=True)

    @app.get("/api/v1/documents")
    def document_catalog() -> dict[str, Any]:
        return runtime_adapter.document_catalog()

    @app.get("/api/v1/documents/{document_id}")
    def document_detail(document_id: str) -> dict[str, Any]:
        detail = dict(runtime_adapter.document_detail(document_id))
        if detail.get("kind") == "specification":
            requirements = []
            for raw in detail.get("requirements") or []:
                requirement = dict(raw)
                requirement_id = str(requirement.get("id") or "")
                requirement["execution_contract"] = runtime_sdd.requirement_status(
                    document_id,
                    requirement_id,
                )
                requirements.append(requirement)
            detail["requirements"] = requirements
        return detail

    @app.get(
        "/api/v1/specs/{spec_id}/requirements/{requirement_id}/execution-contract"
    )
    def execution_contract(
        spec_id: str,
        requirement_id: str,
    ) -> dict[str, Any]:
        return runtime_sdd.contract_review(spec_id, requirement_id, with_snapshot=True)


    @app.get("/api/v1/specs/{spec_id}/requirements/{requirement_id}/judge-amendment")
    def review_judge_amendment(spec_id: str, requirement_id: str):
        return runtime_judge_amendments.review(spec_id, requirement_id)

    @app.post("/api/v1/specs/{spec_id}/requirements/{requirement_id}/judge-amendment")
    def propose_judge_amendment(spec_id: str, requirement_id: str, request: JudgeAmendmentRequest):
        return runtime_judge_amendments.propose(spec_id, requirement_id, request)

    @app.post("/api/v1/specs/{spec_id}/requirements/{requirement_id}/judge-amendment/approve")
    def approve_judge_amendment(spec_id: str, requirement_id: str, request: AuthoringApprovalRequest):
        approver = approver_for(lock_authority.identity_root)
        return runtime_judge_amendments.approve(spec_id, requirement_id, request, authority_id=approver["id"])

    @app.get("/api/v1/specs/{spec_id}/requirements/{requirement_id}/authoring")
    def review_authoring(spec_id: str, requirement_id: str) -> dict[str, Any]:
        return runtime_authoring.review(spec_id, requirement_id)

    @app.post("/api/v1/specs/{spec_id}/requirements/{requirement_id}/authoring")
    def propose_authoring(spec_id: str, requirement_id: str, request: AuthoringProposalRequest) -> dict[str, Any]:
        return runtime_authoring.propose(spec_id, requirement_id, request)

    @app.post("/api/v1/specs/{spec_id}/requirements/{requirement_id}/authoring/approve")
    def approve_authoring(spec_id: str, requirement_id: str, request: AuthoringApprovalRequest) -> dict[str, Any]:
        approver = approver_for(lock_authority.identity_root)
        return runtime_authoring.approve(spec_id, requirement_id, request, authority_id=approver["id"])

    @app.get("/api/v1/specs/{spec_id}/requirements/{requirement_id}/implementation-candidate")
    def review_candidate(spec_id: str, requirement_id: str) -> dict[str, Any]:
        return runtime_candidates.review(spec_id, requirement_id)

    @app.post("/api/v1/specs/{spec_id}/requirements/{requirement_id}/implementation-candidate")
    def select_candidate(spec_id: str, requirement_id: str, request: ImplementationCandidateRequest) -> dict[str, Any]:
        return runtime_candidates.select(spec_id, requirement_id, request)

    @app.post("/api/v1/specs/{spec_id}/requirements/{requirement_id}/implementation-candidate/approve")
    def approve_candidate(spec_id: str, requirement_id: str, request: AuthoringApprovalRequest) -> dict[str, Any]:
        approver = approver_for(lock_authority.identity_root)
        return runtime_candidates.approve(spec_id, requirement_id, request, authority_id=approver["id"])

    @app.get("/api/v1/specs/{spec_id}/requirements/{requirement_id}/lock")
    def lock_exchange(spec_id: str, requirement_id: str) -> dict[str, Any]:
        return lock_authority.view(spec_id, requirement_id)

    @app.post(
        "/api/v1/specs/{spec_id}/requirements/{requirement_id}/lock/release-request"
    )
    def request_lock_release(
        spec_id: str,
        requirement_id: str,
        request: LockReleaseRequest,
    ) -> dict[str, Any]:
        # Asking is not lifting. This records the request and returns the
        # exchange; the boundary keeps refusing work until somebody answers.
        lock_authority.request_release(spec_id, requirement_id, reason=request.reason, request_id=request.request_id)
        return lock_authority.view(spec_id, requirement_id)

    @app.post(
        "/api/v1/specs/{spec_id}/requirements/{requirement_id}/lock/release-answer"
    )
    def answer_lock_release(
        spec_id: str,
        requirement_id: str,
        request: LockReleaseAnswer,
    ) -> dict[str, Any]:
        lock_authority.answer_release(
            spec_id,
            requirement_id,
            decision=request.decision,
            reason=request.reason,
            request_id=request.request_id,
        )
        return lock_authority.view(spec_id, requirement_id)

    @app.post(
        "/api/v1/specs/{spec_id}/requirements/{requirement_id}/execution-contract/freeze"
    )
    def freeze_execution_contract(
        spec_id: str,
        requirement_id: str,
        request: SddFreezeRequest,
    ) -> dict[str, Any]:
        # Who approved is settled before anything is frozen. A workspace that
        # can name nobody must not reach the contract at all, because the only
        # name left to write would be a constant, and a constant on an approval
        # reads as evidence while proving nothing.
        approver = approver_for(lock_authority.identity_root)
        if request.snapshot is None:
            raise SddWorkflowError("Review the current scope and tests before confirming",
                code="sdd_approval_snapshot_required", status_code=422)
        review = runtime_sdd.freeze_requirement(
            spec_id,
            requirement_id,
            owner_actor_id=approver["id"],
            confirmed=request.confirmed,
            expected_snapshot=request.snapshot,
        )
        # The lock is recorded after the contract exists, never before. A lock
        # standing over a contract that was never frozen would read as a broken
        # lock, which is a far worse thing to say than nothing at all.
        # Resuming an exact historical agreement neither lifts nor re-locks its
        # existing boundary. A granted release and its journal remain evidence.
        historical_boundary = (
            review.get("resumed_from_approval") == review.get("contract_hash")
            and review.get("contract_hash") is not None
            and lock_authority.read(spec_id, requirement_id) is not None
        )
        if not historical_boundary and not lock_authority.is_locked(spec_id, requirement_id):
            lock_authority.lock_solo(spec_id, requirement_id)
        return review

    @app.post("/api/v1/specs/{spec_id}/inspect")
    def inspect_spec(spec_id: str, request: SpecInspectRequest) -> dict[str, Any]:
        return runtime_workflows.inspect_spec(spec_id, request)

    @app.post("/api/v1/specs/{spec_id}/rebind")
    def rebind_spec(spec_id: str, request: SpecRebindRequest) -> dict[str, Any]:
        return runtime_workflows.rebind_spec(spec_id, request)

    @app.post("/api/v1/evidence/actions")
    def evidence_action(request: EvidenceActionRequest) -> dict[str, Any]:
        return runtime_workflows.evidence_action(request)

    @app.post("/api/v1/assets/search")
    def search_assets(request: AssetSearchRequest) -> dict[str, Any]:
        return runtime_workflows.search_assets(request)

    @app.post("/api/v1/assets/suggest")
    def suggest_assets(request: AssetSuggestRequest) -> dict[str, Any]:
        return runtime_workflows.suggest_assets(request)

    @app.post("/api/v1/assets/{asset_id}/actions")
    def asset_action(asset_id: str, request: AssetActionRequest) -> dict[str, Any]:
        return runtime_workflows.asset_action(asset_id, request)

    @app.post("/api/v1/system/actions")
    def system_action(request: SystemActionRequest) -> dict[str, Any]:
        return runtime_workflows.system_action(request)

    @app.post("/api/v1/policies/actions")
    def policy_action(request: PolicyActionRequest) -> dict[str, Any]:
        return runtime_workflows.policy_action(request)

    @app.post("/api/v1/workspaces/actions")
    def workspace_action(request: WorkspaceActionRequest) -> dict[str, Any]:
        return runtime_workflows.workspace_action(request)

    @app.post("/api/v1/timesheet/actions")
    def timesheet_action(request: TimesheetRequest) -> dict[str, Any]:
        return runtime_contribution.timesheet(request)

    @app.get("/api/v1/contributions/health")
    def contribution_health() -> dict[str, Any]:
        return runtime_contribution.health()

    @app.get("/api/v1/delivery")
    def delivery_status() -> dict[str, Any]:
        return runtime_delivery.status()

    @app.post("/api/v1/delivery/actions")
    def delivery_action(request: DeliveryActionRequest) -> dict[str, Any]:
        return runtime_delivery.act(request)

    @app.get("/api/v1/runners")
    def runners() -> dict[str, Any]:
        return {"schema": "apatch.studio.runner-catalog.v1", "items": runtime_runs.runners()}

    @app.get("/api/v1/runs")
    def list_runs() -> dict[str, Any]:
        return {
            "schema": "apatch.studio.agent-runs.v2",
            "journal": runtime_runs.journal(),
            "items": runtime_runs.list(),
        }

    @app.get("/api/v1/changes")
    def list_changes() -> dict[str, Any]:
        projection = workspace_projection()
        return build_unified_change_feed(
            runtime_runs.list(),
            projection.get("changes") or [],
            workspace=projection,
        )

    def change_projection(change_id: str) -> dict[str, Any]:
        detail = dict(runtime_adapter.change_detail(change_id))
        try:
            detail["sdd"] = {"available": True, **runtime_sdd.change(change_id)}
        except LookupError:
            detail["sdd"] = {
                "schema": "apatch.studio.sdd-change-status.v1",
                "available": False,
                "reason": "legacy_change_without_frozen_contract",
                "message": "This change predates the frozen execution contract.",
            }
        except RuntimeError:
            detail["sdd"] = {
                "schema": "apatch.studio.sdd-change-status.v1",
                "available": False,
                "reason": "sdd_runtime_unavailable",
                "message": "This Studio runtime cannot read the frozen execution contract.",
            }
        return detail

    @app.get("/api/v1/changes/{change_id}")
    def get_change_detail(change_id: str) -> dict[str, Any]:
        return change_projection(change_id)

    @app.get("/api/v1/changes/{change_id}/delivery-pack")
    def get_delivery_pack(change_id: str) -> dict[str, Any]:
        return runtime_delivery_pack.project(change_projection(change_id))

    @app.post("/api/v1/changes/{change_id}/acceptance")
    def record_change_acceptance(
        change_id: str,
        request: AcceptanceActRequest,
    ) -> dict[str, Any]:
        return runtime_delivery_pack.record_acceptance(
            change_projection(change_id),
            request,
        )

    @app.post("/api/v1/changes/{change_id}/time-decision")
    def record_change_time(
        change_id: str,
        request: AcceptedTimeDecisionRequest,
    ) -> dict[str, Any]:
        return runtime_delivery_pack.record_time_decision(
            change_projection(change_id),
            request,
        )

    @app.post("/api/v1/changes/{change_id}/local-review")
    def open_change_local_review(
        change_id: str,
        request: LocalReviewRequest,
    ) -> dict[str, Any]:
        detail = runtime_adapter.change_detail(change_id)
        payload = recorded_change_patch(detail)
        if not payload:
            raise ReviewWorkflowError(
                "This record has no retained patch to open",
                code="recorded_patch_unavailable",
            )
        return runtime_review.open_payload(
            change_id,
            payload,
            request,
            file_count=int((detail.get("summary") or {}).get("file_count") or 0),
        )

    @app.post("/api/v1/runs", status_code=202)
    def start_run(request: AgentRunRequest) -> dict[str, Any]:
        sdd_execution = None
        if request.mode == "requirement":
            binding = runtime_sdd.execution_binding(
                str(request.spec_id),
                str(request.requirement_id),
                actor_id=f"agent:{request.runner}",
            )
            sdd_execution = SddExecutionContext.model_validate(binding).model_dump()
        if sdd_execution is None:
            return runtime_runs.start(request)
        return runtime_runs.start(request, sdd_execution=sdd_execution)

    @app.get("/api/v1/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        return runtime_runs.get(run_id)

    @app.get("/api/v1/runs/{run_id}/draft-amendment")
    def review_draft_amendment(run_id: str) -> dict[str, Any]:
        return runtime_drafts.review(run_id)

    @app.post("/api/v1/runs/{run_id}/draft-amendment")
    def propose_draft_amendment(run_id: str, request: DraftProposalRequest) -> dict[str, Any]:
        return runtime_drafts.propose(run_id, request)

    @app.post("/api/v1/runs/{run_id}/draft-amendment/approve")
    def approve_draft_amendment(run_id: str, request: DraftApprovalRequest) -> dict[str, Any]:
        owner = approver_for(lock_authority.identity_root)
        return runtime_drafts.approve(run_id, request, owner=owner)

    @app.post("/api/v1/runs/{run_id}/cancel")
    def cancel_run(run_id: str) -> dict[str, Any]:
        return runtime_runs.cancel(run_id)

    @app.post("/api/v1/runs/{run_id}/retry", status_code=202)
    def retry_run(run_id: str) -> dict[str, Any]:
        return runtime_runs.retry(run_id)

    @app.post("/api/v1/runs/{run_id}/review-note")
    def save_review_note(run_id: str, request: ReviewerNoteRequest) -> dict[str, Any]:
        return runtime_runs.save_reviewer_note(run_id, request.text)

    @app.post("/api/v1/runs/{run_id}/local-review")
    def open_local_review(run_id: str, request: LocalReviewRequest) -> dict[str, Any]:
        runtime_runs.get(run_id)
        return runtime_review.open(run_id, request)

    if runtime_intents is not None:

        @app.post("/api/v1/execution-intents/import")
        async def import_execution_intent(request: Request) -> dict[str, Any]:
            return runtime_intents.import_raw(await request.body())

        @app.get("/api/v1/execution-intents")
        def list_execution_intents() -> dict[str, Any]:
            return {
                "schema": "apatch.studio.execution-intents.v1",
                "workspace_id": runtime_intents.workspace_id,
                "items": runtime_intents.list(),
            }

        @app.get("/api/v1/execution-intents/{intent_id}")
        def get_execution_intent(intent_id: str) -> dict[str, Any]:
            return runtime_intents.get(intent_id)

        @app.post("/api/v1/execution-intents/{intent_id}/confirm", status_code=202)
        def confirm_execution_intent(
            intent_id: str,
            confirmation: ExecutionIntentConfirmation,
        ) -> dict[str, Any]:
            return runtime_intents.confirm(intent_id, confirmation)

        @app.post("/api/v1/execution-intents/{intent_id}/cancel")
        def cancel_execution_intent(intent_id: str) -> dict[str, Any]:
            return runtime_intents.cancel(intent_id)

    @app.post("/api/v1/exact-contract-handoffs/import")
    async def import_exact_contract(request: Request) -> dict[str, Any]:
        if runtime_exact is None:
            raise ExecutionIntentError("Exact purpose authority pins are not configured", code="exact_authority_unconfigured", status_code=503)
        return runtime_exact.import_raw(await request.body())

    @app.get("/api/v1/exact-contract-handoffs")
    def list_exact_contracts() -> dict[str, Any]:
        if runtime_exact is None:
            raise ExecutionIntentError("Exact purpose authority pins are not configured", code="exact_authority_unconfigured", status_code=503)
        return {"schema": "apatch.studio.exact-contract-list.v1", "workspace_id": runtime_exact.workspace_id, "items": runtime_exact.list()}

    @app.get("/api/v1/exact-contract-handoffs/{handoff_id}")
    def get_exact_contract(handoff_id: str) -> dict[str, Any]:
        if runtime_exact is None:
            raise ExecutionIntentError("Exact purpose authority pins are not configured", code="exact_authority_unconfigured", status_code=503)
        return runtime_exact.get(handoff_id)

    @app.post("/api/v1/exact-contract-handoffs/{handoff_id}/confirm", status_code=202)
    def confirm_exact_contract(handoff_id: str, confirmation: ExactContractConfirmation) -> dict[str, Any]:
        if runtime_exact is None:
            raise ExecutionIntentError("Exact purpose authority pins are not configured", code="exact_authority_unconfigured", status_code=503)
        return runtime_exact.confirm(handoff_id, confirmation)

    @app.get("/api/v1/exact-contract-handoffs/{handoff_id}/delivery-choices")
    def exact_delivery_choices(handoff_id: str) -> dict[str, Any]:
        if runtime_exact is None:
            raise ExecutionIntentError("Exact contract delivery is not configured", code="exact_authority_unconfigured", status_code=503)
        return runtime_exact.delivery_choices(handoff_id)

    @app.get("/api/v1/exact-contract-handoffs/{handoff_id}/delivery")
    def exact_delivery_projection(handoff_id: str) -> dict[str, Any]:
        if runtime_exact is None:
            raise ExecutionIntentError("Exact contract delivery is not configured", code="exact_authority_unconfigured", status_code=503)
        return runtime_exact.delivery_projection(handoff_id)

    @app.post("/api/v1/exact-contract-handoffs/{handoff_id}/confirm-for-delivery", status_code=202)
    def confirm_exact_contract_for_delivery(handoff_id: str, confirmation: ExactContractConfirmation) -> dict[str, Any]:
        if runtime_exact is None:
            raise ExecutionIntentError("Exact contract delivery is not configured", code="exact_authority_unconfigured", status_code=503)
        return runtime_exact.confirm_for_delivery(handoff_id, confirmation)

    @app.post("/api/v1/exact-contract-handoffs/{handoff_id}/build-evidence")
    def build_exact_contract_evidence(handoff_id: str, request: EvidenceBuildRequest) -> dict[str, Any]:
        if runtime_exact is None:
            raise ExecutionIntentError("Exact contract delivery is not configured", code="exact_authority_unconfigured", status_code=503)
        return runtime_exact.build_for_delivery(handoff_id, request.run_id)


    @app.exception_handler(GovernedWorkGatewayError)
    async def publication_error(_request: Request, error: GovernedWorkGatewayError):
        return JSONResponse(
            {"ok": False, "error": str(error), "error_code": error.code}, status_code=409
        )

    @app.post("/api/v1/governed-work/evidence/preview")
    def preview_selected_evidence(request: EvidencePreviewRequest) -> dict[str, Any]:
        return runtime_publication.preview_evidence(binding_id=request.binding_id)

    @app.post("/api/v1/governed-work/evidence/publish")
    def publish_selected_evidence(request: EvidencePublicationRequest) -> dict[str, Any]:
        return runtime_publication.publish_evidence(plan=request.plan, confirmation=request.confirmation)

    install_document_publication_routes(app, workspace, identity_root=identity_root or default_state_root())
    install_ownership_handoff_routes(app, workspace, identity_root=identity_root or default_state_root())
    install_contract_intake_routes(app, workspace, identity_root=identity_root or default_state_root())
    _install_owner_preparation_boundary_routes(app, workspace, lock_authority)

    assets = frontend / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    def index_response() -> HTMLResponse | JSONResponse:
        index = frontend / "index.html"
        if not index.is_file():
            return JSONResponse(
                {
                    "ok": False,
                    "error": "frontend build missing",
                    "action": "npm --prefix frontend run build",
                },
                status_code=503,
            )
        html = index.read_text(encoding="utf-8").replace(
            "__APATCH_STUDIO_SESSION__", request_guard.token
        )
        return HTMLResponse(html)

    @app.get("/")
    def index():
        return index_response()

    @app.get("/theme-init.js", include_in_schema=False)
    def theme_initializer():
        script = frontend / "theme-init.js"
        if not script.is_file():
            return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
        return FileResponse(script, media_type="application/javascript")

    @app.get("/{route:path}")
    def spa(route: str):
        if route.startswith("api/") or route.startswith("assets/"):
            return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
        return index_response()

    return app
