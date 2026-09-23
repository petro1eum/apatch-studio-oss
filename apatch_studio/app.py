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
from apatch_studio.result_delivery import (
    ResultDeliveryError,
    ResultPreviewRequest,
    ResultSubmitRequest,
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
) -> FastAPI:
    frontend = Path(frontend_root) if frontend_root else _frontend_root()
    active_edition = StudioEdition.parse(edition)
    runtime_adapter = adapter or APatchStudioAdapter(workspace)
    runtime_workflows = workflow_facade or StudioWorkflowFacade(workspace)
    runtime_review = review_handoff or LocalReviewHandoff(workspace)
    runtime_delivery = delivery_workflow or GitDeliveryWorkflow(workspace)
    runtime_contribution = contribution_workflow or ContributionWorkflow(workspace)
    runtime_delivery_pack = delivery_pack_workflow or DeliveryPackWorkflow(workspace)
    runtime_sdd = sdd_facade or SddWorkflowFacade(workspace)
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

    request_guard = guard or StudioRequestGuard(
        trusted_execution_origins=(
            runtime_intents.trusted_origins if runtime_intents is not None else frozenset()
        )
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

    @app.exception_handler(ResultDeliveryError)
    async def result_delivery_error(_request: Request, error: ResultDeliveryError):
        return JSONResponse(
            {
                "ok": False,
                "error": str(error),
                "error_code": "cowork_result_delivery_failed",
            },
            status_code=409,
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
        lock_authority.request_release(spec_id, requirement_id, reason=request.reason)
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
        if not lock_authority.is_locked(spec_id, requirement_id):
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

        @app.post("/api/v1/execution-intents/{intent_id}/result/preview")
        def preview_execution_intent_result(
            intent_id: str,
            request: ResultPreviewRequest,
        ) -> dict[str, Any]:
            return runtime_intents.preview_result(intent_id, request)

        @app.post(
            "/api/v1/execution-intents/{intent_id}/result/submit",
            status_code=202,
        )
        def submit_execution_intent_result(
            intent_id: str,
            request: ResultSubmitRequest,
        ) -> dict[str, Any]:
            return runtime_intents.submit_result(intent_id, request)

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
