import { useState } from "react";
import { approveAuthoringScope, loadAuthoringScope } from "./api";

export type AuthoringReview = {
  status: "not_prepared" | "awaiting_approval" | "approved";
  snapshot?: string;
  grant_hash?: string;
  functional_acceptance: false;
  scope?: {
    actor_id: string;
    files: string[];
    effects: string[];
    max_bytes: number;
    commands: string[][];
    contract_hash: string;
    release_hash: string;
    judge_assets: Record<string, string>;
    before_hashes?: Record<string, string>;
    previous_grant_hash?: string;
    previous_preparation_hash?: string;
  };
};

export function AuthoringScopeReview({ specId, requirementId }: { specId: string; requirementId: string }) {
  const [review, setReview] = useState<AuthoringReview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function open() {
    setBusy(true); setError(null);
    try { setReview(await loadAuthoringScope(specId, requirementId)); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "Preparation scope is unavailable."); }
    finally { setBusy(false); }
  }
  async function approve() {
    if (!review?.snapshot || busy) return;
    setBusy(true); setError(null);
    try { setReview(await approveAuthoringScope(specId, requirementId, review.snapshot)); }
    catch (failure) {
      setReview(null);
      setError(failure instanceof Error ? failure.message : "Approval could not complete. Review the scope again.");
    } finally { setBusy(false); }
  }
  const scope = review?.scope;
  return <section aria-label="Test preparation scope" className="oi-contract-review">
    <h3>Prepare new tests after the release</h3>
    <p>Releasing a boundary does not authorize new work. Review the exact preparation scope before approving it. Existing checks and application code remain protected. This approval does not accept a feature or authorize implementation.</p>
    <button type="button" className="oi-button oi-button-secondary" disabled={busy} onClick={() => void open()}>Review preparation scope</button>
    {review?.status === "not_prepared" ? <p>The agent has not proposed exact new files yet.</p> : null}
    {scope ? <>
      <h4>{scope.previous_grant_hash ? "Preparation files to revise" : "New files to create"}</h4><ul>{scope.files.map(path => <li key={path}><code>{path}</code>{scope.before_hashes?.[path] ? <span> — existing content: {scope.before_hashes[path]}</span> : null}</li>)}</ul>
      <p>Operations: {scope.effects.join(", ")}. Maximum bytes: {scope.max_bytes}. Actor: {scope.actor_id}.</p>
      <h4>Allowed preparation checks</h4><ul>{scope.commands.map((command, index) => <li key={index}><code>{JSON.stringify(command)}</code></li>)}</ul>
      <h4>Existing checks preserved</h4><ul>{Object.keys(scope.judge_assets).map(path => <li key={path}><code>{path}</code></li>)}</ul>
      {scope.previous_grant_hash ? <p>Revision of completed preparation {scope.previous_grant_hash}. Prior evidence: {scope.previous_preparation_hash}. Only the exact existing contents listed above may be replaced.</p> : null}
      <details><summary>Exact scope fingerprints</summary><p>Scope: {review?.snapshot}</p><p>Original contract: {scope.contract_hash}</p><p>Release: {scope.release_hash}</p>{Object.entries(scope.judge_assets).map(([path, hash]) => <p key={path}>{path}: {hash}</p>)}</details>
      {review?.status === "awaiting_approval" ? <button type="button" className="oi-button oi-button-primary" disabled={busy} onClick={() => void approve()}>Approve this preparation scope</button> : <p>Preparation approved. Functional acceptance remains pending.</p>}
    </> : null}
    {error ? <p role="alert">{error}</p> : null}
  </section>;
}
