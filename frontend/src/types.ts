
export type WorkMode =
  | "new_change"
  | "requirement"
  | "specification"
  | "spec_scaffold"
  | "recovery"
  | "rollback_preview";
export type RunnerId = "codex" | "claude";

export interface AgentRunRequest {
  mode: WorkMode;
  runner: RunnerId;
  objective: string;
  acceptance_criteria?: string[];
  spec_id?: string;
  requirement_id?: string;
  rfp_id?: string;
  work_asset_id?: string;
  governed_session_id?: string;
}

export interface ExecutionContext {
  schema: "apatch.studio.execution-context.v1";
  intent_id: string;
  tenant_id: string;
  project_group_id: string;
  work_item_id: string;
  work_item_hash: string;
  authority_version: number;
  work_program_id: string;
  work_program_hash: string;
  document_hash: string;
  envelope_hash: string;
}

export interface SddContractStatus {
  schema: "apatch.studio.sdd-contract-status.v1";
  status: "not_prepared" | "ready_for_owner" | "frozen" | "invalid";
  reason: string | null;
  contract_hash: string | null;
  envelope_hash: string | null;
}

export interface SddLockView {
  schema: "apatch.studio.lock-view.v1";
  spec_id: string;
  requirement_id: string;
  state: "unlocked" | "locked" | "awaiting_answer" | "released" | "broken";
  headline: string;
  explanation: string | null;
  agreed_by: { role: string | null; name: string | null; is_person: boolean; self_asserted: boolean }[];
  agreed_at: string | null;
  approved_by_a_person: boolean;
  exchanges: {
    asked_by: string | null;
    asked_at: string | null;
    reason: string | null;
    one_sided: boolean;
    answered_by: string | null;
    answered_at: string | null;
    answer: "grant" | "refuse" | null;
    answer_reason: string | null;
    outcome: string | null;
  }[];
}

export interface SddContractReview {
  approval_snapshot?: string;
  schema: "apatch.studio.sdd-contract-review.v1";
  status: "ready_for_owner" | "frozen";
  spec_id: string;
  requirement_id: string;
  objective: string;
  prepared_at: string;
  owner_confirmation_required: boolean;
  owner_actor_id: string | null;
  frozen_at: string | null;
  contract_hash: string | null;
  envelope_hash: string | null;
  scope: {
    allowed_reads: string[];
    allowed_writes: string[];
    allowed_symbols: string[];
    forbidden_paths: string[];
    tools: string[];
    commands: Array<string | string[]>;
    network: string[];
    remote: string[];
    services: string[];
    checks: string[];
  };
  budgets: Record<string, number>;
  containment: string;
  rollback_owner: string;
  checks: Array<{
    acceptance_id: string;
    test_id: string;
    oracle: string;
    perspectives: string[];
    observed_red: boolean;
    falsification_expected: string | null;
    material: boolean;
  }>;
}

export interface ExecutionIntentPreview {
  schema: "apatch.studio.execution-intent-preview.v1";
  intent_id: string;
  tenant_id: string;
  project_group_id: string;
  work_item_id: string;
  work_item_hash: string;
  authority_version: number;
  work_program_id: string;
  work_program_hash: string;
  objective: string;
  acceptance_criteria: string[];
  issued_at: string;
  expires_at: string;
  received_at: string;
  status: string;
  document_hash: string;
  envelope_hash: string;
  run_id: string | null;
  cowork: {
    connected: boolean;
    required: boolean;
    status:
      | "not_connected"
      | "local_only"
      | "awaiting_local_acceptance"
      | "accepting"
      | "acceptance_failed"
      | "source_bound";
    change_id: string | null;
    source_binding_id: string | null;
  };
  can_confirm: boolean;
  can_cancel: boolean;
}

export interface ExecutionIntentsPage {
  schema: "apatch.studio.execution-intents.v1";
  workspace_id: string;
  items: ExecutionIntentPreview[];
}

export interface RunnerInfo {
  id: RunnerId;
  label: string;
  available: boolean;
}

export interface WorkspaceObservation {
  schema: string;
  captured_at: string;
  branch: string;
  head: string | null;
  dirty_files: number;
  insertions: number;
  deletions: number;
  attested_requirements: number;
  stale_requirements: number;
  evidence_events: number;
  work_assets: number;
}

export interface RunReview {
  schema: string;
  baseline: WorkspaceObservation | null;
  result: WorkspaceObservation | null;
  delta: ({
    dirty_files: number;
    insertions: number;
    deletions: number;
    attested_requirements: number;
    stale_requirements: number;
    evidence_events: number;
    work_assets: number;
    head_changed: boolean;
    branch_changed: boolean;
  }) | null;
  attribution: "workspace_observation_only";
}

export interface RunJournalStatus {
  schema: string;
  persistent: boolean;
  status: string;
  warning: string | null;
  record_count: number;
  retention: number;
  interrupted_on_start: number;
}

export interface AgentRunsPage {
  schema: string;
  journal: RunJournalStatus;
  items: AgentRun[];
}

export interface EndpointIdentity {
  schema: "apatch.studio.endpoint-identity.v1";
  enrolled: boolean;
  machine_name: string | null;
  has_certificate: boolean;
  headline: string;
  explanation: string;
  next_step: string;
}

export interface RuntimeRequirements {
  schema: "apatch.studio.runtime-requirements.v1";
  installed_version: string;
  required_version: string;
  version_ok: boolean;
  fixes: Array<{ id: string; label: string; present: boolean }>;
  missing: string[];
  ok: boolean;
  headline: string;
  explanation: string;
  next_step: string;
}

export interface RunFailure {
  schema: "apatch.studio.run-failure.v1";
  outcome: string | null;
  headline: string;
  explanation: string;
  next_step: string;
  retryable: boolean;
}

export interface AgentRun {
  schema: string;
  run_id: string;
  runner: RunnerId;
  mode: WorkMode;
  objective: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled" | "interrupted";
  phase: string;
  message: string;
  created_at: string;
  started_at: string | null;
  ended_at: string | null;
  outcome: string | null;
  thread_id: string | null;
  retry_of: string | null;
  execution_context: ExecutionContext | null;
  execution_contract: {
    status: "frozen";
    spec_id: string;
    requirement_id: string;
    actor_id: string;
    contract_hash: string;
    envelope_hash: string;
  } | null;
  event_count: number;
  planning: {
    schema: "apatch.studio.planning-progress.v1";
    inspection_events: number;
    inspection_limit: number;
    stall_after_seconds: number;
    timeout_after_seconds: number;
    last_activity_at: string;
  } | null;
  review: RunReview | null;
  timeline: Array<{ at: string; phase: string; message: string }>;
  reviewer_note: { schema: string; text: string; updated_at: string } | null;
  contribution: {
    contribution_receipt: { status?: string; code?: string; event_id?: string } | null;
    avatar_sync: { ok?: boolean; status?: string; retryable?: boolean; outbox_preserved?: boolean; pending_outbox_items?: number; complete?: boolean; action_required?: string[] } | null;
  } | null;
  plan_handoff: {
    schema: "apatch.studio.plan-handoff.v1";
    status: "review_ready";
    spec_id: string;
    requirement_ids: string[];
    objective: string;
    prepared_at: string;
    package_hash: string;
  } | null;
  scope: {
    schema: "apatch.studio.scope-outcome.v1";
    status: "pending" | "clean" | "protected" | "attention";
    audit_observed: boolean;
    planned_file_count: number;
    logical_areas: Array<"frontend" | "backend" | "tests" | "docs" | "configuration" | "other">;
    blocked_out_of_scope: number;
    reverted_out_of_scope: number;
    unresolved_out_of_scope: number;
  };
  work_ref: {
    spec_id: string | null;
    requirement_id: string | null;
    governed_session_id: string | null;
  };
  available_actions: Array<
    "open_review" | "review_plan" | "cancel" | "fix_forward" | "recover" | "rollback_preview"
  >;
  persisted: boolean;
  can_cancel: boolean;
  can_retry: boolean;
  failure: RunFailure | null;
}


export interface ImportedChange {
  schema: "apatch.studio.imported-change.v1";
  change_id: string;
  governed_session_id: string;
  objective: string;
  status: "proven" | "recorded" | "rolled_back";
  created_at: string;
  updated_at: string;
  spec_id: string | null;
  requirement_id: string | null;
  file_count: number;
  logical_areas: Array<"frontend" | "backend" | "tests" | "docs" | "configuration" | "other">;
  insertions: number;
  deletions: number;
  mutation_count: number;
  attestation_count: number;
  signed_event_count: number;
  latest_record_id: string | null;
  latest_signer: string | null;
}

export interface ProjectBrief {
  schema: "apatch.studio.project-brief.v1";
  title: string;
  purpose: string;
  highlights: string[];
  description_missing: boolean;
  document_id: "PROJECT-README" | null;
}

export type ProjectDocumentBlock =
  | { type: "heading"; level: number; text: string }
  | { type: "paragraph" | "quote"; text: string }
  | { type: "list"; ordered: boolean; items: string[] }
  | { type: "table"; headers: string[]; rows: string[][] }
  | { type: "code"; language: string | null; text: string }
  | { type: "divider" };

export interface ProjectDocumentSection {
  title: string;
  blocks: ProjectDocumentBlock[];
}

export interface ProjectAcceptanceCriterion {
  id: string;
  requirement: string;
  level: string;
  requirement_ids?: string[];
}

export interface ProjectRequirement {
  id: string;
  title: string;
  statement: string;
  state: string;
  state_label: string;
  acceptance: ProjectAcceptanceCriterion | null;
  verification: {
    outcome: "passed_and_recorded" | "needs_recheck" | "blocked" | "not_run";
    label: string;
    explanation: string;
  };
  available_action: "run" | "recheck" | "inspect_proof";
  execution_contract: SddContractStatus;
  technical: { content_hash: string; verification_command: string };
}

export interface ProjectPlan {
  id: string;
  spec_id: string | null;
  proposal_id: string | null;
  title: string;
  purpose: string;
  state: "proposal" | "planned" | "in_progress" | "complete" | "needs_recheck" | "blocked" | "unavailable";
  state_label: string;
  progress: { complete: number; total: number; percent: number };
  next_requirement_id: string | null;
  open_document_id: string;
}

export interface ProjectPlansPage {
  schema: "apatch.studio.project-plans.v1";
  count: number;
  items: ProjectPlan[];
}

export interface ProjectDocument {
  schema: "apatch.studio.project-document.v1";
  id: string;
  kind: "project_brief" | "proposal" | "specification";
  title: string;
  summary: string;
  status?: string;
  sections?: ProjectDocumentSection[];
  acceptance?: ProjectAcceptanceCriterion[];
  paired_spec_ids?: string[];
  proposal_id?: string | null;
  requirements?: ProjectRequirement[];
  traceability?: {
    status: "complete" | "missing" | "ambiguous";
    mappings: Array<{ acceptance_id: string; requirement_id: string }>;
    missing_acceptance_ids: string[];
    ambiguous_acceptance_ids: string[];
    ambiguous_requirement_ids: string[];
    invalid_links: string[];
  };
  technical: { document_hash: string; byte_count: number };
}

export interface ProjectDecisionBasis {
  schema: "apatch.studio.decision-basis.v1";
  specification: { id: string; title: string };
  requirement: {
    id: string;
    title: string;
    statement: string;
    state: string;
    state_label: string;
  };
  proposal: {
    id: string;
    title: string | null;
    criterion: ProjectAcceptanceCriterion | null;
  } | null;
  verification: ProjectRequirement["verification"];
  technical: ProjectRequirement["technical"];
}

export interface SddChangeProjection {
  schema: "apatch.studio.sdd-change.v1";
  available: true;
  change_id: string;
  objective: string;
  authority: { label: string };
  scope: {
    containment: "mediated_only" | "sealed";
    allowed: string[];
    forbidden: string[];
    budgets: Record<string, number>;
    violations: Array<{ effect: string; status: "blocked"; count: number }>;
    amendment: { status: string };
  };
  verification: {
    capability: "non_mutating";
    collected: number;
    executed: number;
    passed: number;
    failed: number;
    skipped: number;
    perspectives: string[];
    falsification: { observed_red: boolean; restored_green: boolean };
    gate_quality: "meaningful" | "incomplete";
    accepted: boolean;
    reasons: string[];
    checks: Array<{
      acceptance_id: string | null;
      test_id: string | null;
      oracle: string;
      perspectives: string[];
    }>;
  };
  proof: {
    status: "proven" | "needs_attention";
    contract_hash: string | null;
    envelope_hash: string | null;
    actor: string;
    mutation_count: number;
    adherence: string;
    checkpoint_refs: string[];
    ledger_refs: string[];
    evidence_hash: string | null;
  };
  timeline: Array<{ kind: string; label: string; reason: string; at: string }>;
  effort: {
    derivation: "signed_event_op_spacing" | "unavailable";
    draft_hours: number | null;
    quality: "verified_estimate" | "unavailable";
    accepted_time: false;
    reason: string | null;
    signed_event_count: number;
    verification: {
      ok: boolean;
      status: string;
      checked: number;
      signed_event_count: number;
      event_ids: string[];
      key_ids: string[];
      ledger_drift_count: number;
      unsigned_count: number;
    };
    method_note: string;
  };
}

export interface SddUnavailableProjection {
  schema: "apatch.studio.sdd-change-status.v1";
  available: false;
  reason: "legacy_change_without_frozen_contract" | "sdd_runtime_unavailable";
  message: string;
}

export type DeliveryAcceptanceDecision =
  | "accepted"
  | "accepted_with_reservations"
  | "changes_requested"
  | "rejected";

export interface DeliveryAuthority {
  schema: "apatch.studio.delivery-authority.v1";
  actor_id: string;
  label: string;
  trust: "local-self-signed" | "organization-authority";
  key_id: string;
  public_key: string;
}

export interface DeliverySignature {
  algorithm: "Ed25519";
  key_id: string;
  purpose: "delivery.acceptance.record" | "delivery.time.record";
  value: string;
}

export interface AcceptanceAct {
  schema: "apatch.studio.acceptance-act.v1";
  act_id: string;
  revision: number;
  change_id: string;
  basis_hash: string;
  test_protocol_hash: string;
  decision: DeliveryAcceptanceDecision;
  note: string;
  technical_gaps: string[];
  result_status: string;
  recorded_at: string;
  authority: DeliveryAuthority;
  signature: DeliverySignature;
}

export interface AcceptedTimeDecision {
  schema: "apatch.studio.accepted-time-decision.v1";
  decision_id: string;
  revision: number;
  change_id: string;
  basis_hash: string;
  effort_hash: string;
  decision: "accepted" | "rejected";
  accepted_hours: number | null;
  draft_hours: number;
  note: string;
  recorded_at: string;
  authority: DeliveryAuthority;
  signature: DeliverySignature;
}

export interface DeliveryTestProtocol {
  schema: "apatch.studio.test-protocol.v1";
  status: "passed" | "failed" | "incomplete" | "not_recorded";
  meaningful: boolean;
  counts: {
    collected: number;
    executed: number;
    passed: number;
    failed: number;
    skipped: number;
  };
  perspectives: string[];
  missing_perspectives: string[];
  falsification: { observed_red: boolean; restored_green: boolean };
  checks: Array<{
    acceptance_id: string | null;
    test_id: string | null;
    oracle: string;
    perspectives: string[];
  }>;
  check_detail_status: "recorded" | "not_recorded";
  contract_hash: string | null;
  envelope_hash: string | null;
  evidence_hash: string | null;
  blockers: string[];
  protocol_hash: string;
}

export interface DeliveryPack {
  schema: "apatch.studio.delivery-pack.v1";
  ownership: {
    execution: "apatch";
    verification: "apatch";
    effort: "apatch.run_timesheet";
    acceptance: "studio_owner_decision";
    accepted_time: "separate_owner_decision";
  };
  change: {
    schema: "apatch.studio.delivery-change.v1";
    change_id: string;
    objective: string;
    status: string;
    result_kind: string;
    updated_at: string;
    spec_id: string | null;
    requirement_id: string | null;
    project: {
      name: string;
      repository: string | null;
      branch: string | null;
      head: string | null;
    };
    summary: {
      file_count: number;
      insertions: number;
      deletions: number;
      mutation_count: number;
      attestation_count: number;
      signed_event_count: number;
    };
  };
  scope: {
    containment: string;
    allowed: string[];
    forbidden: string[];
    violation_count: number;
  };
  basis_hash: string;
  recorded_files_hash?: string;
  test_protocol: DeliveryTestProtocol;
  proof: {
    status: string;
    contract_hash: string | null;
    envelope_hash: string | null;
    evidence_hash: string | null;
    adherence: string;
    mutation_count: number;
  };
  effort: {
    schema: "apatch.studio.effort-draft.v1";
    available: boolean;
    source: "apatch.run_timesheet";
    derivation: "signed_event_op_spacing" | "not_recorded";
    draft_hours: number | null;
    quality: string;
    accepted_time: false;
    reason: string | null;
    signed_event_count: number;
    verification: {
      ok: boolean;
      status: string;
      checked: number;
      signed_event_count: number;
      event_ids: string[];
      key_ids: string[];
      ledger_drift_count: number;
      unsigned_count: number;
    };
    method_note: string;
    disclaimer: string;
    effort_hash: string;
  };
  acceptance: { latest: AcceptanceAct | null; history_count: number; history?: AcceptanceAct[]; status?: "current" | "stale" | "not_recorded" };
  time_decision: { latest: AcceptedTimeDecision | null; history_count: number; history?: AcceptedTimeDecision[]; status?: "current" | "stale" | "not_recorded" };
  legacy_history?: { status: "unverified" | "not_recorded"; acceptance_count: number; time_decision_count: number };
  authority: DeliveryAuthority;
  document_hash: string;
}

export interface ImportedChangeDetailFile {
  path: string;
  mode: string | null;
  sha256: string | null;
  record_ids: string[];
  binary: boolean;
  patch: string | null;
  patch_status: "available" | "truncated" | "binary" | "not_recorded";
  patch_bytes: number;
  insertions: number;
  deletions: number;
  truncated: boolean;
}

export interface ImportedChangeDetail {
  schema: "apatch.studio.imported-change-detail.v1";
  privacy_band: "local_source";
  change_id: string;
  governed_session_id: string;
  result_kind: "code_change" | "verification_checkpoint";
  result_message: string;
  objective: string;
  status: "proven" | "recorded" | "rolled_back";
  created_at: string;
  updated_at: string;
  spec_id: string | null;
  requirement_id: string | null;
  project: {
    name: string;
    identity: string | null;
    repository: string | null;
    branch: string | null;
    upstream: string | null;
    head: string | null;
    operator: string;
  };
  actor: {
    type: "apatch_signing_identity";
    label: string;
    key_id: string | null;
  };
  summary: {
    file_count: number;
    omitted_file_count: number;
    insertions: number;
    deletions: number;
    mutation_count: number;
    attestation_count: number;
    signed_event_count: number;
    patch_bytes: number;
    patch_truncated: boolean;
  };
  files: ImportedChangeDetailFile[];
  events: Array<{
    record_id: string | null;
    at: string;
    tool: string;
    action: string | null;
    signer_key_id: string | null;
  }>;
  verification: {
    status: "proven" | "recorded";
    attestation_count: number;
    latest_record_id: string | null;
    latest_signer: string | null;
  };
  decision_basis: ProjectDecisionBasis | null;
  sdd: SddChangeProjection | SddUnavailableProjection;
  available_actions: Array<"back_to_changes" | "open_recorded_patch" | "open_backlog">;
}

export type ChangeFeedItem =
  | { kind: "studio_run"; id: string; occurred_at: string; run: AgentRun }
  | { kind: "imported_change"; id: string; occurred_at: string; change: ImportedChange };

export interface ProjectHomeSummary {
  schema: "apatch.studio.project-home.v1";
  project: { name: string; branch: string };
  state: {
    id: "working" | "attention" | "review" | "ready";
    label: "Working" | "Needs attention" | "Ready for review" | "Ready for a new change";
    tone: "info" | "danger" | "warning" | "success";
    detail: string;
    next_step: string;
  };
  summary: { proven: number; total: number; remaining: number; uncommitted_files: number };
  history_count: number;
  recent_ids: string[];
  recent_group_sizes: Record<string, number>;
}

export interface ChangeFeedPage {
  schema: "apatch.studio.change-feed.v1";
  count: number;
  items: ChangeFeedItem[];
  home: ProjectHomeSummary;
}

export type TimesheetDimension = "project" | "spec" | "day";

export interface TimesheetGroup { key: string[]; sessions: number; hours: number; active_sec: number; ops: number; files_touched: number; insertions: number; deletions: number; }
export interface TimesheetDraft { schema: "apatch.studio.timesheet-draft.v1"; request_id: string; source: "apatch.run_timesheet"; project: { id: string; name: string }; period: { since: string | null; until: string | null }; basis: "operation_spacing_estimate"; accepted_time: false; group_by: TimesheetDimension[]; groups: TimesheetGroup[]; warnings: string[]; disclaimer: string; }
export interface TimesheetVerification { schema: "apatch.studio.timesheet-verification.v1"; request_id: string; source: "apatch.run_timesheet"; project: { id: string; name: string }; period: { since: string | null; until: string | null }; ok: boolean; checked: number; drift_count: number; unsigned_count: number; signature_status: "complete" | "partial"; integrity_status: "matched" | "drifted"; accepted_time: false; summary: string; next_action: string; }
export type TimesheetResult = TimesheetDraft | TimesheetVerification;
export interface ContributionHealth {
  schema: string;
  timesheet_available: boolean;
  tracker_state: string;
  tracker_configured: boolean;
  tracker_auth_configured: boolean;
  contract_status: string;
  evidence_pending: number;
  contribution_pending: number;
  pending_total: number;
  last_acknowledgement: string | null;
}

export type DeliveryAction = "commit" | "push" | "open_pr";

export interface DeliveryStatus {
  schema: string;
  branch: string | null;
  detached: boolean;
  staged_count: number;
  unstaged_count: number;
  untracked_count: number;
  upstream_configured: boolean;
  ahead: number;
  behind: number;
  can_commit: boolean;
  can_push: boolean;
  can_open_pr: boolean;
  pr_provider: "github" | null;
}

export interface DeliveryReceipt {
  schema: string;
  request_id: string;
  request_hash: string;
  action: DeliveryAction;
  status: "complete";
  completed_at: string;
  result: Record<string, unknown>;
}

export interface LocalReviewHandoff {
  schema: string;
  request_id: string;
  run_id: string;
  status: "opened" | "empty";
  artifact_id: string | null;
  file_count: number;
  byte_count: number;
  launcher: string | null;
  expires_in_sec: number;
}

export type SpecInspectAction =
  | "lint"
  | "coverage"
  | "next"
  | "plan"
  | "interference"
  | "schedule"
  | "reality"
  | "status";

export interface SpecActionResult extends Record<string, unknown> {
  ok: boolean;
  spec_id?: string;
  action: string;
  counts?: Record<string, number>;
  next?: {
    id: string | null;
    title: string;
    state: string | null;
    content_hash: string | null;
  } | null;
  remaining_count?: number;
  rebound?: string[];
  preserved_stale?: string[];
}

export type SystemAction =
  | "doctor" | "hygiene" | "gc_preview" | "gc_execute" | "policy_verify";

export interface SystemActionResult extends Record<string, unknown> {
  ok: boolean;
  action: SystemAction;
  version?: string | null;
  profile?: string | null;
  tool_count?: number;
  writer_protocol?: number | string | null;
  concurrent_writers?: boolean;
  trust_mode?: string | null;
  enforcement?: boolean;
  hygiene?: { status: string; issue_count: number };
  counts?: Record<string, number>;
  action_required?: boolean;
  deleted_count?: number;
  reclaimed_bytes?: number;
  skipped_count?: number;
}

export type WorkspaceAction = "list" | "register" | "remove";

export interface WorkspaceAlias {
  alias: string;
  ready: boolean;
  drift_count: number;
  registered_at: string | null;
  error_type: string | null;
  recommended_action: string | null;
}

export interface WorkspaceActionResult extends Record<string, unknown> {
  ok: boolean;
  action: WorkspaceAction;
  count?: number;
  items?: WorkspaceAlias[];
  alias?: string;
  current_workspace?: boolean;
  ready?: boolean;
  removed?: boolean;
}

export type EvidenceAction =
  | "history" | "verify" | "coverage" | "inclusion" | "ratify" | "reality" | "export";

export interface EvidenceActionResult extends Record<string, unknown> {
  ok: boolean;
  action: EvidenceAction;
  artifact?: string | null;
  count?: number;
  checked?: number;
  verified?: number;
  covered_count?: number;
  uncovered_count?: number;
  violation_count?: number;
  bundle_hash?: string;
  verdict?: string;
  degraded?: boolean;
  skipped?: string | null;
  counts?: Record<string, number>;
  items?: EvidenceEvent[];
  records?: Array<{
    id: string | null;
    summary: string;
    kind: string | null;
    status: string | null;
  }>;
}

export interface ActionPresentation {
  title: string;
  summary: string;
  tone: "success" | "attention";
  facts: Array<{ label: string; value: string }>;
  next_action: string | null;
}

export interface ActionReceipt<T extends Record<string, unknown> = Record<string, unknown>> {
  schema: "apatch.studio.action-receipt.v1";
  action_id: string;
  request_id: string;
  request_hash: string;
  command: string;
  status: "complete" | "attention";
  completed_at: string;
  presentation: ActionPresentation;
  result: T;
}

export interface WorkspaceOverview {
  schema: string;
  generated_at: string;
  workspace: {
    name: string;
    identity: string;
    repository: string | null;
    branch: string;
    upstream: string | null;
    head: string | null;
    operator: string;
    dirty_files: number;
    clean: boolean;
  };
  product: {
    schema: "apatch.studio.product.v1";
    name: "APatch Studio";
    edition: "oss";
    features: {
      local_governed_runs: boolean;
      recovery: boolean;
      evidence: boolean;
      full_agent_api: boolean;
      execution_intents: boolean;
    };
  };
  execution_intents: {
    schema: "apatch.studio.execution-intent-summary.v1";
    available: boolean;
    configured: boolean;
    workspace_id: string | null;
    cowork_connected: boolean;
    pending: number;
    attention: number;
  };
  runtime: {
    apatch_version: string;
    mcp_profile: string;
    tool_count: number;
    trust_mode: string;
    enforcement: boolean;
    trust_anchor: string;
    writer_protocol: string;
    concurrent_writers: boolean;
    hygiene: string;
    hygiene_issues: Array<{ type: string; count: number }>;
    capability_contract: {
      schema: "apatch.studio.runtime-capability-contract.v1";
      runtime_owner: "apatch";
      studio_role: "fixed_purpose_facade";
      catalog: {
        version: string;
        profile: string;
        tool_count: number;
        discovery: "runtime";
        full_professional_api: boolean;
      };
      truth_domains: string[];
      families: Array<{
        id: string;
        runtime_owner: "apatch";
        studio_access: "fixed_purpose_or_allowlisted_runner";
        entrypoint_count: number;
      }>;
      invariants: {
        studio_reimplements_runtime: false;
        studio_reduces_agent_catalog: false;
        read_only_refresh_takes_writer_lease: false;
        path_scoped_concurrency: boolean;
      };
    };
    requirements: RuntimeRequirements;
    endpoint_identity: EndpointIdentity;
  };
  project_brief: ProjectBrief;
  plans: ProjectPlansPage;
  summary: {
    spec_count?: number;
    total_requirements?: number;
    attested?: number;
    stale_count?: number;
    percent_complete?: number;
    coverage_status?: "available" | "unavailable";
    coverage_error?: string | null;
  };
  session: {
    active: boolean;
    id: string | null;
    intent: string | null;
    lifecycle: string;
    phase: string;
    checkpoint: string | null;
    risk: string;
    next_action: string | null;
    started_at: string | null;
    ended_at: string | null;
    failure: { error_type?: string; error?: string } | null;
  };
  specifications: Specification[];
  evidence: EvidenceEvent[];
  work_assets: {
    count: number;
    lifecycle_counts: Record<string, number>;
    items: WorkAsset[];
  };
  degraded: string[];
}

export interface Specification {
  id: string;
  title: string;
  done: boolean;
  coverage_status?: "available" | "unavailable";
  coverage_error?: string | null;
  total: number;
  attested: number;
  pending: number;
  stale: number;
  blocked: number;
  percent: number;
  stale_ids: string[];
  pending_ids: string[];
}

export interface EvidenceEvent {
  id: string;
  role: string;
  tool: string;
  at: string | null;
  signed_by: string | null;
  intent: string | null;
  session_id: string | null;
}

export interface WorkAsset {
  id: string;
  title: string;
  kind: string;
  lifecycle: string;
  recallable: boolean;
  reuse_count: number;
  signals: string[];
  verification_count: number;
  last_used_at?: string | null;
  applicability?: {
    scope: string;
    required_context: string[];
  };
  spec_refs?: string[];
  rfp_refs?: string[];
  provenance?: {
    owner_key_id: string | null;
    trust_level: string | null;
    mutation_count: number;
    attestation_count: number;
    confidentiality_class: string | null;
    rights_claim: string;
  };
}

export type AssetAction = "show" | "recall" | "export";

export type PolicyAction = "status" | "preview" | "apply" | "sign" | "verify" | "restore";
export interface PolicyState {
  mode: string;
  governed_mode: string;
  watcher: string;
  lease_max_seconds: number;
  block_commit_without_proof: boolean;
}
export interface PolicyActionResult extends Record<string, unknown> {
  ok: boolean;
  action: PolicyAction;
  current?: PolicyState;
  proposed?: PolicyState;
  changes?: Array<{ field: string; before: string | number; after: string | number }>;
  signed?: boolean;
  signature_ok?: boolean;
  secure?: boolean;
  has_drift?: boolean;
  signer_key_id?: string | null;
  reason?: string | null;
  next_action?: string;
  remaining_restore_points?: number;
}

export interface AssetActionResult extends Record<string, unknown> {
  ok: boolean;
  action: string;
  query?: string;
  objective?: string;
  count?: number;
  items?: WorkAsset[];
  asset?: WorkAsset;
  asset_id?: string;
  recallable?: boolean;
  reason?: string | null;
  bundle_hash?: string | null;
  bounded?: boolean;
}
