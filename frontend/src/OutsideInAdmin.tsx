import {
  AlertTriangle,
  Check,
  Database,
  FileCheck2,
  Inbox,
  KeyRound,
  LoaderCircle,
  RefreshCw,
  RotateCcw,
  Send,
  Server,
  ShieldCheck,
  SlidersHorizontal,
  Trash2,
  UserRoundCheck,
} from "lucide-react";
import { useEffect, useState } from "react";

import {
  cancelExecutionIntent,
  confirmExecutionIntent,
  importExecutionIntent,
  loadExecutionIntents,
  previewExecutionIntentResult,
  submitExecutionIntentResult,
  runPolicyAction,
  runSystemAction,
  runWorkspaceAction,
} from "./api";
import { ActionResultView } from "./OutsideInViews";
import type { ConfirmRequest } from "./OutsideInViews";
import type {
  ActionReceipt,
  CoworkResultDeliveryPlan,
  CoworkResultDeliveryReceipt,
  ExecutionIntentPreview,
  RunnerInfo,
  WorkspaceAlias,
  WorkspaceOverview,
} from "./types";

export function AdminView({
  data,
  runners,
  section,
  onSection,
  requestConfirm,
  onChanged,
}: {
  data: WorkspaceOverview;
  runners: RunnerInfo[];
  section: "runtime" | "workspaces" | "rules";
  onSection: (section: "runtime" | "workspaces" | "rules") => void;
  requestConfirm: (request: ConfirmRequest) => void;
  onChanged: () => Promise<void>;
}) {
  const sections = [
    ["runtime", "Runtime", Server],
    ["workspaces", "Workspaces", Database],
    ["rules", "Rules", SlidersHorizontal],
  ] as Array<["runtime" | "workspaces" | "rules", string, typeof Server]>;
  return <div className="oi-page">
    <header className="oi-page-header"><div><span>Operations</span><h1>Admin</h1><p>{data.product.name} {data.product.edition.toUpperCase()}</p></div></header>
    <div className="oi-segments" role="tablist">{sections.map(([id, label, Icon]) => <button key={id} className={section === id ? "is-active" : ""} type="button" onClick={() => onSection(id)}><Icon size={15} />{label}</button>)}</div>
    {section === "runtime" ? <RuntimeAdmin data={data} requestConfirm={requestConfirm} onChanged={onChanged} /> : null}
    {section === "workspaces" ? <WorkspaceAdmin data={data} requestConfirm={requestConfirm} /> : null}
    {section === "rules" ? <RulesAdmin data={data} requestConfirm={requestConfirm} /> : null}
    <div className="oi-local-boundary"><ShieldCheck size={18} /><span>Source, prompts, local paths and credentials stay on this computer.</span><strong>{runners.filter((item) => item.available).length} local agents</strong></div>
  </div>;
}

function RuntimeAdmin({ data, requestConfirm, onChanged }: { data: WorkspaceOverview; requestConfirm: (request: ConfirmRequest) => void; onChanged: () => Promise<void> }) {
  const [acting, setActing] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<ActionReceipt | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function act(action: "doctor" | "hygiene" | "gc_preview" | "gc_execute", confirmed = false) {
    try {
      setActing(action);
      setError(null);
      setReceipt(await runSystemAction(action, confirmed));
      await onChanged();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Runtime action failed.");
    } finally {
      setActing(null);
    }
  }

  function cleanup() {
    requestConfirm({
      title: "Run safe cleanup",
      message: "Delete only local APatch artifacts already classified as safe to reclaim?",
      confirmLabel: "Clean up",
      tone: "danger",
      action: () => act("gc_execute", true),
    });
  }

  return <section className="oi-admin-grid">
    <article className="oi-panel">
      <div className="oi-panel-heading"><div><span>Local runtime</span><strong>{data.runtime.apatch_version}</strong></div><Server size={20} /></div>
      <dl className="oi-key-values">
        <div><dt>Health</dt><dd>{data.runtime.hygiene}</dd></div>
        <div><dt>Protection</dt><dd>{data.runtime.enforcement ? "Enforced" : "Audit"}</dd></div>
        <div><dt>Parallel work</dt><dd>{data.runtime.concurrent_writers ? "Available" : "Unavailable"}</dd></div>
        <div><dt>Agent tools</dt><dd>{data.runtime.tool_count}</dd></div>
        <div><dt>Machine identity</dt><dd>{data.runtime.endpoint_identity.headline}{data.runtime.endpoint_identity.enrolled ? "" : ". " + data.runtime.endpoint_identity.next_step}</dd></div>
        <div><dt>Required fixes</dt><dd>{data.runtime.requirements.ok ? "All present" : data.runtime.requirements.missing.length + " missing"}</dd></div>
        <div><dt>Runtime check</dt><dd>{data.runtime.requirements.headline}{data.runtime.requirements.ok ? "" : ". " + data.runtime.requirements.next_step}</dd></div>
      </dl>
      <div className="oi-action-row">
        <button className="oi-button oi-button-primary" type="button" disabled={acting !== null} onClick={() => void act("doctor")}><ShieldCheck size={15} />Check runtime</button>
        <button className="oi-button oi-button-secondary" type="button" disabled={acting !== null} onClick={() => void act("hygiene")}><Check size={15} />Check storage</button>
        <button className="oi-button oi-button-secondary" type="button" disabled={acting !== null} onClick={() => void act("gc_preview")}><RefreshCw size={15} />Preview cleanup</button>
        <button className="oi-button oi-button-danger" type="button" disabled={acting !== null} onClick={cleanup}><Trash2 size={15} />Clean up</button>
      </div>
    </article>
    {acting ? <div className="oi-progress"><LoaderCircle className="spin" size={15} />Working…</div> : null}
    {receipt ? <ActionResultView receipt={receipt} /> : null}
    {error ? <div className="oi-alert is-error"><AlertTriangle size={15} />{error}</div> : null}
  </section>;
}

function WorkspaceAdmin({ data, requestConfirm }: { data: WorkspaceOverview; requestConfirm: (request: ConfirmRequest) => void }) {
  const [alias, setAlias] = useState(data.workspace.name.toLowerCase().replace(/[^a-z0-9._-]+/g, "-").replace(/^[^a-z]+/, "") || "workspace");
  const [items, setItems] = useState<WorkspaceAlias[]>([]);
  const [acting, setActing] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    const receipt = await runWorkspaceAction("list");
    setItems(receipt.result.items ?? []);
  }

  useEffect(() => { void refresh().catch(() => setError("Workspace list unavailable.")); }, []);

  async function mutate(action: "register" | "remove", value: string) {
    try {
      setActing(action);
      setError(null);
      await runWorkspaceAction(action, value, true);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Workspace action failed.");
    } finally {
      setActing(null);
    }
  }

  function register() {
    requestConfirm({
      title: "Add workspace alias",
      message: "Register @" + alias + " for the workspace currently open in Studio?",
      confirmLabel: "Add alias",
      action: () => mutate("register", alias),
    });
  }

  function remove(value: string) {
    requestConfirm({
      title: "Remove workspace alias",
      message: "Remove @" + value + " from local routing?",
      confirmLabel: "Remove",
      tone: "danger",
      action: () => mutate("remove", value),
    });
  }

  return <section className="oi-panel">
    <div className="oi-inline-form"><label className="oi-field"><span>Alias</span><input value={alias} onChange={(event) => setAlias(event.target.value)} /></label><button className="oi-button oi-button-primary" type="button" disabled={acting !== null || !alias} onClick={register}><Check size={15} />Add current workspace</button></div>
    <div className="oi-list">{items.map((item) => <div className="oi-list-row" key={item.alias}><div><strong>@{item.alias}</strong><span>{item.ready ? "Ready" : "Needs attention"}</span></div><button className="oi-icon-button" title={"Remove @" + item.alias} type="button" onClick={() => remove(item.alias)}><Trash2 size={15} /></button></div>)}</div>
    {error ? <div className="oi-alert is-error"><AlertTriangle size={15} />{error}</div> : null}
  </section>;
}

function RulesAdmin({ data, requestConfirm }: { data: WorkspaceOverview; requestConfirm: (request: ConfirmRequest) => void }) {
  const [enforce, setEnforce] = useState(data.runtime.enforcement);
  const [acting, setActing] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<ActionReceipt | null>(null);

  async function act(action: "status" | "preview" | "apply" | "sign" | "verify" | "restore", confirmed = false) {
    setActing(action);
    try {
      setReceipt(await runPolicyAction(action, action === "preview" || action === "apply" ? { mode: enforce ? "enforce" : "audit" } : {}, confirmed));
    } finally {
      setActing(null);
    }
  }

  function confirmRule(action: "apply" | "sign" | "restore", title: string, message: string) {
    requestConfirm({
      title,
      message,
      confirmLabel: title,
      tone: action === "restore" ? "danger" : "default",
      action: () => act(action, true),
    });
  }

  return <section className="oi-panel">
    <label className="oi-toggle"><input type="checkbox" checked={enforce} onChange={(event) => setEnforce(event.target.checked)} /><span />Protect files outside requested scope</label>
    <div className="oi-action-row">
      <button className="oi-button oi-button-primary" type="button" disabled={acting !== null} onClick={() => void act("preview")}><SlidersHorizontal size={15} />Preview</button>
      <button className="oi-button oi-button-secondary" type="button" disabled={acting !== null} onClick={() => confirmRule("apply", "Apply rule", "Apply the selected protection mode to this workspace?")}><Check size={15} />Apply</button>
      <button className="oi-button oi-button-secondary" type="button" disabled={acting !== null} onClick={() => confirmRule("sign", "Sign rules", "Sign the current local rules with the enrolled identity?")}><KeyRound size={15} />Sign</button>
      <button className="oi-button oi-button-secondary" type="button" disabled={acting !== null} onClick={() => void act("verify")}><ShieldCheck size={15} />Verify</button>
      <button className="oi-button oi-button-danger" type="button" disabled={acting !== null} onClick={() => confirmRule("restore", "Restore previous", "Restore the previous local rule version?")}><RotateCcw size={15} />Restore</button>
    </div>
    {receipt ? <ActionResultView receipt={receipt} /> : null}
  </section>;
}

function ResultDeliveryPanel({
  item,
  onRefresh,
  onChanged,
}: {
  item: ExecutionIntentPreview;
  onRefresh: () => Promise<void>;
  onChanged: () => Promise<void>;
}) {
  const [relativePath, setRelativePath] = useState("");
  const [plan, setPlan] = useState<CoworkResultDeliveryPlan | null>(null);
  const [receipt, setReceipt] = useState<CoworkResultDeliveryReceipt | null>(null);
  const [acting, setActing] = useState<"preview" | "submit" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const recorded = receipt ?? item.result_delivery;

  async function prepare() {
    try {
      setActing("preview");
      setError(null);
      setReceipt(null);
      setPlan(await previewExecutionIntentResult(item.intent_id, relativePath.trim()));
    } catch (reason) {
      setPlan(null);
      setError(reason instanceof Error ? reason.message : "Result preview failed.");
    } finally {
      setActing(null);
    }
  }

  async function submit() {
    if (!plan) return;
    try {
      setActing("submit");
      setError(null);
      setReceipt(
        await submitExecutionIntentResult(item.intent_id, relativePath.trim(), plan),
      );
      await onRefresh();
      await onChanged();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Result submission failed.");
    } finally {
      setActing(null);
    }
  }

  if (recorded.state === "submitted") {
    return <section className="oi-result-delivery is-submitted" aria-label="Cowork result submission">
      <div className="oi-result-title"><FileCheck2 size={17} /><div><strong>Submitted to Cowork</strong><span>The project now has a reviewable result backed by APatch evidence.</span></div></div>
      <dl className="oi-result-facts">
        <div><dt>Result hash</dt><dd><code>{recorded.result.outcome_ref}</code></dd></div>
        <div><dt>Evidence bundle</dt><dd><code>{recorded.evidence.bundle_id}</code></dd></div>
        <div><dt>Release receipt</dt><dd><code>{recorded.release.release_id}</code></dd></div>
      </dl>
    </section>;
  }

  if (!item.result_delivery.can_prepare) return null;

  return <section className="oi-result-delivery" aria-label="Submit result to Cowork">
    <div className="oi-result-title"><Send size={17} /><div><strong>Send finished work to Cowork</strong><span>Choose one result file from this workspace. Studio prepares the proof locally before anything is shared.</span></div></div>
    <div className="oi-result-compose">
      <label className="oi-field"><span>Result file</span><input aria-label="Result file" placeholder="reports/result.md" value={relativePath} onChange={(event) => { setRelativePath(event.target.value); setPlan(null); setReceipt(null); }} /></label>
      <button className="oi-button oi-button-secondary" type="button" disabled={acting !== null || relativePath.trim().length === 0} onClick={() => void prepare()}>{acting === "preview" ? <LoaderCircle className="spin" size={15} /> : <FileCheck2 size={15} />}Prepare submission</button>
    </div>
    {plan ? <div className="oi-result-review">
      <div>
        <strong>Shared with Cowork</strong>
        <dl className="oi-result-facts">
          <div><dt>Relative file name</dt><dd><code>{plan.result.relative_path}</code></dd></div>
          <div><dt>Result hash</dt><dd><code>{plan.result.outcome_ref}</code></dd></div>
          <div><dt>File size</dt><dd>{plan.result.size_bytes.toLocaleString()} bytes</dd></div>
          <div><dt>Evidence bundle</dt><dd><code>{plan.evidence.bundle_id}</code></dd></div>
          <div><dt>Evidence hash</dt><dd><code>{plan.evidence.bundle_hash}</code></dd></div>
          <div><dt>Claimed active time</dt><dd>{plan.evidence.claimed_active_seconds.toLocaleString()} seconds</dd></div>
        </dl>
      </div>
      <div className="oi-result-local"><strong>Kept on this computer</strong><p>Source code, prompts, credentials, absolute paths and result contents stay local. Cowork receives hashes, bounded evidence and the release receipt.</p></div>
      <div className="oi-result-consent"><span>Exact confirmation</span><code>submit:{plan.plan_hash}</code><button className="oi-button oi-button-primary" type="button" disabled={acting !== null} onClick={() => void submit()}>{acting === "submit" ? <LoaderCircle className="spin" size={15} /> : <Send size={15} />}Submit to Cowork</button></div>
    </div> : null}
    {error ? <div className="oi-alert is-error"><AlertTriangle size={15} />{error}</div> : null}
  </section>;
}

export function InboxView({
  data,
  runners,
  onChanged,
}: {
  data: WorkspaceOverview;
  runners: RunnerInfo[];
  onChanged: () => Promise<void>;
}) {
  const [items, setItems] = useState<ExecutionIntentPreview[]>([]);
  const [envelope, setEnvelope] = useState("");
  const [acting, setActing] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [executionMode, setExecutionMode] = useState<"new_change" | "specification">(
    data.execution_intents.cowork_connected ? "specification" : "new_change",
  );
  const [existingSpecId, setExistingSpecId] = useState("");
  const runner = runners.find((item) => item.available);
  const workspaceId = data.execution_intents.workspace_id;
  const requiresCowork = (item: ExecutionIntentPreview) =>
    item.cowork?.required ?? (data.execution_intents.cowork_connected && item.can_confirm);
  const visibleStatus = (item: ExecutionIntentPreview) =>
    item.cowork?.status ?? item.status;

  async function refresh() {
    const page = await loadExecutionIntents();
    setItems(page.items);
  }
  useEffect(() => { void refresh().catch(() => setError("Inbox unavailable.")); }, []);

  async function confirm(item: ExecutionIntentPreview) {
    if (!runner || !workspaceId) return;
    const coworkRequired = requiresCowork(item);
    try {
      setActing(item.intent_id);
      await confirmExecutionIntent(
        item.intent_id,
        workspaceId,
        runner.id,
        coworkRequired ? "specification" : executionMode,
        coworkRequired || executionMode === "specification" ? existingSpecId.trim() : undefined,
      );
      await refresh();
      await onChanged();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Task could not be confirmed.");
    } finally {
      setActing(null);
    }
  }

  async function cancel(item: ExecutionIntentPreview) {
    setActing(item.intent_id);
    try {
      await cancelExecutionIntent(item.intent_id);
      await refresh();
    } finally {
      setActing(null);
    }
  }

  async function importTask() {
    try {
      setActing("import");
      await importExecutionIntent(envelope);
      setEnvelope("");
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Signed task could not be imported.");
    } finally {
      setActing(null);
    }
  }

  return <div className="oi-page">
    <header className="oi-page-header"><div><span>Signed requests</span><h1>Inbox</h1><p>{items.filter((item) => item.can_confirm).length} ready</p></div></header>
    <div className="oi-list">{items.map((item) => <article className="oi-list-row oi-request-row" key={item.intent_id}>
      <UserRoundCheck size={18} />
      <div><strong>{item.objective}</strong><span>{item.acceptance_criteria.length} acceptance checks · expires {new Date(item.expires_at).toLocaleString()}</span></div>
      <span className="oi-badge tone-neutral">{visibleStatus(item)}</span>
      <div className="oi-action-row">
        {item.can_confirm ? <>
          {requiresCowork(item) ? <span className="oi-inline-note">Cowork acceptance and source binding are required before the agent starts.</span> : <label className="oi-field"><span>Local action</span><select aria-label="Local action" value={executionMode} onChange={(event) => setExecutionMode(event.target.value as "new_change" | "specification")}><option value="new_change">Prepare new contract</option><option value="specification">Run existing SPEC</option></select></label>}
          {requiresCowork(item) || executionMode === "specification" ? <label className="oi-field"><span>Existing SPEC</span><input aria-label="Existing SPEC" placeholder="SPEC-…" value={existingSpecId} onChange={(event) => setExistingSpecId(event.target.value.toUpperCase())} /></label> : null}
        </> : null}
        <button className="oi-button oi-button-primary" type="button" disabled={!item.can_confirm || acting !== null || !runner || !workspaceId || ((requiresCowork(item) || executionMode === "specification") && !/^SPEC-[A-Z0-9][A-Z0-9-]{1,95}$/.test(existingSpecId.trim()))} onClick={() => void confirm(item)}><Check size={15} />{requiresCowork(item) ? "Accept in Cowork & run" : "Run locally"}</button>
        <button className="oi-icon-button" title="Decline request" type="button" disabled={!item.can_cancel || acting !== null} onClick={() => void cancel(item)}><RotateCcw size={15} /></button>
      </div>
      <ResultDeliveryPanel item={item} onRefresh={refresh} onChanged={onChanged} />
    </article>)}</div>
    {data.execution_intents.configured ? <>{items.length === 0 ? <div className="oi-empty"><Inbox size={28} /><strong>No signed tasks are waiting</strong><span>New requests from a trusted issuer will appear here.</span></div> : null}<details className="oi-proof"><summary><KeyRound size={15} />Import signed task</summary><label className="oi-field"><span>Signed envelope</span><textarea rows={5} value={envelope} onChange={(event) => setEnvelope(event.target.value)} /></label><button className="oi-button oi-button-secondary" type="button" disabled={acting !== null || envelope.length < 10} onClick={() => void importTask()}><Inbox size={15} />Import</button></details></> : <div className="oi-empty"><KeyRound size={28} /><strong>Connect a trusted task issuer</strong><span>Signed task import is available after trust is configured. Start this local client with an execution-intent trust file; this works in OSS without a Cowork account. Solo work needs no account or trust file; private signing keys never belong here.</span></div>}
    {error ? <div className="oi-alert is-error"><AlertTriangle size={15} />{error}</div> : null}
  </div>;
}
