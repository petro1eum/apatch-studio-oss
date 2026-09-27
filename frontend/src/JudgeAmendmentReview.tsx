import { useState } from "react";
import { approveJudgeAmendment, loadJudgeAmendment } from "./api";

export type JudgeReview = {
  status: "not_proposed" | "awaiting_approval" | "activated";
  snapshot?: string;
  review?: {
    reason: string; judge_path: string; contract_hash: string;
    old_judge_hash: string; new_judge_hash: string; diff: string;
    invalidated_acceptance_ids: string[]; affected_requirements: string[];
    preserved_acceptance_ids: string[];
    new_obligation: { acceptance_id: string; oracle: string; command: string[]; perspectives: string[]; baseline: unknown; falsification: unknown };
  };
};
export function JudgeAmendmentReview({specId, requirementId}: {specId: string; requirementId: string}) {
  const [state, setState] = useState<JudgeReview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function review() {
    setBusy(true); setError(null);
    try { setState(await loadJudgeAmendment(specId, requirementId)); }
    catch (failure) { setState(null); setError(failure instanceof Error ? failure.message : "Review unavailable."); }
    finally { setBusy(false); }
  }
  async function approve() {
    if (!state?.snapshot || busy) return;
    setBusy(true); setError(null);
    try { setState(await approveJudgeAmendment(specId, requirementId, state.snapshot)); }
    catch (failure) { setState(null); setError(failure instanceof Error ? failure.message : "Review the current correction again."); }
    finally { setBusy(false); }
  }
  const correction = state?.review;
  return <section className="oi-contract-review" aria-label="Exact verification correction">
    <h3>Review a correction to verification</h3>
    <p>The original test and agreement stay in history. Only the reviewed correction is applied. Affected results must be verified again.</p>
    <button type="button" className="oi-button oi-button-secondary" disabled={busy} onClick={() => void review()}>Review proposed correction</button>
    {state?.status === "not_proposed" ? <p>No correction has been proposed.</p> : null}
    {correction ? <>
      <p>{correction.reason}</p><p>{correction.judge_path}</p>
      <p>Checks requiring verification again: {correction.invalidated_acceptance_ids.join(", ")}.</p>
      <p>Affected requirements: {correction.affected_requirements.join(", ")}.</p>
      <p>Preserved checks: {correction.preserved_acceptance_ids.join(", ")}.</p>
      <pre aria-label="Exact old and new test difference">{correction.diff}</pre>
      <details><summary>Replacement verification obligation</summary><p>{correction.new_obligation.acceptance_id}: {correction.new_obligation.oracle}</p><p>Perspectives: {correction.new_obligation.perspectives.join(", ")}</p><pre>{JSON.stringify(correction.new_obligation.command)}</pre><p>Baseline: {JSON.stringify(correction.new_obligation.baseline)}</p><p>Falsification: {JSON.stringify(correction.new_obligation.falsification)}</p></details>
      <details><summary>Exact versions</summary>
        <p>Current agreement: {correction.contract_hash}</p>
        <p>Original test: {correction.old_judge_hash}</p>
        <p>Replacement test: {correction.new_judge_hash}</p>
        <p>Reviewed proposal: {state?.snapshot}</p>
      </details>
      {state?.status === "awaiting_approval"
        ? <button type="button" className="oi-button oi-button-primary" disabled={busy} onClick={() => void approve()}>Approve this exact correction</button>
        : <p>Correction recorded. This does not mark the feature as verified.</p>}
    </> : null}
    {error ? <p role="alert">{error}</p> : null}
  </section>;
}
