/** Fixed-purpose local Studio calls. No caller-controlled actor, keys or root. */
export interface ExactContractRow {
  handoff_id: string;
  status: string;
  requirement: string | null;
  run_id: string | null;
}
export interface ExactContractChoices {
  handoff_id: string;
  workspace_id: string;
  requirements: Array<{ requirement: string; task_envelope_hash: string }>;
}
export interface ExactContractDelivery {
  handoff_id: string;
  run_id: string | null;
  requirement: string | null;
  status: "not_selected" | "pending_source_ack" | "source_acknowledged" | "awaiting_company";
  source_binding_id: string | null;
  source_binding_hash: string | null;
}
export interface EvidenceReady {
  handoff_id: string;
  run_id: string;
  source_binding_id: string;
  source_binding_hash: string;
  evidence_bundle_hash: string;
  timesheet_hash: string;
  attestation_count: number;
  contribution_event_count: number;
}
export interface SharePlan {
  schema: "apatch.cowork-share-plan.v1";
  platform_origin: string;
  client_subject: string;
  tenant_id: string;
  project_group_id: string;
  scope: "governed_work.evidence_admission";
  evidence_bundle_ref: { bundle_id: string; bundle_hash: string };
  timesheet_ref: { timesheet_id: string; timesheet_hash: string; claimed_active_seconds: number };
  connection_generation: string;
  plan_hash: string;
}
export interface PublicationResult {
  synchronization: { status: "acknowledged" | "queued" | "not_checked_this_request"; delivered: number; pending: number };
  customer_decision: "not_requested";
}
export interface ArtifactPreview {
  handoff_id: string; run_id: string; package_hash: string; platform_origin: string; project_group_id: string;
  files: Array<{path: string; sha256: string}>;
}

export async function previewExactArtifacts(handoffId: string, runId: string, signal?: AbortSignal): Promise<ArtifactPreview> {
  const v = await call(endpoint(handoffId) + '/preview-artifacts', {confirmed: true, run_id: text(runId, RUN)}, signal);
  if (v.schema !== 'apatch.studio.exact-artifact-preview.v1' || v.handoff_id !== handoffId || v.run_id !== runId
      || v.customer_accepted !== false || !Array.isArray(v.files) || !v.files.length || v.files.length > 256) invalid();
  text(v.package_hash, HASH); text(v.project_group_id, /^tcpg_[a-f0-9]{32}$/);
  const origin = new URL(v.platform_origin);
  if (origin.protocol !== 'https:' || origin.username || origin.password || origin.search || origin.hash) invalid();
  const files: Array<{path: string; sha256: string}> = v.files.map((value: unknown) => { const f = object(value); exactKeys(f, ['path', 'sha256']);
    if (typeof f.path !== 'string' || !f.path || f.path.length > 256 || f.path.split('/').some((p: string) => !p || p.startsWith('.'))
        || f.path.includes('\\') || /[\x00-\x1f]/.test(f.path)) invalid();
    return {path: f.path, sha256: text(f.sha256, HASH)}; });
  if (new Set(files.map(f => f.path)).size !== files.length) invalid();
  return {handoff_id: handoffId, run_id: runId, package_hash: v.package_hash, platform_origin: origin.origin,
    project_group_id: v.project_group_id, files};
}

export async function publishExactArtifacts(preview: ArtifactPreview, signal?: AbortSignal): Promise<void> {
  const v = await call(endpoint(preview.handoff_id) + '/publish-artifacts', {confirmed: true,
    run_id: text(preview.run_id, RUN), expected_package_hash: text(preview.package_hash, HASH)}, signal);
  if (v.schema !== 'apatch.studio.exact-artifact-delivery.v1' || v.handoff_id !== preview.handoff_id || v.run_id !== preview.run_id
      || v.package_hash !== preview.package_hash || v.file_count !== preview.files.length || v.delivered !== true
      || v.customer_accepted !== false) invalid();
}

const HASH = /^sha256:[0-9a-f]{64}$/;
const HANDOFF = /^tceh_[0-9a-f]{32}$/;
const RUN = /^apr_[0-9a-f]{32}$/;
const SOURCE = /^tcpsb_[0-9a-f]{32}$/;
const REQUIREMENT = /^SPEC-[A-Z0-9][A-Z0-9-]*#R[0-9]+$/;
type Raw = Record<string, any>;

export class ExactDeliveryApiError extends Error {
  constructor(public readonly code: string) { super("The selected contract operation could not be completed."); }
}
function invalid(): never { throw new ExactDeliveryApiError("invalid_delivery_response"); }
function object(value: unknown): Raw { if (!value || typeof value !== "object" || Array.isArray(value)) invalid(); return value as Raw; }
function text(value: unknown, pattern: RegExp): string { if (typeof value !== "string" || !pattern.test(value)) invalid(); return value; }
function count(value: unknown): number { if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) invalid(); return value; }
function exactKeys(value: Raw, keys: string[]): void { if (Object.keys(value).sort().join("|") !== [...keys].sort().join("|")) invalid(); }
function endpoint(handoffId: string): string { return "/api/v1/exact-contract-handoffs/" + encodeURIComponent(text(handoffId, HANDOFF)); }

async function call(path: string, body?: unknown, signal?: AbortSignal): Promise<Raw> {
  const token = document.querySelector<HTMLMetaElement>('meta[name="apatch-studio-session"]')?.content ?? "";
  const response = await fetch(path, { method: body === undefined ? "GET" : "POST", signal,
    headers: { "X-APatch-Studio-Session": token, ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
  const result = object(await response.json());
  if (!response.ok) {
    // Native/transport diagnostic text can contain paths or private data.
    // Only bounded error codes reach presentation; never render raw errors.
    const code = typeof result.error_code === "string" && /^[a-z][a-z0-9_]{0,95}$/.test(result.error_code)
      ? result.error_code : "delivery_request_failed";
    throw new ExactDeliveryApiError(code);
  }
  return result;
}

export async function listExactContracts(signal?: AbortSignal) {
  const value = await call("/api/v1/exact-contract-handoffs", undefined, signal);
  if (value.schema !== "apatch.studio.exact-contract-list.v1" || !Array.isArray(value.items) || value.items.length > 256) invalid();
  return { workspace_id: text(value.workspace_id, /^[0-9a-f]{32}$/), items: value.items.map((raw: unknown): ExactContractRow => {
    const row = object(raw);
    return { handoff_id: text(row.handoff_id, HANDOFF), status: typeof row.status === "string" ? row.status : "unavailable",
      requirement: row.requirement === null ? null : text(row.requirement, REQUIREMENT), run_id: row.run_id === null ? null : text(row.run_id, RUN) };
  }) };
}
export async function importExactContract(raw: string, signal?: AbortSignal) {
  const token = document.querySelector<HTMLMetaElement>('meta[name="apatch-studio-session"]')?.content ?? "";
  const response = await fetch("/api/v1/exact-contract-handoffs/import", { method: "POST", signal,
    headers: { "X-APatch-Studio-Session": token, "Content-Type": "application/json" }, body: raw });
  if (!response.ok) throw new ExactDeliveryApiError("exact_contract_import_failed");
}
export async function readExactChoices(handoffId: string, signal?: AbortSignal): Promise<ExactContractChoices> {
  const value = await call(endpoint(handoffId) + "/delivery-choices", undefined, signal);
  if (value.schema !== "apatch.studio.exact-contract-delivery-choices.v1" || value.handoff_id !== handoffId
    || value.action !== "confirm_for_delivery" || !Array.isArray(value.requirements) || value.requirements.length < 1 || value.requirements.length > 256) invalid();
  const requirements = value.requirements.map((raw: unknown) => { const row = object(raw);
    return { requirement: text(row.requirement, REQUIREMENT), task_envelope_hash: text(row.task_envelope_hash, HASH) }; });
  if (new Set(requirements.map((row: { requirement: string }) => row.requirement)).size !== requirements.length) invalid();
  return { handoff_id: handoffId, workspace_id: text(value.workspace_id, /^[0-9a-f]{32}$/), requirements };
}
function delivery(value: Raw, handoffId: string): ExactContractDelivery {
  if (value.schema !== "apatch.studio.exact-contract-delivery-view.v1" || value.handoff_id !== handoffId
    || value.customer_accepted !== false || value.ready_for_publication !== false
    || !["not_selected", "pending_source_ack", "source_acknowledged", "awaiting_company"].includes(value.status)) invalid();
  return { handoff_id: handoffId, run_id: value.run_id === null ? null : text(value.run_id, RUN),
    requirement: value.requirement === null ? null : text(value.requirement, REQUIREMENT), status: value.status,
    source_binding_id: value.source_binding_id === null ? null : text(value.source_binding_id, SOURCE),
    source_binding_hash: value.source_binding_hash === null ? null : text(value.source_binding_hash, HASH) };
}
export async function readExactDelivery(handoffId: string, signal?: AbortSignal) { return delivery(await call(endpoint(handoffId) + "/delivery", undefined, signal), handoffId); }
export async function runExactForDelivery(handoffId: string, workspaceId: string, runnerId: "codex" | "claude", requirement: string, signal?: AbortSignal) {
  return delivery(await call(endpoint(handoffId) + "/confirm-for-delivery", {
    confirmed: true, workspace_id: text(workspaceId, /^[0-9a-f]{32}$/), runner_id: runnerId, requirement: text(requirement, REQUIREMENT),
  }, signal), handoffId);
}
export async function readExactRun(runId: string, signal?: AbortSignal): Promise<string> {
  const value = await call("/api/v1/runs/" + encodeURIComponent(text(runId, RUN)), undefined, signal);
  if (value.run_id !== runId || !["queued", "running", "succeeded", "failed", "interrupted", "cancelled"].includes(value.status)) invalid();
  return value.status;
}
export async function buildExactEvidence(handoffId: string, runId: string, signal?: AbortSignal): Promise<EvidenceReady> {
  const value = await call(endpoint(handoffId) + "/build-evidence", { confirmed: true, run_id: text(runId, RUN) }, signal);
  if (value.schema !== "apatch.studio.exact-contract-evidence-ready.v1" || value.handoff_id !== handoffId || value.run_id !== runId
    || value.ready_for_publication !== true || value.customer_accepted !== false) invalid();
  return { handoff_id: handoffId, run_id: runId, source_binding_id: text(value.source_binding_id, SOURCE),
    source_binding_hash: text(value.source_binding_hash, HASH), evidence_bundle_hash: text(value.evidence_bundle_hash, HASH),
    timesheet_hash: text(value.timesheet_hash, HASH), attestation_count: count(value.attestation_count), contribution_event_count: count(value.contribution_event_count) };
}
function validatePlan(raw: unknown): SharePlan {
  const value = object(raw);
  exactKeys(value, ["schema", "platform_origin", "client_subject", "tenant_id", "project_group_id", "scope", "evidence_bundle_ref", "timesheet_ref", "connection_generation", "plan_hash"]);
  exactKeys(object(value.evidence_bundle_ref), ["bundle_id", "bundle_hash"]);
  exactKeys(object(value.timesheet_ref), ["timesheet_id", "timesheet_hash", "claimed_active_seconds"]);
  if (value.schema !== "apatch.cowork-share-plan.v1" || value.scope !== "governed_work.evidence_admission") invalid();
  text(value.platform_origin, /^https?:\/\/[^\s]+$/); text(value.client_subject, /^.{1,256}$/); text(value.tenant_id, /^.{1,128}$/);
  text(value.project_group_id, /^tcpg_[0-9a-f]{32}$/); text(value.connection_generation, HASH); text(value.plan_hash, HASH);
  text(value.evidence_bundle_ref.bundle_id, /^apweb_[0-9a-f]{32}$/); text(value.evidence_bundle_ref.bundle_hash, HASH);
  text(value.timesheet_ref.timesheet_id, /^apts_[0-9a-f]{32}$/); text(value.timesheet_ref.timesheet_hash, HASH); count(value.timesheet_ref.claimed_active_seconds);
  // Preserve exactly the native closed document. No UI role/root fields added.
  return value as SharePlan;
}
export async function previewExactEvidence(bindingId: string, signal?: AbortSignal): Promise<SharePlan> {
  const value = await call("/api/v1/governed-work/evidence/preview", { binding_id: text(bindingId, SOURCE) }, signal);
  if (value.ok !== true || value.operation !== "preview_evidence_publication") invalid();
  return validatePlan(value.plan);
}
export async function publishExactEvidence(plan: SharePlan, signal?: AbortSignal): Promise<PublicationResult> {
  validatePlan(plan);
  const value = await call("/api/v1/governed-work/evidence/publish", { plan, confirmation: "publish:" + plan.plan_hash }, signal);
  const synchronization = object(value.synchronization);
  if (value.ok !== true || value.operation !== "publish_evidence" || value.plan_hash !== plan.plan_hash || value.customer_decision !== "not_requested"
    || !["acknowledged", "queued", "not_checked_this_request"].includes(synchronization.status)) invalid();
  return { synchronization: { status: synchronization.status, delivered: count(synchronization.delivered), pending: count(synchronization.pending) }, customer_decision: "not_requested" };
}

/** A performer cannot supply stop facts; the independent native observer computes them. */
export async function stopExactWorkForReassignment(handoffId:string,workspaceId:string,signal?:AbortSignal):Promise<"stop_requested"|"stopped"|"completed"> {
  const value=await call(endpoint(handoffId)+"/stop-for-reassignment",{workspace_id:text(workspaceId,/^[0-9a-f]{32}$/)},signal);
  if(value.schema!=="trustchain.cowork.work-handoff.v1" || !["stop_requested","stopped","completed"].includes(value.state)
    || !value.request || !/^tcwh_[0-9a-f]{32}$/.test(value.request.request_id)
    || !Array.isArray(value.acknowledged_observers) || value.acknowledged_observers.length===0) invalid();
  return value.state;
}
