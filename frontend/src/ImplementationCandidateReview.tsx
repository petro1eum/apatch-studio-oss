import { useState } from "react";
import { approveImplementationCandidate, loadImplementationCandidate } from "./api";

export type ImplementationReview = {
  status: "not_selected" | "awaiting_approval" | "activated";
  snapshot?: string;
  functional_acceptance: false;
  review?: {
    objective?: string;
    candidate_path: string;
    candidate_hash: string;
    contract_hash: string;
    release_hash: string;
    previous_grant_hash: string;
    judge_assets: Record<string, string>;
    task_envelopes: Record<string, {
      allowed_reads?: string[]; allowed_writes?: string[]; forbidden_paths?: string[];
      tools?: string[]; commands?: string[][]; budgets?: Record<string, number>;
      network?: string[]; services?: string[]; remote?: string[];
      allowed_symbols?: string[]; checks?: string[]; containment?: string; rollback_owner?: string;
    }>;
    obligations: { acceptance_id: string; oracle: string; command: string[]; perspectives?: string[]; baseline?: {kind?: string; result_hash?: string}; falsification?: {kind?: string; expected?: string; target_path?: string} }[];
  };
};

export function ImplementationCandidateReview({ specId, requirementId }: { specId: string; requirementId: string }) {
  const [state, setState] = useState<ImplementationReview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function review() {
    setBusy(true); setError(null);
    try { setState(await loadImplementationCandidate(specId, requirementId)); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "Candidate review unavailable."); }
    finally { setBusy(false); }
  }
  async function approve() {
    if (!state?.snapshot || busy) return;
    setBusy(true); setError(null);
    try { setState(await approveImplementationCandidate(specId, requirementId, state.snapshot)); }
    catch (failure) { setState(null); setError(failure instanceof Error ? failure.message : "Review the candidate again before confirming."); }
    finally { setBusy(false); }
  }
  const candidate = state?.review;
  return <section className="oi-contract-review" aria-label="Versioned implementation amendment">
    <h3>Review the implementation amendment</h3>
    <p>Approve the prepared tests and exact implementation boundaries. The previous contract and its checks remain recorded. This approval authorizes implementation; it does not mean the feature passed its tests.</p>
    <button className="oi-button oi-button-secondary" type="button" disabled={busy} onClick={() => void review()}>Review selected candidate</button>
    {state?.status === "not_selected" ? <p>A valid implementation candidate has not been selected yet.</p> : null}
    {candidate ? <>
      <h4>{candidate.objective ?? "Exact selected candidate"}</h4><p><code>{candidate.candidate_path}</code></p>
      {Object.entries(candidate.task_envelopes).map(([requirement, envelope]) => <section key={requirement}>
        <h4>{requirement}</h4>
        <p>Allowed reads: {(envelope.allowed_reads ?? []).join(", ")}</p>
        <p>Allowed changes: {(envelope.allowed_writes ?? []).join(", ")}</p>
        <p>Forbidden: {(envelope.forbidden_paths ?? []).join(", ")}</p>
        <p>Allowed symbols: {(envelope.allowed_symbols ?? []).join(", ") || "None listed"}</p>
        <p>Tools: {(envelope.tools ?? []).join(", ")}</p>
        <p>Limits: {JSON.stringify(envelope.budgets ?? {})}</p>
        <p>Network: {(envelope.network ?? []).join(", ") || "None"}; services: {(envelope.services ?? []).join(", ") || "None"}; remote: {(envelope.remote ?? []).join(", ") || "None"}.</p>
        <p>Required checks: {(envelope.checks ?? []).join(", ")}. Containment: {envelope.containment}. Rollback owner: {envelope.rollback_owner}.</p>
        <ul>{(envelope.commands ?? []).map((command, index) => <li key={index}><code>{JSON.stringify(command)}</code></li>)}</ul>
      </section>)}
      <h4>Required checks, including preserved baseline</h4><ul>{candidate.obligations.map(item => <li key={item.acceptance_id}>{item.acceptance_id}: {item.oracle}<br /><code>{JSON.stringify(item.command)}</code><p>Perspectives: {(item.perspectives ?? []).join(", ")}. Baseline evidence: {item.baseline?.kind} ({item.baseline?.result_hash}). Falsification: {item.falsification?.kind}; expected {item.falsification?.expected}; target {item.falsification?.target_path}.</p></li>)}</ul>
      <details><summary>Exact input fingerprints</summary><p>Review: {state?.snapshot}</p><p>Candidate: {candidate.candidate_hash}</p><p>Previous contract: {candidate.contract_hash}</p><p>Release: {candidate.release_hash}</p><p>Preparation grant: {candidate.previous_grant_hash}</p>{Object.entries(candidate.judge_assets).map(([path, hash]) => <p key={path}>{path}: {hash}</p>)}</details>
      {state?.status === "awaiting_approval" ? <button className="oi-button oi-button-primary" type="button" disabled={busy} onClick={() => void approve()}>Approve this implementation amendment</button> : <p>Successor contract activated. Functional verification is still required.</p>}
    </> : null}
    {error ? <p role="alert">{error}</p> : null}
  </section>;
}
