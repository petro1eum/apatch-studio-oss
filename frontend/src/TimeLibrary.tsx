import {
  AlertTriangle,
  CalendarDays,
  Clock3,
  Download,
  LoaderCircle,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { loadContributionHealth, runTimesheet } from "./api";
import { downloadTimesheetCsv } from "./timesheetCsv";
import type {
  ContributionHealth,
  TimesheetDimension,
  TimesheetDraft,
  TimesheetVerification,
} from "./types";


type PeriodPreset = "7" | "30" | "custom";
type TimeGrouping = Extract<TimesheetDimension, "day" | "spec">;

function isoDate(value: Date) {
  return value.toISOString().slice(0, 10);
}

function lastDays(days: number) {
  const until = new Date();
  const since = new Date(until);
  since.setUTCDate(since.getUTCDate() - (days - 1));
  return { since: isoDate(since), until: isoDate(until) };
}

export function TimeLibrary({ workspaceName }: { workspaceName: string }) {
  const initial = useMemo(() => lastDays(7), []);
  const [preset, setPreset] = useState<PeriodPreset>("7");
  const [since, setSince] = useState(initial.since);
  const [until, setUntil] = useState(initial.until);
  const [grouping, setGrouping] = useState<TimeGrouping>("day");
  const [draft, setDraft] = useState<TimesheetDraft | null>(null);
  const [verification, setVerification] = useState<TimesheetVerification | null>(null);
  const [health, setHealth] = useState<ContributionHealth | null>(null);
  const [acting, setActing] = useState<string | null>("draft");
  const [error, setError] = useState<string | null>(null);

  async function calculate(action: "draft" | "verify") {
    if (!since || !until || since > until) {
      setError("Choose a valid date range.");
      return;
    }
    try {
      setActing(action);
      setError(null);
      const result = await runTimesheet(action, [grouping], since, until);
      if ("groups" in result) {
        setDraft(result);
        setVerification(null);
      } else {
        setVerification(result);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Time calculation failed.");
    } finally {
      setActing(null);
    }
  }

  useEffect(() => {
    void calculate("draft");
    void loadContributionHealth().then(setHealth).catch(() => setHealth(null));
  }, []);

  function choosePreset(days: 7 | 30) {
    const next = lastDays(days);
    setPreset(String(days) as PeriodPreset);
    setSince(next.since);
    setUntil(next.until);
  }

  const totals = useMemo(() => (draft?.groups ?? []).reduce(
    (sum, group) => ({
      hours: sum.hours + group.hours,
      sessions: sum.sessions + group.sessions,
      ops: sum.ops + group.ops,
      files: sum.files + group.files_touched,
    }),
    { hours: 0, sessions: 0, ops: 0, files: 0 },
  ), [draft]);
  const visibleGroups = (draft?.groups ?? []).slice(0, 80);

  return (
    <section className="oi-time-workflow">
      <div className="oi-time-toolbar">
        <div className="oi-time-presets" aria-label="Time period">
          <button className={preset === "7" ? "is-active" : ""} type="button" onClick={() => choosePreset(7)}>7 days</button>
          <button className={preset === "30" ? "is-active" : ""} type="button" onClick={() => choosePreset(30)}>30 days</button>
          <button className={preset === "custom" ? "is-active" : ""} type="button" onClick={() => setPreset("custom")}>Custom</button>
        </div>
        <div className="oi-time-dates">
          <label><span>From</span><input type="date" value={since} onChange={(event) => { setPreset("custom"); setSince(event.target.value); }} /></label>
          <label><span>To</span><input type="date" value={until} onChange={(event) => { setPreset("custom"); setUntil(event.target.value); }} /></label>
        </div>
        <div className="oi-time-grouping" aria-label="Group time">
          <button className={grouping === "day" ? "is-active" : ""} type="button" onClick={() => setGrouping("day")}>By day</button>
          <button className={grouping === "spec" ? "is-active" : ""} type="button" onClick={() => setGrouping("spec")}>By requirement</button>
        </div>
        <button className="oi-icon-button" type="button" title="Recalculate time" disabled={acting !== null} onClick={() => void calculate("draft")}><RefreshCw className={acting === "draft" ? "spin" : ""} size={16} /></button>
      </div>

      <div className="oi-time-context">
        <div><CalendarDays size={18} /><span><strong>{draft?.project.name ?? workspaceName}</strong><small>{since} to {until}</small></span></div>
        <div><ShieldCheck size={18} /><span><strong>Account delivery</strong><small>{health ? (health.pending_total ? health.pending_total + " pending across all workspaces" : "All signed records delivered") : "Local records remain available"}</small></span></div>
      </div>

      <div className="oi-metric-band oi-time-metrics">
        <div><span>Estimated hours</span><strong>{totals.hours.toFixed(2)}</strong></div>
        <div><span>Governed changes</span><strong>{totals.sessions}</strong></div>
        <div><span>Governed operations</span><strong>{totals.ops}</strong></div>
        <div><span>File touches</span><strong>{totals.files}</strong></div>
      </div>

      <div className="oi-action-row oi-time-actions">
        <button className="oi-button oi-button-primary" type="button" disabled={acting !== null} onClick={() => void calculate("draft")}><Clock3 size={15} />Calculate</button>
        <button className="oi-button oi-button-secondary" type="button" disabled={acting !== null || !draft} onClick={() => void calculate("verify")}><ShieldCheck size={15} />Verify records</button>
        <button className="oi-button oi-button-secondary" type="button" disabled={!draft} onClick={() => draft && downloadTimesheetCsv(draft)}><Download size={15} />Export CSV</button>
      </div>

      {acting ? <div className="oi-progress" role="status"><LoaderCircle className="spin" size={15} />{acting === "verify" ? "Verifying signed records…" : "Calculating project time…"}</div> : null}
      {verification ? <div className={"oi-alert " + (verification.integrity_status === "drifted" ? "is-error" : verification.signature_status === "complete" ? "is-good" : "")}><ShieldCheck size={15} /><span><strong>{verification.integrity_status === "matched" ? "Recorded volumes match" : "Recorded volumes changed"}</strong><small>{verification.summary} {verification.next_action}</small></span></div> : null}
      {draft?.warnings.includes("line_volume_unavailable") ? <div className="oi-alert"><AlertTriangle size={15} />Some older records do not contain line-volume counters.</div> : null}

      {visibleGroups.length ? (
        <div className="oi-time-groups">
          {visibleGroups.map((group, index) => (
            <div key={group.key.join("/") + index}>
              <span><strong>{group.key.join(" · ") || "No requirement"}</strong><small>{group.ops} governed operations · {group.files_touched} file touches</small></span>
              <strong>{group.hours.toFixed(2)} h</strong>
            </div>
          ))}
        </div>
      ) : !acting ? <div className="oi-empty"><Clock3 size={28} /><strong>No governed time in this period</strong><span>Choose another range or complete a protected change.</span></div> : null}
      {draft && draft.groups.length > visibleGroups.length ? <p className="oi-disclaimer">Showing the first {visibleGroups.length} of {draft.groups.length} canonical groups. Narrow the period for full detail.</p> : null}
      {draft ? <p className="oi-disclaimer">{draft.disclaimer} Verify record integrity before relying on this draft. Draft time is never accepted automatically.</p> : null}
      {error ? <div className="oi-alert is-error" role="alert"><AlertTriangle size={15} />{error}</div> : null}
    </section>
  );
}
