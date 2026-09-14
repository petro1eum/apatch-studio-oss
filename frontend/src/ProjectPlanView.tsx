import {
  ArrowLeft,
  BookOpen,
  CheckCircle2,
  FileText,
  LoaderCircle,
  Play,
  RefreshCw,
  Search,
  ShieldCheck,
  TriangleAlert,
  Unlock,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  answerLockRelease,
  askToLiftLock,
  freezeExecutionContract,
  loadLockExchange,
  inspectSpec,
  loadDocument,
  loadExecutionContract,
  rebindSpec,
  startRun,
} from "./api";
import type {
  ProjectDocument,
  ProjectDocumentBlock,
  ProjectDocumentSection,
  ProjectRequirement,
  RunnerInfo,
  SddContractReview,
  SddLockView,
} from "./types";

function DocumentBlock({ block }: { block: ProjectDocumentBlock }) {
  if (block.type === "paragraph") return <p>{block.text}</p>;
  if (block.type === "quote") return <blockquote>{block.text}</blockquote>;
  if (block.type === "divider") return <hr />;
  if (block.type === "heading") {
    if (block.level <= 3) return <h3>{block.text}</h3>;
    return <h4>{block.text}</h4>;
  }
  if (block.type === "list") {
    const List = block.ordered ? "ol" : "ul";
    return <List>{block.items.map((item, index) => <li key={index}>{item}</li>)}</List>;
  }
  if (block.type === "table") {
    return <div className="oi-document-table-wrap"><table><thead><tr>{block.headers.map((header) => <th key={header}>{header}</th>)}</tr></thead><tbody>{block.rows.map((row, rowIndex) => <tr key={rowIndex}>{row.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}</tr>)}</tbody></table></div>;
  }
  return <pre className="oi-document-code"><code>{block.text}</code></pre>;
}

function DocumentSections({ sections }: { sections: ProjectDocumentSection[] }) {
  return <div className="oi-document-body">{sections.map((section, index) => <section className="oi-document-section" key={section.title + index}><h2>{section.title}</h2>{section.blocks.map((block, blockIndex) => <DocumentBlock block={block} key={blockIndex} />)}</section>)}</div>;
}

function stateTone(state: string) {
  if (state === "attested") return "success";
  if (state === "stale") return "warning";
  if (state === "blocked") return "danger";
  return "neutral";
}

function RequirementCard({
  requirement,
  specificationId,
  availableRunner,
  selected,
  onChanged,
}: {
  requirement: ProjectRequirement;
  specificationId: string;
  availableRunner: RunnerInfo | undefined;
  selected: boolean;
  onChanged: () => Promise<void>;
}) {
  const [acting, setActing] = useState(false);
  const [review, setReview] = useState<SddContractReview | null>(null);
  const [lock, setLock] = useState<SddLockView | null>(null);
  const [lockLoaded, setLockLoaded] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const contractStatus = review?.status ?? requirement.execution_contract.status;

  // The boundary is read with the requirement, not behind the contract review.
  // A workspace whose contract is gone is exactly the workspace whose lock most
  // needs reading, and that is the one case a review could never open.
  // A fresh review also refreshes session-specific agreement controls here.
  useEffect(() => {
    let live = true;
    setLockLoaded(false);
    loadLockExchange(specificationId, requirement.id)
      .then((next) => { if (live) { setLock(next); setLockLoaded(true); } })
      .catch(() => { if (live) { setLock(null); setLockLoaded(false); } });
    return () => { live = false; };
  }, [specificationId, requirement.id, review]);

  async function loadContractReview() {
    try {
      setActing(true);
      setError(null);
      setMessage(null);
      setReview(await loadExecutionContract(specificationId, requirement.id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The scope and tests could not be opened.");
    } finally {
      setActing(false);
    }
  }

  async function askForRelease() {
    try {
      setActing(true);
      setError(null);
      setLock(await askToLiftLock(specificationId, requirement.id, reason));
      setReason("");
      setMessage("Your request was recorded. The boundary holds until the other side answers.");
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "The request could not be recorded.");
    } finally {
      setActing(false);
    }
  }

  async function answerRelease(decision: "grant" | "refuse") {
    try {
      setActing(true);
      setError(null);
      setLock(await answerLockRelease(specificationId, requirement.id, decision, reason));
      setReason("");
      setMessage(decision === "grant" ? "You agreed to lift this boundary." : "You refused, and your reason was recorded.");
      await onChanged();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "The answer could not be recorded.");
    } finally {
      setActing(false);
    }
  }

  async function approveContract() {
    try {
      setActing(true);
      setError(null);
      setMessage(null);
      const snapshot = review?.approval_snapshot;
      if (!snapshot) throw new Error("Review the current scope and tests before confirming.");
      const frozen = await freezeExecutionContract(specificationId, requirement.id, { snapshot });
      setReview(frozen);
      setLock(await loadLockExchange(specificationId, requirement.id));
      setMessage("Scope and tests approved. The agent can now run only inside this contract.");
      await onChanged();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The scope and tests could not be approved.");
    } finally {
      setActing(false);
    }
  }

  async function act() {
    try {
      setActing(true);
      setError(null);
      setMessage(null);
      if (requirement.available_action === "run") {
        if (contractStatus !== "frozen") {
          throw new Error("Review and approve the exact scope and tests before this requirement can run.");
        }
        if (!lockLoaded) throw new Error("Wait until the recorded task authority is loaded.");
        if (!availableRunner) throw new Error("No local agent is available.");
        await startRun({
          mode: "requirement",
          runner: availableRunner.id,
          objective: requirement.statement,
          spec_id: specificationId,
          requirement_id: requirement.id,
        });
        setMessage("The approved requirement was sent to the local agent.");
      } else if (requirement.available_action === "recheck") {
        await rebindSpec(specificationId, [requirement.id], []);
        setMessage("The exact requirement was checked again.");
      } else {
        await inspectSpec(specificationId, "status");
        setMessage("The recorded proof status is current.");
      }
      await onChanged();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The action could not complete.");
    } finally {
      setActing(false);
    }
  }

  const waitingForPreparation =
    requirement.available_action === "run" && contractStatus === "not_prepared";
  const waitingForOwner =
    requirement.available_action === "run" && contractStatus === "ready_for_owner";
  const invalidContract =
    requirement.available_action === "run" && contractStatus === "invalid";
  const actionLabel = waitingForPreparation
    ? "Scope & tests not prepared"
    : waitingForOwner
      ? "Review scope & tests"
      : invalidContract
        ? "Contract needs attention"
        : requirement.available_action === "run"
          ? "Run requirement"
          : requirement.available_action === "recheck"
            ? "Re-check"
            : "Inspect proof";
  const ActionIcon = requirement.available_action === "run"
    ? Play
    : requirement.available_action === "recheck"
      ? RefreshCw
      : Search;

  return <details className="oi-requirement" open={selected}>
    <summary>
      <div><strong>{requirement.title}</strong><span>{requirement.statement}</span></div>
      <span className={"oi-badge tone-" + stateTone(requirement.state)}>{requirement.state_label}</span>
    </summary>
    <div className="oi-requirement-body">
      <div className="oi-decision-grid">
        <div><span>Expected outcome</span><p>{requirement.acceptance?.requirement ?? "This requirement has no mapped proposal criterion."}</p></div>
        <div><span>Why this status</span><p>{requirement.verification.explanation}</p></div>
        <div><span>Execution permission</span><p>{requirement.available_action === "run" ? (contractStatus === "frozen" ? "Scope and tests are approved. Source work may begin." : contractStatus === "ready_for_owner" ? "Source work is blocked until you approve the prepared scope and tests." : contractStatus === "invalid" ? "The prepared contract is invalid or changed. Source work remains blocked." : "The agent has not prepared an exact scope and independent tests yet.") : requirement.available_action === "recheck" ? "No new source work is authorized. The existing result only needs its recorded proof checked again." : "No new source work is authorized. This requirement is already proven and recorded."}</p></div>
      </div>

      {waitingForPreparation ? <div className="oi-alert is-warning"><TriangleAlert size={15} /><span><strong>Preparation required.</strong> The planning agent must define allowed changes, forbidden areas, budgets and meaningful tests before implementation can start.</span></div> : null}
      {contractStatus === "frozen" ? <div className="oi-alert is-good"><ShieldCheck size={15} /><span>Only the approved scope below may be changed; attempts outside it are blocked and recorded.</span></div> : null}

      <div className="oi-action-row">
        <button
          className="oi-button oi-button-primary"
          type="button"
          disabled={acting || waitingForPreparation || invalidContract || (requirement.available_action === "run" && contractStatus === "frozen" && (!lockLoaded || !availableRunner))}
          onClick={() => void (waitingForOwner ? loadContractReview() : act())}
        >
          {acting ? <LoaderCircle className="spin" size={15} /> : <ActionIcon size={15} />}
          {actionLabel}
        </button>
        {contractStatus === "frozen" && !review ? <button className="oi-button oi-button-secondary" type="button" disabled={acting} onClick={() => void loadContractReview()}><Search size={15} />Review approved scope</button> : null}
      </div>

      {review ? <section className="oi-contract-review" aria-label="Approved execution contract">
        <header><div><span>{review.status === "frozen" ? "Approved execution contract" : "Your approval is required"}</span><h3>{review.objective}</h3></div><span className={"oi-badge " + (review.status === "frozen" ? "tone-success" : "tone-warning")}>{review.status === "frozen" ? "Approved" : "Source blocked"}</span></header>
        <div className="oi-sdd-scope-grid">
          <div><h3><CheckCircle2 size={15} />Allowed</h3><ul>{[
            ...review.scope.allowed_reads.map((item) => "Read " + item),
            ...review.scope.allowed_writes.map((item) => "Change " + item),
            ...review.scope.allowed_symbols.map((item) => "Touch symbol " + item),
          ].map((item) => <li key={item}>{item}</li>)}</ul></div>
          <div><h3><TriangleAlert size={15} />Forbidden</h3><ul>{review.scope.forbidden_paths.map((item) => <li key={item}>{item}</li>)}</ul></div>
        </div>
        <div className="oi-sdd-budget">{Object.entries(review.budgets).map(([label, value]) => <div key={label}><span>{label.replaceAll("_", " ")}</span><strong>{value}</strong></div>)}</div>
        <div className="oi-contract-checks">
          <div className="oi-section-heading"><div><h3>How the result will be judged</h3><p>These checks were fixed before source implementation.</p></div></div>
          {review.checks.map((check) => <article key={check.acceptance_id + check.test_id}><div><strong>{check.oracle}</strong><span>{check.perspectives.join(" · ")}</span></div><span className={"oi-badge " + (check.observed_red && check.falsification_expected === "red" ? "tone-success" : "tone-warning")}>{check.observed_red ? "Red observed" : "Baseline missing"}</span></article>)}
        </div>
        {review.owner_confirmation_required ? <div className="oi-contract-decision"><div><strong>Approve this exact boundary?</strong><span>The tests, scope and limits become immutable for the implementation agent. Any amendment requires another explicit decision.</span></div><button className="oi-button oi-button-primary" type="button" disabled={acting} onClick={() => void approveContract()}>{acting ? <LoaderCircle className="spin" size={15} /> : <ShieldCheck size={15} />}Approve scope & tests</button></div> : <div className="oi-contract-decision is-approved"><div><strong>Approved by {review.owner_actor_id ?? "local owner"}</strong><span>{review.frozen_at ? "Frozen " + new Date(review.frozen_at).toLocaleString() : "The frozen contract is active."}</span></div></div>}
        <details className="oi-technical-audit"><summary>Contract fingerprints</summary><dl><div><dt>Contract</dt><dd>{review.contract_hash ?? "Pending owner approval"}</dd></div><div><dt>Task envelope</dt><dd>{review.envelope_hash ?? "Created on approval"}</dd></div><div><dt>Containment</dt><dd>{review.containment}</dd></div><div><dt>Rollback owner</dt><dd>{review.rollback_owner}</dd></div></dl></details>
      </section> : null}

      {lock && lock.state !== "unlocked" ? <section className="oi-contract-lock">
        <div className="oi-section-heading"><div><h3>{lock.headline}</h3>{lock.explanation ? <p>{lock.explanation}</p> : null}</div></div>
        <dl className="oi-lock-parties">
          {lock.agreed_by.map((party) => <div key={(party.role ?? "") + (party.name ?? "")}><dt>{party.role === "set_by" ? "Set the task" : party.role === "taken_by" ? "Took the task" : "Approved"}</dt><dd>{party.name}{party.is_person ? "" : " (this machine, not a person)"}{party.self_asserted ? <span className="oi-lock-self-asserted">Named by this machine. Nobody outside it vouched for the name.</span> : null}</dd></div>)}
          {lock.agreed_at ? <div><dt>Agreed</dt><dd>{new Date(lock.agreed_at).toLocaleString()}</dd></div> : null}
        </dl>
        <div className="oi-lock-action">
          {lock.state === "locked" ? <>
            <label htmlFor={"lock-reason-" + requirement.id}>Why should this boundary be lifted?</label>
            <textarea id={"lock-reason-" + requirement.id} disabled={acting} value={reason} onChange={(event) => setReason(event.target.value)} rows={2} placeholder="The tests and scope stop being the right ones because..." />
            <button className="oi-button oi-button-secondary" type="button" disabled={acting || reason.trim().length < 8} onClick={() => void askForRelease()}>{acting ? <LoaderCircle className="spin" size={15} /> : <Unlock size={15} />}Ask to lift this</button>
          </> : null}
          {lock.state === "awaiting_answer" ? <>
            <label htmlFor={"lock-answer-" + requirement.id}>Your answer, and why</label>
            <textarea id={"lock-answer-" + requirement.id} disabled={acting} value={reason} onChange={(event) => setReason(event.target.value)} rows={2} placeholder="Agreed, because... / Not yet, because..." />
            <div className="oi-action-row">
              <button className="oi-button oi-button-primary" type="button" disabled={acting || reason.trim().length < 8} onClick={() => void answerRelease("grant")}>{acting ? <LoaderCircle className="spin" size={15} /> : <Unlock size={15} />}Agree to lift it</button>
              <button className="oi-button oi-button-secondary" type="button" disabled={acting || reason.trim().length < 8} onClick={() => void answerRelease("refuse")}><TriangleAlert size={15} />Refuse, with reason</button>
            </div>
          </> : null}
        </div>
        {lock.exchanges.length ? <ol className="oi-lock-exchanges">
          {lock.exchanges.map((exchange, index) => <li key={index}>
            <div><strong>{exchange.asked_by} asked to lift this</strong><span>{exchange.reason}</span></div>
            {exchange.answer ? <div className={exchange.answer === "grant" ? "is-granted" : "is-refused"}><strong>{exchange.answered_by} {exchange.answer === "grant" ? "agreed" : "refused"}</strong><span>{exchange.answer_reason}</span></div> : <div className="is-waiting"><strong>Waiting for the other side</strong><span>The boundary still holds until they answer.</span></div>}
            {exchange.one_sided ? <span className="oi-lock-one-sided">Recorded as one-sided: this workspace has a single user, so nobody else consented.</span> : null}
          </li>)}
        </ol> : null}
      </section> : null}

      {message ? <div className="oi-alert is-good">{message}</div> : null}
      {error ? <div className="oi-alert is-error" role="alert"><TriangleAlert size={15} />{error}</div> : null}
      <details className="oi-technical-audit"><summary>Technical audit</summary><dl><div><dt>Requirement ID</dt><dd>{requirement.id}</dd></div><div><dt>Content fingerprint</dt><dd>{requirement.technical.content_hash}</dd></div><div><dt>Configured verification</dt><dd><code>{requirement.technical.verification_command}</code></dd></div>{requirement.acceptance ? <div><dt>Acceptance ID</dt><dd>{requirement.acceptance.id}</dd></div> : null}</dl></details>
    </div>
  </details>;
}



export function ProjectPlanView({
  resourceId,
  runners,
  onBack,
  onOpenDocument,
  onChanged,
}: {
  resourceId: string;
  runners: RunnerInfo[];
  onBack: () => void;
  onOpenDocument: (documentId: string) => void;
  onChanged: () => Promise<void>;
}) {
  const [documentId, selectedRequirementId] = resourceId.split("#", 2);
  const [document, setDocument] = useState<ProjectDocument | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const availableRunner = useMemo(() => runners.find((runner) => runner.available), [runners]);

  const refresh = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      setDocument(await loadDocument(documentId));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The plan could not be opened.");
    } finally {
      setLoading(false);
    }
  }, [documentId]);

  useEffect(() => { void refresh(); }, [refresh]);

  async function changed() {
    await onChanged();
    await refresh();
  }

  if (loading) return <div className="oi-page oi-plan-page"><button className="oi-button oi-button-secondary oi-detail-back" type="button" onClick={onBack}><ArrowLeft size={15} />All plans</button><div className="oi-loading-inline"><LoaderCircle className="spin" size={20} />Opening plan...</div></div>;
  if (!document) return <div className="oi-page oi-plan-page"><button className="oi-button oi-button-secondary oi-detail-back" type="button" onClick={onBack}><ArrowLeft size={15} />All plans</button><div className="oi-empty"><TriangleAlert size={28} /><strong>Plan unavailable</strong><span>{error ?? "This project document could not be opened."}</span></div></div>;

  const proposal = document.kind === "proposal";
  return <div className="oi-page oi-plan-page">
    <button className="oi-button oi-button-secondary oi-detail-back" type="button" onClick={onBack}><ArrowLeft size={15} />All plans</button>
    <header className="oi-plan-hero"><div><span>{proposal ? "Proposal" : document.kind === "specification" ? "Executable plan" : "Project guide"}</span><h1>{document.title}</h1><p>{document.summary}</p></div><span className="oi-badge tone-info">{document.status ?? "Project document"}</span></header>
    <div className="oi-action-row oi-plan-links">
      {document.proposal_id ? <button className="oi-button oi-button-secondary" type="button" onClick={() => onOpenDocument(document.proposal_id!)}><BookOpen size={15} />View proposal</button> : null}
      {(document.paired_spec_ids ?? []).map((specId) => <button className="oi-button oi-button-secondary" type="button" key={specId} onClick={() => onOpenDocument(specId)}><FileText size={15} />View specification</button>)}
    </div>

    {proposal && document.acceptance?.length ? <section className="oi-acceptance"><div className="oi-section-heading"><div><h2>What must become true</h2><p>These outcomes define whether the proposal is complete.</p></div></div><div className="oi-acceptance-list">{document.acceptance.map((criterion) => <div key={criterion.id}><CheckCircle2 size={17} /><span>{criterion.requirement}</span>{criterion.requirement_ids?.length && document.paired_spec_ids?.[0] ? <button type="button" onClick={() => onOpenDocument(document.paired_spec_ids![0] + "#" + criterion.requirement_ids![0])}>Open requirement</button> : null}</div>)}</div></section> : null}

    {document.kind === "specification" ? <section className="oi-requirements"><div className="oi-section-heading"><div><h2>Work to be done</h2><p>{document.requirements?.length ?? 0} explicit requirements with live APatch status.</p></div></div>{document.traceability?.status !== "complete" ? <div className="oi-alert is-warning"><TriangleAlert size={15} />Decision links are {document.traceability?.status ?? "missing"}; Studio will not guess them.</div> : null}<div className="oi-requirement-list">{(document.requirements ?? []).map((requirement) => <RequirementCard key={requirement.id} requirement={requirement} specificationId={document.id} availableRunner={availableRunner} selected={requirement.id === selectedRequirementId} onChanged={changed} />)}</div></section> : <DocumentSections sections={document.sections ?? []} />}

    <details className="oi-technical-audit oi-document-audit"><summary><ShieldCheck size={15} />Technical audit</summary><dl><div><dt>Document ID</dt><dd>{document.id}</dd></div><div><dt>Document fingerprint</dt><dd>{document.technical.document_hash}</dd></div><div><dt>Bounded content size</dt><dd>{document.technical.byte_count} bytes</dd></div></dl></details>
  </div>;
}
