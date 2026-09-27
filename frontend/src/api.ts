import type { DraftRepair } from "./DraftRepairReview";
import type { ImplementationReview } from "./ImplementationCandidateReview";
import type { JudgeReview } from "./JudgeAmendmentReview";
import type { AuthoringReview } from "./AuthoringScopeReview";
import type {
  ActionReceipt,
  AgentRun,
  AssetAction,
  AssetActionResult,
  AgentRunRequest,
  AgentRunsPage,
  ChangeFeedPage,
  DeliveryAcceptanceDecision,
  DeliveryPack,
  EvidenceAction,
  EvidenceActionResult,
  ExecutionIntentPreview,
  ImportedChangeDetail,
  AcceptanceAct,
  AcceptedTimeDecision,
  LocalReviewHandoff,
  DeliveryAction,
  DeliveryReceipt,
  DeliveryStatus,
  ContributionHealth,
  ExecutionIntentsPage,
  PolicyAction,
  ProjectDocument,
  ProjectPlansPage,
  PolicyActionResult,
  RunnerInfo,
  SddContractReview,
  SddLockView,
  SystemAction,
  SystemActionResult,
  TimesheetDimension,
  TimesheetResult,
  WorkspaceAction,
  WorkspaceActionResult,
  SpecActionResult,
  SpecInspectAction,
  WorkspaceOverview,
} from "./types";

const token =
  document.querySelector<HTMLMetaElement>('meta[name="apatch-studio-session"]')?.content ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "X-APatch-Studio-Session": token,
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ error: response.statusText }));
    const detail = Array.isArray(body.detail) ? body.detail[0]?.msg : body.detail;
    throw new Error(body.error ?? detail ?? ("Request failed (" + response.status + ")"));
  }
  return response.json() as Promise<T>;
}


export const loadOverview = () => request<WorkspaceOverview>("/api/v1/overview");

export const loadDocuments = () =>
  request<ProjectPlansPage>("/api/v1/documents");

export const loadDocument = (documentId: string) =>
  request<ProjectDocument>("/api/v1/documents/" + encodeURIComponent(documentId));
export const refreshOverview = () =>
  request<WorkspaceOverview>("/api/v1/refresh", { method: "POST" });

export const loadRunners = async () =>
  (await request<{ items: RunnerInfo[] }>("/api/v1/runners")).items;

export const loadRuns = () => request<AgentRunsPage>("/api/v1/runs");

const draftRepairPath = (runId: string) => "/api/v1/runs/" + encodeURIComponent(runId) + "/draft-amendment";
export const loadDraftRepair = (runId: string) => request<DraftRepair>(draftRepairPath(runId));
export const proposeDraftRepair = (runId: string, reason: string, files: Array<{ path: string; content: string }>) =>
  request<DraftRepair>(draftRepairPath(runId), { method: "POST",
    body: JSON.stringify({ request_id: actionRequestId("draft_prepare"), reason, files }) });
export const approveDraftRepair = (runId: string, snapshot: string) =>
  request<{ ok: boolean; functional_acceptance: false }>(draftRepairPath(runId) + "/approve", { method: "POST",
    body: JSON.stringify({ request_id: actionRequestId("draft_approve"), confirmed: true, snapshot }) });

export const loadChangeFeed = () => request<ChangeFeedPage>("/api/v1/changes");

export const loadChangeDetail = (changeId: string) =>
  request<ImportedChangeDetail>("/api/v1/changes/" + encodeURIComponent(changeId));

export const openChangeLocalReview = (changeId: string) =>
  request<LocalReviewHandoff>(
    "/api/v1/changes/" + encodeURIComponent(changeId) + "/local-review",
    {
      method: "POST",
      body: JSON.stringify({ request_id: actionRequestId("change_review") }),
    },
  );

export const startRun = (payload: AgentRunRequest) =>
  request<AgentRun>("/api/v1/runs", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const cancelRun = (runId: string) =>
  request<AgentRun>("/api/v1/runs/" + encodeURIComponent(runId) + "/cancel", {
    method: "POST",
  });

export const retryRun = (runId: string) =>
  request<AgentRun>("/api/v1/runs/" + encodeURIComponent(runId) + "/retry", {
    method: "POST",
  });

export const saveRunReviewNote = (runId: string, text: string) =>
  request<AgentRun>("/api/v1/runs/" + encodeURIComponent(runId) + "/review-note", {
    method: "POST",
    body: JSON.stringify({ text }),
  });

export const openRunLocalReview = (runId: string) =>
  request<LocalReviewHandoff>("/api/v1/runs/" + encodeURIComponent(runId) + "/local-review", {
    method: "POST",
    body: JSON.stringify({ request_id: actionRequestId("local_review") }),
  });

export const loadDeliveryStatus = () =>
  request<DeliveryStatus>("/api/v1/delivery");

export const runDeliveryAction = (
  action: DeliveryAction,
  confirmed: true,
  message?: string,
) =>
  request<DeliveryReceipt>("/api/v1/delivery/actions", {
    method: "POST",
    body: JSON.stringify({
      request_id: actionRequestId("delivery"),
      action,
      confirmed,
      ...(message ? { message } : {}),
    }),
  });

export const loadContributionHealth = () =>
  request<ContributionHealth>("/api/v1/contributions/health");

export const runTimesheet = (
  action: "draft" | "verify",
  groupBy: TimesheetDimension[],
  since?: string,
  until?: string,
) =>
  request<TimesheetResult>("/api/v1/timesheet/actions", {
    method: "POST",
    body: JSON.stringify({
      request_id: actionRequestId("timesheet"),
      action,
      group_by: groupBy,
      ...(since ? { since } : {}),
      ...(until ? { until } : {}),
    }),
  });

export const importExecutionIntent = (canonicalEnvelope: string) =>
  request<ExecutionIntentPreview>("/api/v1/execution-intents/import", {
    method: "POST",
    body: canonicalEnvelope,
  });

export const actionRequestId = (scope: string) =>
  "apsreq_" + scope + "_" + crypto.randomUUID().replaceAll("-", "");

export const loadDeliveryPack = (changeId: string) =>
  request<DeliveryPack>(
    "/api/v1/changes/" + encodeURIComponent(changeId) + "/delivery-pack",
  );

export const recordAcceptanceAct = (
  changeId: string,
  pack: DeliveryPack,
  decision: DeliveryAcceptanceDecision,
  note: string,
) =>
  request<AcceptanceAct>(
    "/api/v1/changes/" + encodeURIComponent(changeId) + "/acceptance",
    {
      method: "POST",
      body: JSON.stringify({
        request_id: actionRequestId("acceptance"),
        expected_basis_hash: pack.basis_hash,
        decision,
        note: note.trim(),
        confirmed: true,
      }),
    },
  );

export const recordTimeDecision = (
  changeId: string,
  pack: DeliveryPack,
  decision: "accepted" | "rejected",
  acceptedHours: number | null,
  note: string,
) =>
  request<AcceptedTimeDecision>(
    "/api/v1/changes/" + encodeURIComponent(changeId) + "/time-decision",
    {
      method: "POST",
      body: JSON.stringify({
        request_id: actionRequestId("accepted_time"),
        expected_basis_hash: pack.basis_hash,
        expected_effort_hash: pack.effort.effort_hash,
        decision,
        accepted_hours: decision === "accepted" ? acceptedHours : null,
        note: note.trim(),
        confirmed: true,
      }),
    },
  );

export const loadExecutionContract = (specId: string, requirementId: string) =>
  request<SddContractReview>(
    "/api/v1/specs/" + encodeURIComponent(specId) + "/requirements/" + encodeURIComponent(requirementId) + "/execution-contract",
  );

export const loadLockExchange = (specId: string, requirementId: string) =>
  request<SddLockView>(
    "/api/v1/specs/" + encodeURIComponent(specId) + "/requirements/" + encodeURIComponent(requirementId) + "/lock",
  );

export const askToLiftLock = (specId: string, requirementId: string, reason: string) =>
  request<SddLockView>(
    "/api/v1/specs/" + encodeURIComponent(specId) + "/requirements/" + encodeURIComponent(requirementId) + "/lock/release-request",
    {
      method: "POST",
      body: JSON.stringify({ request_id: actionRequestId("lock_release"), reason }),
    },
  );

export const answerLockRelease = (
  specId: string,
  requirementId: string,
  decision: "grant" | "refuse",
  reason: string,
) =>
  request<SddLockView>(
    "/api/v1/specs/" + encodeURIComponent(specId) + "/requirements/" + encodeURIComponent(requirementId) + "/lock/release-answer",
    {
      method: "POST",
      body: JSON.stringify({ request_id: actionRequestId("lock_answer"), decision, reason }),
    },
  );

export const freezeExecutionContract = (
  specId: string, requirementId: string, agreement: { snapshot: string },
) =>
  request<SddContractReview>(
    "/api/v1/specs/" + encodeURIComponent(specId) + "/requirements/" + encodeURIComponent(requirementId) + "/execution-contract/freeze",
    {
      method: "POST",
      body: JSON.stringify({
        request_id: actionRequestId("sdd_freeze"),
        confirmed: true,
        ...agreement,
      }),
    },
  );

export const inspectSpec = (specId: string, action: SpecInspectAction) =>
  request<ActionReceipt<SpecActionResult>>(
    "/api/v1/specs/" + encodeURIComponent(specId) + "/inspect",
    {
      method: "POST",
      body: JSON.stringify({ request_id: actionRequestId("spec"), action }),
    },
  );

export const rebindSpec = (
  specId: string,
  requirementIds: string[],
  excludeRequirementIds: string[],
) =>
  request<ActionReceipt<SpecActionResult>>(
    "/api/v1/specs/" + encodeURIComponent(specId) + "/rebind",
    {
      method: "POST",
      body: JSON.stringify({
        request_id: actionRequestId("rebind"),
        requirement_ids: requirementIds,
        exclude_requirement_ids: excludeRequirementIds,
        confirmed: true,
      }),
    },
  );

export const runPolicyAction = (
  action: PolicyAction,
  fields: Partial<{
    mode: "audit" | "enforce";
    governed_mode: "auto_session" | "strict";
    watcher: "audit" | "revert";
    lease_max_seconds: number;
  }> = {},
  confirmed = false,
) =>
  request<ActionReceipt<PolicyActionResult>>("/api/v1/policies/actions", {
    method: "POST",
    body: JSON.stringify({ request_id: actionRequestId("policy"), action, ...fields, confirmed }),
  });

export const runSystemAction = (action: SystemAction, confirmed = false) =>
  request<ActionReceipt<SystemActionResult>>("/api/v1/system/actions", {
    method: "POST",
    body: JSON.stringify({ request_id: actionRequestId("system"), action, confirmed }),
  });

export const runWorkspaceAction = (
  action: WorkspaceAction,
  alias: string | null = null,
  confirmed = false,
) =>
  request<ActionReceipt<WorkspaceActionResult>>("/api/v1/workspaces/actions", {
    method: "POST",
    body: JSON.stringify({
      request_id: actionRequestId("workspace"),
      action,
      ...(alias ? { alias } : {}),
      confirmed,
    }),
  });

export const searchAssets = (query: string, limit = 20) =>
  request<ActionReceipt<AssetActionResult>>("/api/v1/assets/search", {
    method: "POST",
    body: JSON.stringify({ request_id: actionRequestId("asset_search"), query, limit }),
  });

export const suggestAssets = (objective: string, limit = 5) =>
  request<ActionReceipt<AssetActionResult>>("/api/v1/assets/suggest", {
    method: "POST",
    body: JSON.stringify({ request_id: actionRequestId("asset_suggest"), objective, limit }),
  });

export const runAssetAction = (assetId: string, action: AssetAction, intent = "") =>
  request<ActionReceipt<AssetActionResult>>(
    "/api/v1/assets/" + encodeURIComponent(assetId) + "/actions",
    {
      method: "POST",
      body: JSON.stringify({ request_id: actionRequestId("asset_action"), action, intent }),
    },
  );

export const runEvidenceAction = (
  action: EvidenceAction,
  artifact: string | null,
  scope: "working_tree" | "staged" = "working_tree",
) =>
  request<ActionReceipt<EvidenceActionResult>>("/api/v1/evidence/actions", {
    method: "POST",
    body: JSON.stringify({
      request_id: actionRequestId("evidence"),
      action,
      artifact: artifact || null,
      scope,
    }),
  });

export const loadExecutionIntents = () =>
  request<ExecutionIntentsPage>("/api/v1/execution-intents");

export const confirmExecutionIntent = (
  intentId: string,
  workspaceId: string,
  runnerId: "codex" | "claude",
  mode: "new_change" | "specification",
  specId?: string,
) =>
  request<ExecutionIntentPreview>(
    "/api/v1/execution-intents/" + encodeURIComponent(intentId) + "/confirm",
    {
      method: "POST",
      body: JSON.stringify({
        confirmed: true,
        workspace_id: workspaceId,
        runner_id: runnerId,
        mode,
        ...(specId ? { spec_id: specId } : {}),
      }),
    },
  );

export const cancelExecutionIntent = (intentId: string) =>
  request<ExecutionIntentPreview>(
    "/api/v1/execution-intents/" + encodeURIComponent(intentId) + "/cancel",
    { method: "POST" },
  );

export const loadAuthoringScope = (specId: string, requirementId: string) =>
  request<AuthoringReview>("/api/v1/specs/" + encodeURIComponent(specId) + "/requirements/" + encodeURIComponent(requirementId) + "/authoring");
export const approveAuthoringScope = (specId: string, requirementId: string, snapshot: string) =>
  request<AuthoringReview>("/api/v1/specs/" + encodeURIComponent(specId) + "/requirements/" + encodeURIComponent(requirementId) + "/authoring/approve", {
    method: "POST", body: JSON.stringify({ request_id: "apsreq_" + crypto.randomUUID().replaceAll("-", ""), confirmed: true, snapshot }),
  });

export const loadJudgeAmendment = (specId: string, requirementId: string) =>
  request<JudgeReview>("/api/v1/specs/" + encodeURIComponent(specId) + "/requirements/" + encodeURIComponent(requirementId) + "/judge-amendment");
export const approveJudgeAmendment = (specId: string, requirementId: string, snapshot: string) =>
  request<JudgeReview>("/api/v1/specs/" + encodeURIComponent(specId) + "/requirements/" + encodeURIComponent(requirementId) + "/judge-amendment/approve", {
    method: "POST", body: JSON.stringify({ request_id: "apsreq_" + crypto.randomUUID().replaceAll("-", ""), confirmed: true, snapshot }),
  });

export const loadImplementationCandidate = (specId: string, requirementId: string) =>
  request<ImplementationReview>("/api/v1/specs/" + encodeURIComponent(specId) + "/requirements/" + encodeURIComponent(requirementId) + "/implementation-candidate");
export const approveImplementationCandidate = (specId: string, requirementId: string, snapshot: string) =>
  request<ImplementationReview>("/api/v1/specs/" + encodeURIComponent(specId) + "/requirements/" + encodeURIComponent(requirementId) + "/implementation-candidate/approve", {
    method: "POST", body: JSON.stringify({ request_id: "apsreq_" + crypto.randomUUID().replaceAll("-", ""), confirmed: true, snapshot }),
  });
