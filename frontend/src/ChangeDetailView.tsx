import {
  AlertTriangle,
  ArrowLeft,
  BadgeCheck,
  BookOpen,
  Check,
  CircleX,
  Clock3,
  Download,
  ExternalLink,
  FileCheck2,
  FileCode2,
  FileText,
  LoaderCircle,
  Printer,
  RefreshCw,
  ShieldCheck,
  TestTubeDiagonal,
  Timer,
} from "lucide-react";
import { useEffect, useState } from "react";

import {
  loadChangeDetail,
  loadDeliveryPack,
  loadDocument,
  openChangeLocalReview,
  recordAcceptanceAct,
  recordTimeDecision,
} from "./api";
import { ChangeCard } from "./OutsideInViews";
import type { ConfirmRequest } from "./OutsideInViews";
import type {
  ChangeFeedItem,
  DeliveryAcceptanceDecision,
  DeliveryPack,
  ImportedChangeDetail,
  ProjectDecisionBasis,
  SddChangeProjection,
  WorkspaceOverview,
} from "./types";

const TECHNICAL_DELIVERY_AUDIT = "Technical delivery audit";

function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function short(value: string | null) {
  if (!value) return "Not recorded";
  return value.length > 28 ? value.slice(0, 14) + "..." + value.slice(-8) : value;
}

function deliveryDecisionLabel(value: DeliveryAcceptanceDecision | undefined) {
  if (value === "accepted") return "Accepted";
  if (value === "accepted_with_reservations") return "Accepted with reservations";
  if (value === "changes_requested") return "Changes requested";
  if (value === "rejected") return "Rejected";
  return "Awaiting decision";
}

function blockerLabel(value: string) {
  const labels: Record<string, string> = {
    frozen_verification_not_recorded: "The pre-agreed test contract was not retained.",
    no_tests_collected: "No tests were collected.",
    no_tests_executed: "No tests were executed.",
    all_tests_skipped: "Every collected test was skipped.",
    tests_failed: "At least one agreed test failed.",
    missing_perspectives: "Positive, negative, boundary and regression coverage is incomplete.",
    falsification_incomplete: "The checks were not shown to fail on a reversible defect.",
    apatch_gate_incomplete: "APatch did not accept the complete frozen verification gate.",
  };
  return labels[value] ?? value.replaceAll("_", " ");
}

function downloadDeliveryPack(pack: DeliveryPack) {
  const blob = new Blob([JSON.stringify(pack, null, 2) + "\n"], {
    type: "application/json;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = pack.change.change_id + "-delivery-record.json";
  link.click();
  URL.revokeObjectURL(url);
}

function humanTitle(value: string) {
  const withoutAnchor = value.replace(
    /^SPEC-[A-Z0-9-]+#(?:R|FR|NFR)[A-Z0-9-]*:\s*/i,
    "",
  ).trim();
  return withoutAnchor || "Verified project change";
}

function runnerLabel(value: "codex" | "claude") {
  return value === "codex" ? "Codex" : "Claude Code";
}

function WorkspaceContext({
  data,
  recordedBy,
  runner,
}: {
  data: WorkspaceOverview;
  recordedBy: string;
  runner?: string;
}) {
  return (
    <section className="oi-detail-context" aria-label="Project and actor context">
      <div><span>Project</span><strong>{data.workspace.repository ?? data.workspace.name}</strong></div>
      <div><span>Branch</span><strong>{data.workspace.branch}</strong></div>
      {runner ? <div><span>Studio runner</span><strong>{runner}</strong></div> : null}
      <div><span>Local operator</span><strong>{data.workspace.operator || "Local user"}</strong></div>
      <div><span>Recorded by</span><strong>{recordedBy}</strong></div>
    </section>
  );
}

function DecisionBasisSection({
  basis,
  onOpenDocument,
}: {
  basis: ProjectDecisionBasis | null;
  onOpenDocument: (documentId: string) => void;
}) {
  if (!basis) return null;
  return <section className="oi-decision-basis" aria-labelledby="decision-basis-title">
    <div className="oi-section-heading"><div><span>Decision basis</span><h2 id="decision-basis-title">Why this result is proven</h2><p>APatch checked the exact expected outcome and recorded proof for it.</p></div><ShieldCheck size={22} /></div>
    <div className="oi-decision-grid">
      <div><span>Required result</span><strong>{basis.requirement.title}</strong><p>{basis.requirement.statement}</p></div>
      <div><span>Expected outcome</span><strong>{basis.proposal?.title ?? "Executable project plan"}</strong><p>{basis.proposal?.criterion?.requirement ?? "No proposal criterion is linked to this requirement."}</p></div>
      <div><span>Verification</span><strong>{basis.verification.label}</strong><p>{basis.verification.explanation}</p></div>
    </div>
    <div className="oi-action-row">
      <button className="oi-button oi-button-secondary" type="button" onClick={() => onOpenDocument(basis.specification.id)}><FileText size={15} />View specification</button>
      {basis.proposal ? <button className="oi-button oi-button-secondary" type="button" onClick={() => onOpenDocument(basis.proposal!.id)}><BookOpen size={15} />View proposal</button> : null}
    </div>
    <details className="oi-technical-audit"><summary>Technical audit</summary><dl><div><dt>Requirement anchor</dt><dd>{basis.specification.id}#{basis.requirement.id}</dd></div><div><dt>Configured verification</dt><dd><code>{basis.technical.verification_command}</code></dd></div><div><dt>Requirement fingerprint</dt><dd>{basis.technical.content_hash}</dd></div>{basis.proposal?.criterion ? <div><dt>Acceptance ID</dt><dd>{basis.proposal.criterion.id}</dd></div> : null}</dl></details>
  </section>;
}


function ExecutionContractSection({ sdd }: { sdd: ImportedChangeDetail["sdd"] }) {
  if (!sdd.available) {
    return <section className="oi-sdd-section" aria-labelledby="execution-contract-title">
      <div className="oi-section-heading"><div><span>Execution contract</span><h2 id="execution-contract-title">Scope record unavailable</h2><p>{sdd.message}</p></div><AlertTriangle size={22} /></div>
    </section>;
  }
  const budgetLabels: Record<string, string> = {
    files: "Files",
    insertions: "Lines added",
    deletions: "Lines removed",
    seconds: "Time budget",
  };
  return <section className="oi-sdd-section" aria-labelledby="execution-contract-title">
    <div className="oi-section-heading"><div><span>Execution contract</span><h2 id="execution-contract-title">What the agent could do</h2><p>The exact boundaries were frozen before implementation and stayed attached to this change.</p></div><ShieldCheck size={22} /></div>
    <div className="oi-sdd-scope-grid">
      <div><h3><Check size={16} />What the agent was allowed to do</h3><ul>{sdd.scope.allowed.map((item) => <li key={item}>{item}</li>)}</ul></div>
      <div><h3><AlertTriangle size={16} />What the agent could not do</h3><ul>{sdd.scope.forbidden.map((item) => <li key={item}>{item}</li>)}</ul></div>
    </div>
    <div className="oi-sdd-budget" aria-label="Execution budgets">
      {Object.entries(sdd.scope.budgets).map(([key, value]) => <div key={key}><span>{budgetLabels[key] ?? key}</span><strong>{key === "seconds" ? Math.round(value / 60) + " min" : value}</strong></div>)}
    </div>
    <div className={"oi-sdd-containment " + (sdd.scope.violations.length ? "is-warning" : "is-clean")}>
      <ShieldCheck size={16} />
      <div><strong>{sdd.scope.violations.length ? "APatch blocked an out-of-scope attempt" : "No unresolved scope violation"}</strong><span>{sdd.scope.containment === "sealed" ? "All declared execution channels were contained." : "APatch-governed effects were checked; direct shell or network access outside APatch is not contained."}</span></div>
    </div>
    {sdd.scope.violations.length ? <ul className="oi-sdd-violations">{sdd.scope.violations.map((item, index) => <li key={item.effect + index}>{item.count} blocked attempt: {item.effect}</li>)}</ul> : null}
    <p className="oi-sdd-amendment">Contract change: {sdd.scope.amendment.status === "not_requested" ? "none requested" : sdd.scope.amendment.status.replaceAll("_", " ")}</p>
  </section>;
}

function TestProtocolPanel({ pack }: { pack: DeliveryPack }) {
  const protocol = pack.test_protocol;
  const falsified = protocol.falsification.observed_red && protocol.falsification.restored_green;
  return <section className="oi-delivery-step" aria-labelledby="delivery-tests-title">
    <div className="oi-delivery-step-heading">
      <span className={"oi-step-icon " + (protocol.meaningful ? "is-complete" : "is-warning")}><TestTubeDiagonal size={17} /></span>
      <div><span>Tests</span><h3 id="delivery-tests-title">How this was checked</h3><p>{protocol.meaningful ? "The agreed checks passed from the retained APatch record." : "Test evidence is incomplete; this result cannot be accepted without reservations."}</p></div>
      <span className={"oi-badge tone-" + (protocol.meaningful ? "success" : "warning")}>{protocol.meaningful ? "Passed" : "Needs review"}</span>
    </div>
    <div className="oi-delivery-metrics" aria-label="Test results">
      <div><span>Passed</span><strong>{protocol.counts.passed}</strong></div>
      <div><span>Failed</span><strong>{protocol.counts.failed}</strong></div>
      <div><span>Skipped</span><strong>{protocol.counts.skipped}</strong></div>
      <div><span>Coverage views</span><strong>{protocol.perspectives.length}/4</strong></div>
    </div>
    {protocol.checks.length ? <div className="oi-delivery-checks">
      <div className="oi-delivery-subheading"><strong>Checks agreed before implementation</strong><span>{protocol.checks.length} retained</span></div>
      {protocol.checks.map((check, index) => <article key={(check.acceptance_id ?? "check") + index}>
        <Check size={15} />
        <div><strong>{check.oracle || "Recorded acceptance check"}</strong><span>{check.perspectives.join(" · ") || "Coverage view not recorded"}</span></div>
      </article>)}
    </div> : <div className="oi-alert is-warning"><AlertTriangle size={15} /><span>Individual check descriptions were not retained.</span></div>}
    <div className={"oi-sdd-falsification " + (falsified ? "is-clean" : "is-warning")}>
      {falsified ? <Check size={16} /> : <AlertTriangle size={16} />}
      <div><strong>{falsified ? "The checks caught a known defect" : "Defect-detection proof is missing"}</strong><span>{falsified ? "A reversible defect produced red, and the restored implementation returned to green." : "A green command alone is not treated as proof that the checks can detect failure."}</span></div>
    </div>
    {protocol.blockers.length ? <ul className="oi-delivery-blockers">{protocol.blockers.map((item) => <li key={item}>{blockerLabel(item)}</li>)}</ul> : null}
  </section>;
}

function VerificationSection(props: Parameters<typeof TestProtocolPanel>[0]) {
  return <TestProtocolPanel {...props} />;
}

function AcceptanceActPanel({
  pack,
  note,
  busy,
  onNote,
  onDecision,
}: {
  pack: DeliveryPack;
  note: string;
  busy: boolean;
  onNote: (value: string) => void;
  onDecision: (decision: DeliveryAcceptanceDecision) => void;
}) {
  const latest = pack.acceptance.latest;
  const noteReady = note.trim().length >= 3;
  return <section className="oi-delivery-step" aria-labelledby="delivery-acceptance-title">
    <div className="oi-delivery-step-heading">
      <span className={"oi-step-icon " + (latest?.decision === "accepted" ? "is-complete" : "")}><FileCheck2 size={17} /></span>
      <div><span>Result acceptance</span><h3 id="delivery-acceptance-title">{deliveryDecisionLabel(latest?.decision)}</h3><p>{latest ? `${latest.authority.label} recorded revision ${latest.revision} on ${formatDate(latest.recorded_at)}.` : "A human decision is recorded separately from the technical result."}</p></div>
      <span className={"oi-badge tone-" + (latest?.decision === "accepted" ? "success" : latest ? "warning" : "neutral")}>{latest ? "Recorded" : "Not decided"}</span>
    </div>
    {pack.acceptance.status === "stale" ? <p className="oi-alert" role="status">The result changed. Earlier signed decisions remain in history and do not accept this current result.</p> : null}
    {latest?.note ? <blockquote className="oi-delivery-note">{latest.note}</blockquote> : null}
    <label className="oi-delivery-field"><span>Decision note</span><textarea value={note} maxLength={1000} placeholder="What was accepted or what must change?" onChange={(event) => onNote(event.target.value)} /></label>
    <div className="oi-action-row">
      <button className="oi-button oi-button-primary" type="button" disabled={busy || !pack.test_protocol.meaningful} onClick={() => onDecision("accepted")}><BadgeCheck size={15} />Accept result</button>
      <button className="oi-button oi-button-secondary" type="button" disabled={busy || !noteReady} onClick={() => onDecision("accepted_with_reservations")}><AlertTriangle size={15} />Accept with reservations</button>
      <button className="oi-button oi-button-danger" type="button" disabled={busy || !noteReady} onClick={() => onDecision("changes_requested")}><CircleX size={15} />Request changes</button>
    </div>
  </section>;
}

function effortIssueLabel(effort: DeliveryPack["effort"]) {
  const labels: Record<string, string> = {
    signed_event_missing: "This change has no signed APatch contribution event.",
    signed_event_ambiguous: "More than one event claims this exact session.",
    signed_event_untrusted: "The event identity is not attested.",
    signed_event_unsigned: "The contribution event is not signed.",
    signed_event_identity_invalid: "The contribution event identity is invalid.",
    signed_event_key_unavailable: "The signing public key was not recorded.",
    signed_event_key_invalid: "The recorded signing public key is invalid.",
    signed_event_key_mismatch: "The signing key does not match its recorded identity.",
    signed_event_signature_invalid: "The contribution event signature is invalid.",
    signed_event_ledger_drift: "The event volume no longer matches the signed APatch ledger.",
    signed_event_hours_invalid: "The derived effort value is invalid.",
    signed_event_verification_unavailable: "APatch could not verify this effort draft.",
    signed_event_not_verified: "A verified exact-session effort draft was not recorded.",
  };
  return labels[effort.reason ?? ""] ?? "A verified exact-session effort draft is unavailable.";
}

function TimeDecisionPanel({
  pack,
  hours,
  note,
  busy,
  onHours,
  onNote,
  onDecision,
}: {
  pack: DeliveryPack;
  hours: string;
  note: string;
  busy: boolean;
  onHours: (value: string) => void;
  onNote: (value: string) => void;
  onDecision: (decision: "accepted" | "rejected") => void;
}) {
  const effort = pack.effort;
  const verification = effort.verification ?? {
    ok: false,
    status: "not_recorded",
    checked: 0,
    signed_event_count: 0,
    event_ids: [],
    key_ids: [],
    ledger_drift_count: 0,
    unsigned_count: 0,
  };
  const effortAvailable = effort.available && verification.ok && verification.status === "verified";
  const latest = pack.time_decision.latest;
  const numericHours = Number(hours);
  const canAccept = effortAvailable && Number.isFinite(numericHours) && numericHours >= 0 && numericHours <= Number(effort.draft_hours);
  const issue = effortAvailable ? null : effortIssueLabel(effort);
  return <section className="oi-delivery-step" aria-labelledby="delivery-time-title">
    <div className="oi-delivery-step-heading">
      <span className={"oi-step-icon " + (latest?.decision === "accepted" ? "is-complete" : effortAvailable ? "" : "is-warning")}><Timer size={17} /></span>
      <div>
        <span>Time report</span>
        <h3 id="delivery-time-title">{effortAvailable ? `${Number(effort.draft_hours).toLocaleString(undefined, { maximumFractionDigits: 2 })} h draft` : "Time draft unavailable"}</h3>
        <p>{latest ? `${latest.accepted_hours ?? 0} h ${latest.decision} by ${latest.authority.label}.` : issue ?? effort.method_note}</p>
        <small className="oi-delivery-estimate-note">{effortAvailable ? `Verified from ${effort.signed_event_count} exact-session signed event · Estimated governed effort, not accepted time` : "Estimated governed effort is unavailable until the exact session event verifies."}</small>
      </div>
      <span className={"oi-badge tone-" + (latest?.decision === "accepted" ? "success" : latest ? "warning" : effortAvailable ? "neutral" : "warning")}>{latest ? "Decided" : effortAvailable ? "Draft only" : "Not verified"}</span>
    </div>
    {pack.time_decision.status === "stale" ? <p className="oi-alert" role="status">The result or time draft changed. Earlier reviewed hours remain in history and are not accepted for this draft.</p> : null}
    <div className="oi-time-decision-form">
      <label className="oi-delivery-field"><span>Hours to accept</span><input type="number" min="0" max={effort.draft_hours ?? undefined} step="0.01" value={hours} disabled={!effortAvailable} onChange={(event) => onHours(event.target.value)} /></label>
      <label className="oi-delivery-field"><span>Time note</span><input value={note} maxLength={1000} placeholder="Optional review note" onChange={(event) => onNote(event.target.value)} /></label>
    </div>
    <p className="oi-delivery-disclaimer">{effort.disclaimer}</p>
    <div className="oi-action-row">
      <button className="oi-button oi-button-primary" type="button" disabled={busy || !canAccept} onClick={() => onDecision("accepted")}><Check size={15} />Accept time</button>
      <button className="oi-button oi-button-secondary" type="button" disabled={busy || !effortAvailable} onClick={() => onDecision("rejected")}><CircleX size={15} />Reject time</button>
    </div>
    <details className="oi-technical-audit">
      <summary>Time verification</summary>
      <dl>
        <div><dt>Status</dt><dd>{verification.status}</dd></div>
        <div><dt>Exact events checked</dt><dd>{verification.checked}</dd></div>
        <div><dt>Valid signatures</dt><dd>{verification.signed_event_count}</dd></div>
        <div><dt>Ledger drift</dt><dd>{verification.ledger_drift_count}</dd></div>
      </dl>
    </details>
  </section>;
}

function EffortSection(props: Parameters<typeof TimeDecisionPanel>[0]) {
  return <TimeDecisionPanel {...props} />;
}

function DeliveryRecordPanel({ pack }: { pack: DeliveryPack }) {
  return <section className="oi-delivery-step oi-delivery-record" aria-labelledby="delivery-record-title">
    <div className="oi-delivery-step-heading">
      <span className="oi-step-icon"><ShieldCheck size={17} /></span>
      <div><span>Delivery record</span><h3 id="delivery-record-title">Signed local record</h3><p>{pack.authority.label} · {pack.authority.trust === "organization-authority" ? "Organization authority" : "Local owner key"}</p></div>
      <span className="oi-badge tone-info">{pack.acceptance.history_count + pack.time_decision.history_count} decisions</span>
    </div>
    <div className="oi-delivery-summary">
      <div><span>Technical result</span><strong>{pack.test_protocol.meaningful ? "Passed" : "Incomplete"}</strong></div>
      <div><span>Result decision</span><strong>{deliveryDecisionLabel(pack.acceptance.latest?.decision)}</strong></div>
      <div><span>Accepted time</span><strong>{pack.time_decision.latest?.decision === "accepted" ? `${pack.time_decision.latest.accepted_hours} h` : "Not accepted"}</strong></div>
    </div>
    <div className="oi-action-row oi-print-actions">
      <button className="oi-button oi-button-secondary" type="button" onClick={() => downloadDeliveryPack(pack)}><Download size={15} />Download record</button>
      <button className="oi-button oi-button-secondary" type="button" onClick={() => window.print()}><Printer size={15} />Print act</button>
    </div>
    <details className="oi-technical-audit">
      <summary>{TECHNICAL_DELIVERY_AUDIT}</summary>
      <dl>
        <div><dt>Delivery document</dt><dd>{pack.document_hash}</dd></div>
        <div><dt>Exact acceptance basis</dt><dd>{pack.basis_hash}</dd></div>
        <div><dt>Frozen test protocol</dt><dd>{pack.test_protocol.protocol_hash}</dd></div>
        <div><dt>Frozen contract</dt><dd>{pack.test_protocol.contract_hash ?? "Not recorded"}</dd></div>
        <div><dt>Evidence record</dt><dd>{pack.test_protocol.evidence_hash ?? "Not recorded"}</dd></div>
        <div><dt>Authority key</dt><dd>{pack.authority.key_id}</dd></div>
        {pack.acceptance.latest ? <div><dt>Acceptance act</dt><dd>{pack.acceptance.latest.act_id} · signature {short(pack.acceptance.latest.signature.value)}</dd></div> : null}
        {pack.time_decision.latest ? <div><dt>Time decision</dt><dd>{pack.time_decision.latest.decision_id} · signature {short(pack.time_decision.latest.signature.value)}</dd></div> : null}
      </dl>
    </details>
  </section>;
}

function DeliveryPackSection({
  changeId,
  onChanged,
  requestConfirm,
}: {
  changeId: string;
  onChanged: () => Promise<void>;
  requestConfirm: (request: ConfirmRequest) => void;
}) {
  const [pack, setPack] = useState<DeliveryPack | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [acceptanceNote, setAcceptanceNote] = useState("");
  const [timeNote, setTimeNote] = useState("");
  const [hours, setHours] = useState("");

  async function refresh() {
    try {
      const current = await loadDeliveryPack(changeId);
      setPack(current);
      setError(null);
      if (!hours && current.effort.draft_hours !== null) setHours(String(current.effort.draft_hours));
    } catch (reason) {
      setPack(null);
      setError(reason instanceof Error ? reason.message : "The delivery record could not be verified.");
      throw reason;
    }
  }

  useEffect(() => {
    let active = true;
    setLoading(true);
    setPack(null);
    setError(null);
    void loadDeliveryPack(changeId)
      .then((current) => {
        if (!active) return;
        setPack(current);
        if (current.effort.draft_hours !== null) setHours(String(current.effort.draft_hours));
      })
      .catch((reason) => { if (active) setError(reason instanceof Error ? reason.message : "The delivery record could not be loaded."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [changeId]);

  function decideResult(decision: DeliveryAcceptanceDecision) {
    if (!pack) return;
    const labels: Record<DeliveryAcceptanceDecision, string> = {
      accepted: "Accept this exact result?",
      accepted_with_reservations: "Accept this result with reservations?",
      changes_requested: "Request changes to this result?",
      rejected: "Reject this result?",
    };
    requestConfirm({
      title: labels[decision],
      message: "The decision will be signed against the current files, tests and proof. A later change creates a new basis and does not rewrite this act.",
      confirmLabel: decision === "accepted" ? "Accept result" : decision === "changes_requested" ? "Request changes" : "Record decision",
      tone: decision === "changes_requested" || decision === "rejected" ? "danger" : "default",
      action: async () => {
        setBusy(true);
        setError(null);
        try {
          await recordAcceptanceAct(changeId, pack, decision, acceptanceNote);
          setAcceptanceNote("");
          setMessage("Result decision signed and recorded.");
          await refresh();
          await onChanged();
        } catch (reason) {
          setError(reason instanceof Error ? reason.message : "The result decision could not be recorded.");
        } finally {
          setBusy(false);
        }
      },
    });
  }

  function decideTime(decision: "accepted" | "rejected") {
    if (!pack) return;
    const acceptedHours = decision === "accepted" ? Number(hours) : null;
    requestConfirm({
      title: decision === "accepted" ? "Accept the reviewed hours?" : "Reject this time draft?",
      message: decision === "accepted" ? `Record ${acceptedHours} h as the separate accepted-time decision for this change.` : "The APatch draft remains in the audit, but it will not become accepted time.",
      confirmLabel: decision === "accepted" ? "Accept time" : "Reject time",
      tone: decision === "rejected" ? "danger" : "default",
      action: async () => {
        setBusy(true);
        setError(null);
        try {
          await recordTimeDecision(changeId, pack, decision, acceptedHours, timeNote);
          setTimeNote("");
          setMessage("Time decision signed and recorded separately.");
          await refresh();
          await onChanged();
        } catch (reason) {
          setError(reason instanceof Error ? reason.message : "The time decision could not be recorded.");
        } finally {
          setBusy(false);
        }
      },
    });
  }

  if (loading) return <section className="oi-delivery-pack"><div className="oi-loading-inline"><LoaderCircle className="spin" size={18} />Preparing the delivery record...</div></section>;
  if (!pack) return <section className="oi-delivery-pack"><div className="oi-alert is-error" role="alert"><AlertTriangle size={15} /><span>{error ?? "The delivery record is unavailable."}</span></div></section>;

  return <section className="oi-delivery-pack" aria-labelledby="delivery-pack-title">
    <header className="oi-delivery-header">
      <div><span>Delivery pack</span><h2 id="delivery-pack-title">Tested, decided and recorded</h2><p>Technical proof, human acceptance and reviewed time remain separate and traceable.</p></div>
      <button className="oi-button oi-button-secondary" type="button" disabled={busy} onClick={() => void refresh().catch(() => undefined)} aria-label="Refresh delivery record"><RefreshCw size={15} />Refresh</button>
    </header>
    {pack.legacy_history?.status === "unverified" ? <div className="oi-alert" role="status"><AlertTriangle size={15} /><span>Legacy delivery records are unverified. Original project files are preserved; review this result and record a new decision. No earlier acceptance or hours were imported.</span></div> : null}
    <VerificationSection pack={pack} />
    <AcceptanceActPanel pack={pack} note={acceptanceNote} busy={busy} onNote={setAcceptanceNote} onDecision={decideResult} />
    <EffortSection pack={pack} hours={hours} note={timeNote} busy={busy} onHours={setHours} onNote={setTimeNote} onDecision={decideTime} />
    <DeliveryRecordPanel pack={pack} />
    {message ? <div className="oi-alert is-good"><Check size={15} /><span>{message}</span></div> : null}
    {error ? <div className="oi-alert is-error" role="alert"><AlertTriangle size={15} /><span>{error}</span></div> : null}
  </section>;
}

function CausalReplaySection({ sdd }: { sdd: SddChangeProjection }) {
  return <section className="oi-sdd-section" aria-labelledby="causal-replay-title">
    <div className="oi-section-heading"><div><span>Decision trail</span><h2 id="causal-replay-title">Why this change happened</h2><p>The request, approval, execution, checks and final record remain connected.</p></div></div>
    <ol className="oi-sdd-replay">{sdd.timeline.map((item, index) => <li key={item.kind + index}><span>{index + 1}</span><div><strong>{item.label}</strong><p>{item.reason}</p><small>{item.at ? formatDate(item.at) : "Recorded sequence"}</small></div></li>)}</ol>
  </section>;
}

export function ChangeDetailView({
  resourceId,
  item,
  data,
  onBack,
  onOpenRun,
  onOpenDocument,
  onChanged,
  requestConfirm,
}: {
  resourceId: string;
  item: ChangeFeedItem | undefined;
  data: WorkspaceOverview;
  onBack: () => void;
  onOpenRun: (runId: string) => void;
  onOpenDocument: (documentId: string) => void;
  onChanged: () => Promise<void>;
  requestConfirm: (request: ConfirmRequest) => void;
}) {
  const imported = item?.kind === "imported_change" || resourceId.startsWith("apchg_");
  const [detail, setDetail] = useState<ImportedChangeDetail | null>(null);
  const [runBasis, setRunBasis] = useState<ProjectDecisionBasis | null>(null);
  const [loading, setLoading] = useState(imported);
  const [acting, setActing] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    if (!imported) {
      setLoading(false);
      return () => { active = false; };
    }
    setLoading(true);
    setError(null);
    void loadChangeDetail(resourceId)
      .then((value) => {
        if (active) setDetail(value);
      })
      .catch((reason) => {
        if (active) setError(reason instanceof Error ? reason.message : "The change could not be opened.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, [imported, resourceId]);

  useEffect(() => {
    let active = true;
    const run = item?.kind === "studio_run" ? item.run : null;
    const specId = run?.work_ref.spec_id;
    const requirementId = run?.work_ref.requirement_id;
    if (!specId || !requirementId) {
      setRunBasis(null);
      return () => { active = false; };
    }
    void loadDocument(specId).then((document) => {
      const requirement = document.requirements?.find((candidate) => candidate.id === requirementId);
      if (!active || !requirement) return;
      setRunBasis({
        schema: "apatch.studio.decision-basis.v1",
        specification: { id: document.id, title: document.title },
        requirement: {
          id: requirement.id,
          title: requirement.title,
          statement: requirement.statement,
          state: requirement.state,
          state_label: requirement.state_label,
        },
        proposal: document.proposal_id ? {
          id: document.proposal_id,
          title: null,
          criterion: requirement.acceptance,
        } : null,
        verification: requirement.verification,
        technical: requirement.technical,
      });
    }).catch(() => { if (active) setRunBasis(null); });
    return () => { active = false; };
  }, [item]);

  async function openPatch() {
    try {
      setActing(true);
      setError(null);
      const handoff = await openChangeLocalReview(resourceId);
      setMessage(handoff.status === "opened" ? "Recorded patch opened locally." : "No recorded patch is available.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The recorded patch could not open.");
    } finally {
      setActing(false);
    }
  }

  const back = (
    <button className="oi-button oi-button-secondary oi-detail-back" type="button" onClick={onBack}>
      <ArrowLeft size={15} />All changes
    </button>
  );

  if (!imported) {
    const run = item?.kind === "studio_run" ? item.run : null;
    if (!run) {
      return <div className="oi-page oi-detail-page">{back}<div className="oi-empty"><AlertTriangle size={28} /><strong>Change not found</strong><span>This local run is no longer in the Studio journal.</span></div></div>;
    }
    return (
      <div className="oi-page oi-detail-page">
        {back}
        <header className="oi-change-hero">
          <div>
            <span>Change</span>
            <h1>{run.objective}</h1>
            <p>{formatDate(run.started_at ?? run.created_at)} · {run.message}</p>
          </div>
          <span className={"oi-badge tone-" + (run.status === "succeeded" ? "success" : run.can_retry ? "danger" : "info")}>
            {run.status === "succeeded" ? "Ready for review" : run.can_retry ? "Needs attention" : "In progress"}
          </span>
        </header>
        <WorkspaceContext
          data={data}
          runner={runnerLabel(run.runner)}
          recordedBy={run.work_ref.governed_session_id ? "APatch governed session" : "Studio run journal"}
        />
        <DecisionBasisSection basis={runBasis} onOpenDocument={onOpenDocument} />
        <ChangeCard
          run={run}
          expanded
          standalone
          onToggle={() => undefined}
          onOpenRun={onOpenRun}
          onOpenDocument={onOpenDocument}
          onChanged={onChanged}
          requestConfirm={requestConfirm}
        />
      </div>
    );
  }

  if (loading) {
    return <div className="oi-page oi-detail-page">{back}<div className="oi-loading-inline"><LoaderCircle className="spin" size={20} />Opening recorded change...</div></div>;
  }

  if (!detail) {
    return <div className="oi-page oi-detail-page">{back}<div className="oi-empty"><AlertTriangle size={28} /><strong>Change unavailable</strong><span>{error ?? "The signed record could not be found."}</span></div></div>;
  }

  const checkpoint = detail.result_kind === "verification_checkpoint";
  const proven = detail.status === "proven";
  const canOpenPatch = detail.available_actions.includes("open_recorded_patch");
  const hasFrozenContract = detail.sdd?.available === true;

  return (
    <div className="oi-page oi-detail-page">
      {back}
      <header className="oi-change-hero">
        <div>
          <span>{checkpoint ? "Verification checkpoint" : "Change"}</span>
          <h1>{humanTitle(detail.objective)}</h1>
          <p>{formatDate(detail.updated_at)} · {detail.result_message}</p>
        </div>
        <span className={"oi-badge tone-" + (proven ? "success" : "neutral")}>
          {proven ? <Check size={14} /> : <Clock3 size={14} />}{proven ? "Proven" : "Recorded"}
        </span>
      </header>

      <WorkspaceContext
        data={data}
        recordedBy={detail.actor.label}
      />

      <DecisionBasisSection basis={detail.decision_basis} onOpenDocument={onOpenDocument} />
      <ExecutionContractSection sdd={detail.sdd} />

      <div className="oi-action-row oi-detail-actions">
        {canOpenPatch ? (
          <button className="oi-button oi-button-primary" type="button" disabled={acting} onClick={() => void openPatch()}>
            {acting ? <LoaderCircle className="spin" size={15} /> : <ExternalLink size={15} />}Open patch locally
          </button>
        ) : null}
        {detail.spec_id && !detail.decision_basis ? <button className="oi-button oi-button-secondary" type="button" onClick={() => onOpenDocument(detail.spec_id! + (detail.requirement_id ? "#" + detail.requirement_id : ""))}><FileText size={15} />View specification</button> : null}
      </div>

      {checkpoint ? (
        <section className="oi-zero-change">
          <ShieldCheck size={22} />
          <div><strong>No files were changed</strong><span>This record verifies existing project state. It is proof, not a code change.</span></div>
        </section>
      ) : (
        <section className="oi-recorded-files">
          <div className="oi-section-heading">
            <div><h2>Changed files</h2><p>{detail.summary.file_count} recorded · +{detail.summary.insertions} / -{detail.summary.deletions}</p></div>
          </div>
          <div className="oi-file-list">
            {detail.files.map((file, index) => (
              <details className="oi-file-result" key={file.path} open={index === 0}>
                <summary>
                  <span><FileCode2 size={16} /><strong>{file.path}</strong></span>
                  <small>+{file.insertions} / -{file.deletions}{file.mode ? " · mode " + file.mode : ""}</small>
                </summary>
                {file.patch ? <pre className="oi-diff">{file.patch}</pre> : <div className="oi-patch-unavailable">Patch content was not retained for this file.</div>}
                <footer><span>{file.patch_status === "truncated" ? "Preview truncated" : file.patch_status.replace("_", " ")}</span><span>{short(file.sha256)}</span></footer>
              </details>
            ))}
          </div>
        </section>
      )}

      <DeliveryPackSection changeId={resourceId} onChanged={onChanged} requestConfirm={requestConfirm} />
      {hasFrozenContract && detail.sdd.available ? <CausalReplaySection sdd={detail.sdd} /> : null}

      {message ? <div className="oi-alert is-good">{message}</div> : null}
      {error ? <div className="oi-alert is-error" role="alert"><AlertTriangle size={15} />{error}</div> : null}

      <details className="oi-proof">
        <summary><ShieldCheck size={16} />Proof and technical details</summary>
        <div className="oi-proof-grid">
          <div><span>Technical anchor</span><strong>{detail.spec_id ? detail.spec_id + (detail.requirement_id ? "#" + detail.requirement_id : "") : "Change-level proof"}</strong></div>
          <div><span>Protected run</span><strong>{short(detail.governed_session_id)}</strong></div>
          <div><span>Signed records</span><strong>{detail.summary.signed_event_count}</strong></div>
          <div><span>Proof records</span><strong>{detail.summary.attestation_count}</strong></div>
          <div><span>Files omitted by safety limits</span><strong>{detail.summary.omitted_file_count}</strong></div>
          <div><span>Revision</span><strong>{short(detail.project.head)}</strong></div>
          <div><span>Signer key</span><strong>{short(detail.actor.key_id)}</strong></div>
          {detail.sdd.available ? <div><span>Frozen contract</span><strong>{short(detail.sdd.proof.contract_hash)}</strong></div> : null}
          {detail.sdd.available ? <div><span>Task envelope</span><strong>{short(detail.sdd.proof.envelope_hash)}</strong></div> : null}
          {detail.sdd.available ? <div><span>Plan adherence</span><strong>{detail.sdd.proof.adherence}</strong></div> : null}
          {detail.sdd.available ? <div><span>Evidence record</span><strong>{short(detail.sdd.proof.evidence_hash)}</strong></div> : null}
        </div>
      </details>
    </div>
  );
}
