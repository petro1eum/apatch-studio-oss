import { Check, ChevronDown, History, RotateCcw, ShieldCheck } from "lucide-react";

import type { ImportedChange } from "./types";


function short(value: string | null) {
  if (!value) return "Not recorded";
  return value.length > 24 ? value.slice(0, 12) + "…" + value.slice(-8) : value;
}

function humanTitle(value: string) {
  const withoutAnchor = value.replace(/^SPEC-[A-Z0-9-]+#(?:R|FR|NFR)[A-Z0-9-]*:\s*/i, "").trim();
  return withoutAnchor || "Verified project change";
}

function humanSpecTitle(value: string) {
  const withoutAnchor = value.replace(/^SPEC-[A-Z0-9-]+\s*(?:--|—|:)\s*/i, "").trim();
  return withoutAnchor || "Verified project change";
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function deltaLabel(change: ImportedChange) {
  return [
    change.file_count + (change.file_count === 1 ? " file" : " files"),
    "+" + Math.max(0, change.insertions),
    "−" + Math.max(0, change.deletions),
  ].join(" · ");
}

export function ImportedChangeCard({
  change,
  expanded,
  onToggle,
  resultTitle,
  groupSize,
}: {
  change: ImportedChange;
  expanded: boolean;
  onToggle: () => void;
  resultTitle?: string;
  groupSize?: number;
}) {
  const proven = change.status === "proven";
  const rolledBack = change.status === "rolled_back";
  const label = proven ? "Verified" : rolledBack ? "Rolled back" : "Recorded";
  const tone = proven ? "success" : rolledBack ? "warning" : "neutral";
  const StatusIcon = proven ? Check : rolledBack ? RotateCcw : History;
  const grouped = (groupSize ?? 1) > 1;
  const title = resultTitle ? humanSpecTitle(resultTitle) : humanTitle(change.objective);
  const resultMeta = grouped
    ? `${groupSize} verified steps · latest ${deltaLabel(change)}`
    : deltaLabel(change);

  return (
    <article className={"oi-change-card oi-imported-change " + (expanded ? "is-open" : "")}>
      <div className="oi-change-main">
        <button className="oi-change-open" type="button" onClick={onToggle} aria-expanded={expanded}>
          <span className={"oi-status-icon tone-" + tone}><StatusIcon size={18} /></span>
          <span className="oi-change-copy">
            <strong>{title}</strong>
            <span>{formatDate(change.updated_at)} · {resultMeta}</span>
          </span>
        </button>
        <div className="oi-change-badges">
          <span className={"oi-badge tone-" + tone}>{label}</span>
        </div>
        <button className="oi-button oi-button-primary oi-next-action" type="button" onClick={onToggle}>
          <ChevronDown size={15} />Open result
        </button>
      </div>

      {expanded ? (
        <div className="oi-change-detail">
          <div className="oi-change-summary">
            <div><span>{grouped ? "Latest verified step" : "Result"}</span><strong>{deltaLabel(change)}</strong></div>
            {grouped ? <div><span>Verified steps</span><strong>{groupSize}</strong></div> : null}
            <div><span>Area</span><strong>{change.logical_areas.length ? change.logical_areas.join(", ") : "Not retained"}</strong></div>
            <div><span>Verification</span><strong>{change.attestation_count ? "Signed proof available" : "Recorded locally"}</strong></div>
          </div>
          <div className="oi-scope-report is-protected">
            <ShieldCheck size={17} />
            <span>This result comes from signed project history. Actions from the original run are no longer available.</span>
          </div>
          <details className="oi-proof">
            <summary><ShieldCheck size={16} />Proof</summary>
            <div className="oi-proof-grid">
              <div><span>Technical anchor</span><strong>{change.spec_id && change.requirement_id ? change.spec_id + "#" + change.requirement_id : "Change-level proof"}</strong></div>
              <div><span>Protected run</span><strong>{short(change.governed_session_id)}</strong></div>
              <div><span>Signed records</span><strong>{change.signed_event_count}</strong></div>
              <div><span>Recorded mutations</span><strong>{change.mutation_count}</strong></div>
              <div><span>Proof records</span><strong>{change.attestation_count}</strong></div>
              <div><span>Latest record</span><strong>{short(change.latest_record_id)}</strong></div>
              <div><span>Signed by</span><strong>{short(change.latest_signer)}</strong></div>
            </div>
          </details>
        </div>
      ) : null}
    </article>
  );
}
