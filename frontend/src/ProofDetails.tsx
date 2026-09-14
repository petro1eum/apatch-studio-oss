import { FileCode2, ShieldCheck } from "lucide-react";

import type { AgentRun } from "./types";

function short(value: string | null | undefined) {
  if (!value) return "Not recorded";
  return value.length > 24 ? value.slice(0, 12) + "…" + value.slice(-8) : value;
}

export function ProofDetails({
  run,
  onOpenLocalReview,
  opening,
}: {
  run: AgentRun;
  onOpenLocalReview: () => void;
  opening: boolean;
}) {
  const receipt = run.contribution?.contribution_receipt;
  return (
    <details className="oi-proof">
      <summary><ShieldCheck size={16} />Proof</summary>
      <div className="oi-proof-grid">
        <div><span>Requirement</span><strong>{run.work_ref.spec_id && run.work_ref.requirement_id ? run.work_ref.spec_id + " / " + run.work_ref.requirement_id : "Change-level proof"}</strong></div>
        <div><span>Protected run</span><strong>{short(run.work_ref.governed_session_id)}</strong></div>
        <div><span>Local agent run</span><strong>{short(run.run_id)}</strong></div>
        <div><span>Record</span><strong>{short(receipt?.event_id)}</strong></div>
        <div><span>Events observed</span><strong>{run.event_count}</strong></div>
        <div><span>Delivery</span><strong>{receipt?.status ?? run.contribution?.avatar_sync?.status ?? "Local only"}</strong></div>
      </div>
      <button className="oi-button oi-button-secondary" type="button" disabled={opening} onClick={onOpenLocalReview}>
        <FileCode2 size={15} />{opening ? "Opening…" : "Open local diff"}
      </button>
    </details>
  );
}
