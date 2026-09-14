import {
  AlertTriangle,
  ArrowRight,
  BookOpenCheck,
  Check,
  ChevronDown,
  CircleStop,
  Clock3,
  FileCode2,
  FileSearch,
  GitBranch,
  GitCommitHorizontal,
  GitPullRequest,
  History,
  LayoutDashboard,
  Library,
  LoaderCircle,
  Play,
  RefreshCw,
  Repeat2,
  RotateCcw,
  Search,
  Send,
  Settings2,
  ShieldCheck,
  Sparkles,
  UserRound,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  cancelRun,
  loadDeliveryStatus,
  openRunLocalReview,
  retryRun,
  runAssetAction,
  runDeliveryAction,
  runEvidenceAction,
  saveRunReviewNote,
  searchAssets,
  suggestAssets,
  startRun,
} from "./api";
import { ImportedChangeCard } from "./ImportedChangeCard";
import { TimeLibrary } from "./TimeLibrary";
import { ProofDetails } from "./ProofDetails";
import { backlogState, changeState, proofState, scopeState } from "./productLanguage";
import type {
  ActionReceipt,
  AgentRun,
  ChangeFeedItem,
  DeliveryAction,
  DeliveryStatus,
  EvidenceActionResult,
  ProjectHomeSummary,
  RunnerInfo,
  WorkAsset,
  WorkspaceOverview,
} from "./types";

export interface ConfirmRequest {
  title: string;
  message: string;
  confirmLabel: string;
  tone?: "default" | "danger";
  action: () => Promise<void>;
}

export function ActionResultView({
  receipt,
}: {
  receipt: ActionReceipt;
}) {
  const presentation = receipt.presentation;
  return <section className="oi-proof" role="status" aria-live="polite">
    <div className="oi-panel-heading">
      <div><span>{presentation.tone === "success" ? "Completed" : "Needs attention"}</span><strong>{presentation.title}</strong></div>
      {presentation.tone === "success" ? <Check size={18} /> : <AlertTriangle size={18} />}
    </div>
    <p>{presentation.summary}</p>
    {presentation.facts.length ? <div className="oi-proof-grid">{presentation.facts.map((fact) => <div key={fact.label}><span>{fact.label}</span><strong>{fact.value}</strong></div>)}</div> : null}
    {presentation.next_action ? <div className="oi-alert"><ArrowRight size={15} />{presentation.next_action}</div> : null}
    <details><summary>Technical details</summary><pre>{JSON.stringify(receipt.result, null, 2)}</pre></details>
  </section>;
}

function formatDate(value: string | null) {
  if (!value) return "Now";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatDuration(totalSeconds: number) {
  const bounded = Math.max(0, Math.floor(totalSeconds));
  const minutes = Math.floor(bounded / 60);
  const seconds = bounded % 60;
  return minutes ? minutes + "m " + seconds + "s" : seconds + "s";
}

function deltaLabel(run: AgentRun) {
  if (run.plan_handoff) return "0 source files changed";
  const delta = run.review?.delta;
  if (!delta) return "Change size pending";
  return [
    Math.max(0, delta.dirty_files) + " files",
    "+" + Math.max(0, delta.insertions),
    "−" + Math.max(0, delta.deletions),
  ].join(" · ");
}

function defaultCriterion(objective: string) {
  const compact = objective.trim().replace(/\s+/g, " ").slice(0, 420);
  return "The requested outcome is implemented and verified: " + compact;
}

export function HomeView({
  data,
  home,
  changes,
  runners,
  selectedRunId,
  onSelectRun,
  onOpenPlans,
  onOpenLibrary,
  onOpenAdmin,
  onOpenPlan,
  onChanged,
  requestConfirm,
}: {
  data: WorkspaceOverview;
  home: ProjectHomeSummary;
  changes: ChangeFeedItem[];
  runners: RunnerInfo[];
  selectedRunId: string | null;
  onSelectRun: (runId: string | null) => void;
  onOpenPlans: () => void;
  onOpenLibrary: () => void;
  onOpenAdmin: () => void;
  onOpenPlan: (documentId: string) => void;
  onChanged: () => Promise<void>;
  requestConfirm: (request: ConfirmRequest) => void;
}) {
  const availableRunners = runners.filter((runner) => runner.available);
  const [objective, setObjective] = useState("");
  const [runner, setRunner] = useState<"codex" | "claude">(
    (availableRunners[0]?.id ?? "codex") as "codex" | "claude",
  );
  const [criterion, setCriterion] = useState("");
  const [specId, setSpecId] = useState("");
  const [requirementId, setRequirementId] = useState("");
  const [acting, setActing] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showFullHistory, setShowFullHistory] = useState(false);

  const recentIds = useMemo(() => new Set(home.recent_ids), [home.recent_ids]);
  const specTitles = useMemo(
    () => new Map(data.specifications.map((item) => [item.id, item.title])),
    [data.specifications],
  );
  const recentChanges = useMemo(
    () => changes.filter((item) => recentIds.has(item.id)),
    [changes, recentIds],
  );
  const visibleChanges = showFullHistory ? changes : recentChanges;

  useEffect(() => {
    if (selectedRunId && !recentIds.has(selectedRunId)) setShowFullHistory(true);
  }, [recentIds, selectedRunId]);

  const selectedSpec = data.specifications.find((item) => item.id === specId);
  const requirements = selectedSpec
    ? [...selectedSpec.stale_ids, ...selectedSpec.pending_ids]
    : [];
  const exactRequirementSelected = Boolean(specId && requirementId);

  async function begin() {
    const clean = objective.trim();
    if (clean.length < 3) return;
    if (!availableRunners.some((item) => item.id === runner)) {
      setError("No local agent is available.");
      return;
    }
    try {
      setActing("start");
      setError(null);
      const run = await startRun({
        mode: exactRequirementSelected ? "requirement" : "new_change",
        runner,
        objective: clean,
        ...(exactRequirementSelected
          ? { spec_id: specId, requirement_id: requirementId }
          : { acceptance_criteria: [criterion.trim() || defaultCriterion(clean)] }),
      });
      setObjective("");
      setCriterion("");
      await onChanged();
      onSelectRun(run.run_id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The change could not start.");
    } finally {
      setActing(null);
    }
  }

  return (
    <div className="oi-page">
      <header className="oi-project-header">
        <div className="oi-command-identity">
          <span className="oi-command-glyph"><LayoutDashboard size={20} /></span>
          <div>
            <span>Local project</span>
            <h1>{home.project.name}</h1>
            <p className="oi-project-byline">
              <span>{data.workspace.repository ?? "Local repository"}</span>
              <span><GitBranch size={13} />{home.project.branch ? "Branch " + home.project.branch : "Detached revision"}</span>
              <span><UserRound size={13} />{data.workspace.operator || "Local user"}</span>
            </p>
          </div>
        </div>
        <div className="oi-command-side">
          <div className={"oi-project-state tone-" + home.state.tone}>
            <span className={"oi-dot tone-" + home.state.tone} />
            <strong>{home.state.label}</strong>
          </div>
          <small className="oi-project-state-detail">{home.state.detail}. {home.state.next_step}.</small>
          <button className="oi-button oi-button-secondary" type="button" onClick={onOpenPlans}><BookOpenCheck size={16} />View project plans</button>
        </div>
      </header>

      <section className="oi-project-summary" aria-label="Project status">
        <article className={"oi-cockpit-card " + (home.summary.total > 0 && home.summary.remaining === 0 ? "is-success" : "is-info")}>
          <header><span>Verified work</span><ShieldCheck size={16} /></header>
          <strong>{home.summary.proven} of {home.summary.total}</strong>
          <small>Planned outcomes confirmed by verification</small>
        </article>
        <article className={"oi-cockpit-card " + (home.summary.remaining > 0 ? "is-warning" : "is-success")}>
          <header><span>Left to verify</span><Clock3 size={16} /></header>
          <strong>{home.summary.remaining}</strong>
          <small>{home.summary.remaining > 0 ? "Outcomes still waiting for proof" : "Nothing is waiting"}</small>
        </article>
        <article className={"oi-cockpit-card " + (home.summary.uncommitted_files > 0 ? "is-warning" : "is-success")}>
          <header><span>Uncommitted files</span><FileCode2 size={16} /></header>
          <strong>{home.summary.uncommitted_files}</strong>
          <small>{home.summary.uncommitted_files > 0 ? "Local changes not delivered yet" : "Working tree is clean"}</small>
        </article>
        <article className={"oi-cockpit-card " + (data.runtime.hygiene === "clean" ? "is-success" : data.runtime.hygiene === "critical" ? "is-danger" : "is-warning")}>
          <header><span>Protection</span><ShieldCheck size={16} /></header>
          <strong>{data.runtime.enforcement ? "Enforced" : "Audit"}</strong>
          <small>APatch {data.runtime.apatch_version} · storage health {data.runtime.hygiene}</small>
        </article>
      </section>

      <section className="oi-project-brief" aria-labelledby="project-purpose-title">
        <div>
          <span>What this project does</span>
          <h2 id="project-purpose-title">{data.project_brief.title}</h2>
          <p>{data.project_brief.purpose}</p>
          {data.project_brief.highlights.length ? <ul>{data.project_brief.highlights.map((highlight) => <li key={highlight}>{highlight}</li>)}</ul> : null}
        </div>
      </section>

      <section className={"oi-composer " + (changes.length === 0 ? "is-first-run" : "")}>
        {changes.length === 0 ? <div className="oi-first-run-mark"><Sparkles size={18} /><span>Start your first change</span></div> : null}
        <label htmlFor="change-objective">What do you want to change?</label>
        <div className="oi-composer-row">
          <textarea
            id="change-objective"
            rows={2}
            value={objective}
            onChange={(event) => setObjective(event.target.value)}
            placeholder="Describe the result you want"
            autoFocus={changes.length === 0}
          />
          <button className="oi-button oi-button-primary oi-start-button" type="button" disabled={acting !== null || objective.trim().length < 3} onClick={() => void begin()}>
            {acting === "start" ? <LoaderCircle className="spin" size={18} /> : <Play size={18} />}
            {exactRequirementSelected ? "Run requirement" : "Prepare plan"}
          </button>
        </div>
        <p className="oi-disclaimer">{exactRequirementSelected ? "Run only the selected planned item through its frozen checks." : "Studio first prepares a reviewable plan and verification contract. Source work starts only after the owner freezes it."}</p>
        <details className="oi-refinements">
          <summary><ChevronDown size={14} />Options</summary>
          <div className="oi-refinement-grid">
            <label><span>Agent</span><select value={runner} onChange={(event) => setRunner(event.target.value as "codex" | "claude")}>{availableRunners.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
            <label><span>Planned work</span><select value={specId} onChange={(event) => { setSpecId(event.target.value); setRequirementId(""); }}><option value="">Create or use the right contract</option>{data.specifications.filter((item) => !item.done).map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>
            {selectedSpec ? <label><span>Exact item</span><select value={requirementId} onChange={(event) => setRequirementId(event.target.value)}><option value="">Let the agent choose safely</option>{requirements.map((item) => <option key={item} value={item}>{item}</option>)}</select></label> : null}
            <label className="oi-wide"><span>Success check</span><textarea rows={2} value={criterion} onChange={(event) => setCriterion(event.target.value)} placeholder={objective.trim() ? defaultCriterion(objective) : "Generated from the requested outcome"} /></label>
          </div>
        </details>
        {error ? <div className="oi-alert is-error" role="alert"><AlertTriangle size={16} />{error}</div> : null}
      </section>

      {changes.length ? (
        <section className="oi-home-results" aria-label="Project results">
          <div className="oi-section-heading">
            <div>
              <h2>{showFullHistory ? "Full history" : "Recent results"}</h2>
              <p>{showFullHistory ? home.history_count + " canonical records" : "Latest meaningful changes"}</p>
            </div>
            {home.history_count > recentChanges.length ? (
              <button className="oi-button oi-button-secondary" type="button" onClick={() => setShowFullHistory((value) => !value)}>
                <History size={15} />{showFullHistory ? "Show recent results" : "Show full history"}
              </button>
            ) : null}
          </div>
          {visibleChanges.length ? (
            <div className="oi-change-feed">
              {visibleChanges.map((item) => item.kind === "studio_run" ? (
                <ChangeCard
                  key={item.id}
                  run={item.run}
                  expanded={selectedRunId === item.id}
                  onToggle={() => onSelectRun(selectedRunId === item.id ? null : item.id)}
                  onOpenRun={(runId) => onSelectRun(runId)}
                  onOpenDocument={onOpenPlan}
                  onChanged={onChanged}
                  requestConfirm={requestConfirm}
                />
              ) : (
                <ImportedChangeCard
                  key={item.id}
                  change={item.change}
                  expanded={selectedRunId === item.id}
                  onToggle={() => onSelectRun(selectedRunId === item.id ? null : item.id)}
                  resultTitle={!showFullHistory && item.change.spec_id ? specTitles.get(item.change.spec_id) : undefined}
                  groupSize={!showFullHistory ? home.recent_group_sizes[item.id] : undefined}
                />
              ))}
            </div>
          ) : <div className="oi-empty-result">No code changes recorded yet.</div>}
        </section>
      ) : null}

      <section className="oi-modules" aria-label="Workspace areas">
        <button className="oi-module" type="button" onClick={onOpenPlans}><span><BookOpenCheck size={16} />Plans</span><small>Why each change exists, what must become true and what remains.</small>{data.plans.count ? <b>{data.plans.count} plans</b> : null}</button>
        <button className="oi-module" type="button" onClick={onOpenLibrary}><span><Library size={16} />Library</span><small>Proven methods, proof and verified time.</small>{data.work_assets.count ? <b>{data.work_assets.count} methods</b> : null}</button>
        <button className="oi-module" type="button" onClick={onOpenAdmin}><span><Settings2 size={16} />Admin</span><small>Runtime health, workspaces and protection rules.</small><b>{data.runtime.enforcement ? "Protected" : "Audit mode"}</b></button>
      </section>
    </div>
  );
}

export function ChangeCard({
  run,
  expanded,
  onToggle,
  onOpenRun,
  onOpenDocument,
  onChanged,
  requestConfirm,
  standalone = false,
}: {
  run: AgentRun;
  expanded: boolean;
  onToggle: () => void;
  onOpenRun: (runId: string) => void;
  onOpenDocument: (documentId: string) => void;
  onChanged: () => Promise<void>;
  requestConfirm: (request: ConfirmRequest) => void;
  standalone?: boolean;
}) {
  const state = changeState(run);
  const proof = proofState(run);
  const planOnly = run.mode === "new_change";
  const planReady = run.status === "succeeded" && run.plan_handoff !== null;
  const scope = planReady
    ? { label: "Source unchanged", tone: "success" as const }
    : scopeState(run.scope);
  const [acting, setActing] = useState<string | null>(null);
  const [note, setNote] = useState(run.reviewer_note?.text ?? "");
  const [delivery, setDelivery] = useState<DeliveryStatus | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [clock, setClock] = useState(() => Date.now());

  useEffect(() => {
    if (run.status !== "running" || run.planning === null) return;
    setClock(Date.now());
    const timer = window.setInterval(() => setClock(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [run.planning?.last_activity_at, run.status]);

  useEffect(() => {
    if (!expanded || run.status !== "succeeded" || planOnly) return;
    void loadDeliveryStatus().then(setDelivery).catch(() => setDelivery(null));
  }, [expanded, planOnly, run.status]);

  async function perform<T>(label: string, action: () => Promise<T>): Promise<T | null> {
    try {
      setActing(label);
      setError(null);
      const outcome = await action();
      await onChanged();
      return outcome;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Action failed.");
      return null;
    } finally {
      setActing(null);
    }
  }

  async function retry() {
    const created = await perform("retry", () => retryRun(run.run_id));
    if (created) onOpenRun(created.run_id);
  }

  async function launchMode(mode: "recovery" | "rollback_preview") {
    if (!run.work_ref.governed_session_id) return;
    await perform(mode, () => startRun({
      mode,
      runner: run.runner,
      objective: (mode === "recovery" ? "Recover: " : "Preview rollback: ") + run.objective,
      governed_session_id: run.work_ref.governed_session_id ?? undefined,
    }));
  }

  async function saveNote() {
    await perform("note", () => saveRunReviewNote(run.run_id, note));
  }

  async function openDiff() {
    try {
      setActing("diff");
      setError(null);
      const handoff = await openRunLocalReview(run.run_id);
      setResult(handoff.status === "opened" ? "Local diff opened." : "No local diff is available.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Local diff could not open.");
    } finally {
      setActing(null);
    }
  }

  function openPreparedPlan() {
    if (!run.plan_handoff?.requirement_ids[0]) return;
    onOpenDocument(
      run.plan_handoff.spec_id + "#" + run.plan_handoff.requirement_ids[0],
    );
  }

  function deliver(action: DeliveryAction) {
    const labels: Record<DeliveryAction, string> = {
      commit: "Commit reviewed change",
      push: "Push current branch",
      open_pr: "Open pull request",
    };
    requestConfirm({
      title: labels[action],
      message: action === "commit"
        ? "Create a local Git commit from the currently staged change?"
        : action === "push"
          ? "Push the current branch to its configured upstream?"
          : "Open a pull request from the current branch?",
      confirmLabel: labels[action],
      action: async () => {
        await perform(action, async () => {
          await runDeliveryAction(action, true, action === "commit" ? run.objective.slice(0, 160) : undefined);
          setDelivery(await loadDeliveryStatus());
        });
      },
    });
  }

  const nextLabel = planReady
    ? "Review plan"
    : run.status === "succeeded"
      ? "Review result"
      : run.can_retry
      ? "Retry"
      : run.can_cancel
        ? "View progress"
        : "Open change";
  const nextIcon = run.can_retry ? Repeat2 : ArrowRight;
  const nextAction = planReady
    ? openPreparedPlan
    : run.can_retry
      ? () => void retry()
      : onToggle;
  const planningElapsed = run.started_at
    ? (clock - new Date(run.started_at).getTime()) / 1000
    : 0;
  const planningIdle = run.planning
    ? (clock - new Date(run.planning.last_activity_at).getTime()) / 1000
    : 0;
  const planningRemaining = run.planning
    ? run.planning.timeout_after_seconds - planningElapsed
    : 0;

  return (
    <article className={"oi-change-card " + (expanded ? "is-open " : "") + (standalone ? "is-standalone" : "")}>
      <div className="oi-change-main">
        <button className="oi-change-open" type="button" onClick={onToggle} aria-expanded={expanded}>
          <span className={"oi-status-icon tone-" + state.tone}>{run.status === "succeeded" ? <Check size={18} /> : run.status === "running" ? <LoaderCircle className="spin" size={18} /> : run.can_retry ? <AlertTriangle size={18} /> : <Clock3 size={18} />}</span>
          <span className="oi-change-copy">
            <strong>{run.objective}</strong>
            <span>{formatDate(run.started_at ?? run.created_at)} · {deltaLabel(run)}</span>
          </span>
        </button>
        <div className="oi-change-badges">
          <span className={"oi-badge tone-" + state.tone}>{state.label}</span>
          <span className={"oi-badge tone-" + scope.tone}>{scope.label}</span>
          {proof.label !== state.label ? <span className={"oi-badge tone-" + proof.tone}>{proof.label}</span> : null}
        </div>
        <button className="oi-button oi-button-primary oi-next-action" type="button" disabled={acting !== null} onClick={nextAction}>
          {nextIcon === Repeat2 ? <Repeat2 size={15} /> : <ArrowRight size={15} />}{nextLabel}
        </button>
      </div>

      {expanded ? (
        <div className="oi-change-detail">
          <div className="oi-change-summary">
            <div><span>Current step</span><strong>{run.message}</strong></div>
            <div><span>Observed result</span><strong>{deltaLabel(run)}</strong></div>
            <div><span>Scope</span><strong>{scope.label}</strong></div>
          </div>
          {run.failure ? (
            <section className="oi-run-failure" aria-label="What happened">
              <div><span>What happened</span><strong>{run.failure.headline}</strong><p>{run.failure.explanation}</p></div>
              <div><span>What to do</span><strong>{run.failure.next_step}</strong></div>
            </section>
          ) : null}
          {run.status === "running" && run.planning ? (
            <section className="oi-planning-budget" aria-label="Planning budget">
              <div><span>Elapsed</span><strong>{formatDuration(planningElapsed)}</strong></div>
              <div><span>Last activity</span><strong>{formatDuration(planningIdle)} ago</strong></div>
              <div><span>Time remaining</span><strong>{formatDuration(planningRemaining)}</strong></div>
              <small>{run.planning.inspection_events} of {run.planning.inspection_limit} bounded context checks before contract authoring</small>
            </section>
          ) : null}
          {run.scope.blocked_out_of_scope || run.scope.reverted_out_of_scope || run.scope.unresolved_out_of_scope ? (
            <div className={"oi-scope-report " + (run.scope.unresolved_out_of_scope ? "is-error" : "is-protected")}>
              <ShieldCheck size={17} />
              <span>{run.scope.blocked_out_of_scope} extra writes detected · {run.scope.reverted_out_of_scope} reverted · {run.scope.unresolved_out_of_scope} unresolved</span>
            </div>
          ) : null}

          {planReady && run.plan_handoff ? <section className="oi-plan-handoff">
            <div><span>Prepared plan</span><strong>{run.plan_handoff.objective}</strong><small>{run.plan_handoff.requirement_ids.length} reviewable outcomes · scope and tests await owner approval</small></div>
            <button className="oi-button oi-button-primary" type="button" onClick={openPreparedPlan}><BookOpenCheck size={15} />Review plan</button>
          </section> : null}

          <div className="oi-detail-columns">
            <section>
              <h3>Progress</h3>
              <ol className="oi-timeline">{run.timeline.slice(-8).map((event, index) => <li key={event.at + index}><span /> <div><strong>{event.message}</strong><small>{formatDate(event.at)}</small></div></li>)}</ol>
            </section>
            <section>
              <h3>Review</h3>
              <label className="oi-note"><span>Reviewer note</span><textarea rows={3} value={note} onChange={(event) => setNote(event.target.value)} placeholder="Record the review outcome" /></label>
              <div className="oi-action-row">
                <button className="oi-button oi-button-secondary" type="button" disabled={acting !== null || note.trim().length < 3} onClick={() => void saveNote()}><Check size={15} />Save note</button>
                {run.can_cancel ? <button className="oi-button oi-button-secondary" type="button" disabled={acting !== null} onClick={() => void perform("cancel", () => cancelRun(run.run_id))}><CircleStop size={15} />Stop</button> : null}
                {run.can_retry ? <button className="oi-button oi-button-secondary" type="button" disabled={acting !== null} onClick={() => void retry()}><Repeat2 size={15} />Retry</button> : null}
                {run.work_ref.governed_session_id && run.can_retry ? <button className="oi-button oi-button-secondary" type="button" disabled={acting !== null} onClick={() => void launchMode("recovery")}><RefreshCw size={15} />Recover</button> : null}
                {run.work_ref.governed_session_id && run.status !== "running" ? <button className="oi-button oi-button-secondary" type="button" disabled={acting !== null} onClick={() => void launchMode("rollback_preview")}><RotateCcw size={15} />Preview rollback</button> : null}
              </div>
            </section>
          </div>

          {!planOnly && run.status === "succeeded" && delivery ? (
            <section className="oi-delivery">
              <h3>Deliver</h3>
              <div className="oi-action-row">
                <button className="oi-button oi-button-primary" type="button" disabled={!delivery.can_commit || acting !== null} onClick={() => deliver("commit")}><GitCommitHorizontal size={15} />Commit</button>
                <button className="oi-button oi-button-secondary" type="button" disabled={!delivery.can_push || acting !== null} onClick={() => deliver("push")}><Send size={15} />Push</button>
                <button className="oi-button oi-button-secondary" type="button" disabled={!delivery.can_open_pr || acting !== null} onClick={() => deliver("open_pr")}><GitPullRequest size={15} />Open PR</button>
              </div>
            </section>
          ) : null}

          {!planOnly ? <ProofDetails run={run} onOpenLocalReview={() => void openDiff()} opening={acting === "diff"} /> : null}
          {acting ? <div className="oi-progress" role="status"><LoaderCircle className="spin" size={15} />Working…</div> : null}
          {result ? <div className="oi-alert is-good">{result}</div> : null}
          {error ? <div className="oi-alert is-error" role="alert"><AlertTriangle size={15} />{error}</div> : null}
        </div>
      ) : null}
    </article>
  );
}

export function BacklogView({
  data,
  onOpenPlan,
}: {
  data: WorkspaceOverview;
  onOpenPlan: (documentId: string) => void;
}) {
  return (
    <div className="oi-page">
      <header className="oi-page-header"><div><span>Project knowledge</span><h1>Plans</h1><p>Read why each change exists, what must become true and what remains to be done.</p></div></header>
      {data.summary.coverage_status === "unavailable" ? <div className="oi-alert is-warning"><AlertTriangle size={15} /><span><strong>Live requirement coverage is unavailable.</strong> Requirement totals are intentionally hidden until APatch can read the canonical ledger again.</span></div> : null}
      <section className="oi-plan-list" aria-label="Project plans">
        {data.plans.items.map((plan) => <article className="oi-plan-row" key={plan.id}>
          <div className="oi-plan-progress" aria-label={plan.progress.percent + "% complete"}><span style={{ width: plan.progress.percent + "%" }} /></div>
          <div className="oi-plan-copy"><div><strong>{plan.title}</strong><span className={"oi-badge tone-" + (plan.state === "complete" ? "success" : plan.state === "needs_recheck" ? "warning" : plan.state === "blocked" ? "danger" : "info")}>{plan.state_label}</span></div><p>{plan.purpose}</p><small>{plan.progress.total ? plan.progress.complete + " of " + plan.progress.total + " outcomes confirmed" : "Proposal awaiting an executable plan"}</small></div>
          <button className="oi-button oi-button-primary" type="button" onClick={() => onOpenPlan(plan.open_document_id)}><BookOpenCheck size={15} />Open plan</button>
        </article>)}
        {data.plans.items.length === 0 ? <div className="oi-empty"><BookOpenCheck size={28} /><strong>No project plans yet</strong><span>Start a change from Home to create the first governed plan.</span></div> : null}
      </section>
    </div>
  );
}

type LibrarySection = "methods" | "proof" | "time";

export function LibraryView({
  data,
  section,
  onSection,
  runners,
  onChanged,
}: {
  data: WorkspaceOverview;
  section: LibrarySection;
  onSection: (section: LibrarySection) => void;
  runners: RunnerInfo[];
  onChanged: () => Promise<void>;
}) {
  return (
    <div className="oi-page">
      <header className="oi-page-header"><div><span>Reusable results</span><h1>Library</h1><p>Methods, proof and verified time</p></div></header>
      <div className="oi-segments" role="tablist">
        <button className={section === "methods" ? "is-active" : ""} type="button" onClick={() => onSection("methods")}><Library size={15} />Methods</button>
        <button className={section === "proof" ? "is-active" : ""} type="button" onClick={() => onSection("proof")}><ShieldCheck size={15} />Proof</button>
        <button className={section === "time" ? "is-active" : ""} type="button" onClick={() => onSection("time")}><Clock3 size={15} />Time</button>
      </div>
      {section === "methods" ? <MethodsLibrary data={data} runners={runners} onChanged={onChanged} /> : null}
      {section === "proof" ? <ProofLibrary data={data} /> : null}
      {section === "time" ? <TimeLibrary workspaceName={data.workspace.name} /> : null}
    </div>
  );
}

function MethodsLibrary({ data, runners, onChanged }: { data: WorkspaceOverview; runners: RunnerInfo[]; onChanged: () => Promise<void> }) {
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<WorkAsset[]>(data.work_assets.items);
  const [acting, setActing] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<ActionReceipt | null>(null);
  const [error, setError] = useState<string | null>(null);
  const runner = runners.find((item) => item.available);

  async function search() {
    try {
      setActing("search");
      const receipt = await searchAssets(query, 30);
      setItems(receipt.result.items ?? []);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Search failed.");
    } finally {
      setActing(null);
    }
  }

  async function suggest() {
    if (!query.trim()) return;
    try {
      setActing("suggest");
      const result = await suggestAssets(query.trim(), 10);
      setItems(result.result.items ?? []);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Suggestions failed.");
    } finally {
      setActing(null);
    }
  }

  async function use(asset: WorkAsset) {
    if (!runner) return;
    try {
      setActing(asset.id);
      await runAssetAction(asset.id, "recall", query || asset.title);
      await startRun({
        mode: "new_change",
        runner: runner.id,
        objective: query.trim() || "Apply the proven method: " + asset.title,
        acceptance_criteria: [defaultCriterion(query.trim() || asset.title)],
        work_asset_id: asset.id,
      });
      await onChanged();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The method could not start.");
    } finally {
      setActing(null);
    }
  }

  async function exportAsset(asset: WorkAsset) {
    try {
      setActing("export:" + asset.id);
      setReceipt(await runAssetAction(asset.id, "export"));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The method could not be exported.");
    } finally {
      setActing(null);
    }
  }

  return <section>
    <div className="oi-search-row"><Search size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Find a proven method" /><button className="oi-button oi-button-secondary" type="button" disabled={acting !== null} onClick={() => void search()}>Search assets</button><button className="oi-button oi-button-secondary" type="button" disabled={acting !== null || !query.trim()} onClick={() => void suggest()}><Sparkles size={15} />Suggest for task</button></div>
    <p className="oi-disclaimer">Viewing a method does not record reuse. Reuse is recorded only after governed verification.</p>
    <div className="oi-library-grid">{items.map((asset) => <article className="oi-method-card" key={asset.id}><span>{asset.kind}</span><strong>{asset.title}</strong><small>{asset.verification_count} checks · used {asset.reuse_count} times</small><div className="oi-action-row">{asset.recallable ? <button className="oi-button oi-button-primary" type="button" disabled={acting !== null || !runner} onClick={() => void use(asset)}><Play size={15} />Apply in governed work</button> : <div className="oi-alert"><BookOpenCheck size={15} />Reference only · reusable instructions are not packaged yet</div>}<button className="oi-button oi-button-secondary" type="button" disabled={acting !== null} onClick={() => void exportAsset(asset)}><Send size={15} />Export asset</button></div></article>)}</div>
    {items.length === 0 ? <div className="oi-empty"><Library size={28} /><strong>No matching methods</strong><span>Complete proven changes to grow the library.</span></div> : null}
    {receipt ? <ActionResultView receipt={receipt} /> : null}
    {error ? <div className="oi-alert is-error"><AlertTriangle size={15} />{error}</div> : null}
  </section>;
}

function ProofLibrary({ data }: { data: WorkspaceOverview }) {
  const artifacts = useMemo(() => data.specifications.flatMap((specification) => [...specification.stale_ids, ...specification.pending_ids].map((requirement) => ({ value: "spec:" + specification.id + "#" + requirement, label: specification.title + " / " + requirement }))), [data.specifications]);
  const [artifact, setArtifact] = useState(artifacts[0]?.value ?? "");
  const [acting, setActing] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<ActionReceipt<EvidenceActionResult> | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function act(action: "history" | "verify" | "coverage" | "inclusion" | "ratify" | "reality" | "export") {
    try {
      setActing(action);
      setError(null);
      setReceipt(await runEvidenceAction(action, artifact || null));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Proof check failed.");
    } finally {
      setActing(null);
    }
  }

  return <section className="oi-panel">
    <label className="oi-field"><span>Backlog item</span><select value={artifact} onChange={(event) => setArtifact(event.target.value)}><option value="">Whole workspace</option>{artifacts.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
    <div className="oi-action-row">
      <button className="oi-button oi-button-primary" type="button" disabled={acting !== null} onClick={() => void act("verify")}><ShieldCheck size={15} />Verify proof</button>
      <button className="oi-button oi-button-secondary" type="button" disabled={acting !== null} onClick={() => void act("history")}><History size={15} />View history</button>
      <button className="oi-button oi-button-secondary" type="button" disabled={acting !== null} onClick={() => void act("coverage")}><FileSearch size={15} />Check coverage</button>
      <button className="oi-button oi-button-secondary" type="button" disabled={acting !== null} onClick={() => void act("inclusion")}><FileSearch size={15} />Independent log check</button>
      <button className="oi-button oi-button-secondary" type="button" disabled={acting !== null} onClick={() => void act("ratify")}><RefreshCw size={15} />Re-check policy gate</button>
      <button className="oi-button oi-button-secondary" type="button" disabled={acting !== null} onClick={() => void act("reality")}><FileCode2 size={15} />Check source state</button>
      <button className="oi-button oi-button-secondary" type="button" disabled={acting !== null} onClick={() => void act("export")}><Send size={15} />Export</button>
    </div>
    {acting ? <div className="oi-progress"><LoaderCircle className="spin" size={15} />Checking…</div> : null}
    {receipt ? <ActionResultView receipt={receipt} /> : null}
    {error ? <div className="oi-alert is-error"><AlertTriangle size={15} />{error}</div> : null}
  </section>;
}
