import { useEffect, useState } from "react";
import { approveDraftRepair, loadDraftRepair, proposeDraftRepair } from "./api";

export type DraftRepair = {
  status: "not_prepared" | "awaiting_approval" | "completed";
  snapshot?: string;
  review?: {
    run_id: string; spec_id: string; reason: string;
    files: Array<{ path: string; before_hash: string | null; after_hash: string; before_content: string | null; content: string }>;
  };
  functional_acceptance: false;
};

export function DraftRepairReview({ runId, onChanged }: { runId: string; onChanged: () => void }) {
  const [review, setReview] = useState<DraftRepair | null>(null);
  const [files, setFiles] = useState<Array<{ path: string; content: string }> | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [generation, setGeneration] = useState(0);
  useEffect(() => {
    let active = true;
    setReview(null); setConfirmed(false);
    void loadDraftRepair(runId).then(value => { if (active) setReview(value); })
      .catch(e => { if (active) setError(String(e.message ?? e)); });
    return () => { active = false; };
  }, [runId, generation]);

  async function upload(file: File | undefined) {
    setError(null); setConfirmed(false); setFiles(null);
    if (!file) return;
    try {
      if (file.size > 1048576) throw new Error("The repair package must be smaller than 1 MB.");
      const value: unknown = JSON.parse(await file.text());
      if (!Array.isArray(value) || !value.length || value.length > 64 ||
          value.some(item => typeof item !== "object" || item === null ||
            typeof item.path !== "string" || typeof item.content !== "string")) {
        throw new Error("Upload an array of exact {path, content} replacements prepared by your agent.");
      }
      setFiles(value);
    } catch (e) { setError(e instanceof Error ? e.message : "Invalid repair package"); }
  }

  async function propose() {
    if (!files || busy) return;
    setBusy(true); setError(null); setConfirmed(false);
    try { setReview(await proposeDraftRepair(runId, reason, files)); }
    catch (e) { setError(e instanceof Error ? e.message : "Cannot prepare this repair"); }
    finally { setBusy(false); }
  }

  async function approve() {
    if (!review?.snapshot || !confirmed || busy) return;
    setBusy(true); setError(null);
    try {
      await approveDraftRepair(runId, review.snapshot);
      setGeneration(value => value + 1); onChanged();
    } catch (e) {
      setConfirmed(false);
      setError(e instanceof Error ? e.message : "Repair has not completed; retry the same reviewed snapshot.");
    } finally { setBusy(false); }
  }

  return <section className="oi-sdd-section" aria-labelledby="draft-repair-title">
    <h2 id="draft-repair-title">Prepare or repair this contract</h2>
    <p>Create the missing contract or repair its draft under the same change. Existing signed contracts remain protected. This action prepares files only; it does not approve implementation.</p>
    {error ? <p role="alert">{error}</p> : null}
    {review?.status === "completed" ? <p role="status">Draft preparation is recorded. Review and freeze its scope and tests separately before implementation.</p> : <>
      <details><summary>Review a preparation package</summary>
        <p>Ask your agent for a JSON array of exact path/content replacements. Only this draft's approved preparation files can change.</p>
        <label>Replacement files <input type="file" accept="application/json,.json" disabled={busy} onChange={e => void upload(e.target.files?.[0])} /></label>
        <label>Reason <textarea value={reason} maxLength={2000} disabled={busy} onChange={e => { setReason(e.target.value); setConfirmed(false); }} /></label>
        <button type="button" className="oi-button oi-button-secondary" disabled={busy || !files || reason.trim().length < 8} onClick={() => void propose()}>Review exact changes</button>
      </details>
      {review?.review ? <>
        <p><strong>{review.review.spec_id}</strong> · {review.review.reason}</p>
        {review.review.files.map(file => <details key={file.path}>
          <summary>{file.before_hash ? "Replace" : "Create"}: {file.path}</summary>
          <p>Before: <code>{file.before_hash ?? "Absent"}</code></p>
          <pre>{file.before_content ?? "New file"}</pre>
          <p>After: <code>{file.after_hash}</code></p><pre>{file.content}</pre>
        </details>)}
        <label><input type="checkbox" checked={confirmed} disabled={busy} onChange={e => setConfirmed(e.target.checked)} /> I approve these exact preparation changes, not implementation.</label>
        <button type="button" className="oi-button oi-button-primary" disabled={busy || !confirmed} onClick={() => void approve()}>{busy ? "Applying reviewed repair…" : "Approve preparation"}</button>
      </> : null}
    </>}
  </section>;
}
