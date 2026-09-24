# RFP-024 — APatch Studio OSS result delivery to TrustChain Cowork

Status: accepted for implementation  
Owner: Ed Cherednik  
Products: APatch Studio OSS, APatch OSS, TrustChain Cowork

## Problem

Cowork can issue a signed ProjectWorkItem and Studio can accept it into an exact
local APatch Change, but the performer cannot finish the journey in Studio. The
current product stops after local execution. Returning the result requires manual
API work and copying hashes and evidence identifiers, so the visible OSS product
does not yet support the promised issue → accept → execute → submit → review loop.

## User journey

A performer opens the signed assignment in the local Studio Inbox, accepts it and
executes its existing SPEC. After the local work is ready, the same assignment card
lets the performer choose one workspace-relative result file and prepare a
submission. Studio shows exactly what will be disclosed: the result hash and size,
the APatch evidence-bundle hash, claimed active time, destination project and task.
It explicitly states that source, diff, prompt, runner output, file bytes, local
absolute paths, credentials and keys are not sent.

The performer confirms the exact frozen plan. Studio then publishes the already
previewed APatch evidence, obtains the Platform admission acknowledgement, creates
a WorkRelease bound to the exact task/program/version, and submits that release for
review. Cowork remains the place where the customer accepts or rejects it. Studio
shows a receipt and can replay safely after a lost response.

## Boundaries

- No form asks a person to paste an outcome hash, evidence bundle id, release id or
  server token.
- Preparing a submission may create local signed APatch evidence, but it makes no
  network mutation.
- Submitting is the only network-mutating action and requires
  `submit:<plan_hash>` confirmation over a freshly recomputed plan.
- The result file must be a regular, non-symlink file inside the selected workspace
  and is never uploaded by this protocol; only its hash and byte count are shared.
- The APatch workspace signing key signs every Platform request. Browser cookies,
  bearer-only calls and a different machine key are not authority.
- Performer authority ends at `submitted`. Review, work completion, accepted time,
  Avatar claims, ownership and economics remain independent Cowork decisions.
- Durable local state stores hashes and the bounded WorkRelease receipt, never file
  contents or a local path.

## Failure and recovery

A Platform outage leaves the preview and all source local. A failed evidence
admission or WorkRelease command fails closed and can be retried with the same
idempotency keys. A changed file, task pin, connection generation, evidence bundle
or publication plan invalidates the confirmation and requires a new preview.

## Acceptance

| ID | Requirement | Priority |
| --- | --- | --- |
| SDR-1 | Studio accepts only a bounded workspace-relative regular result file, derives its SHA-256 and size locally, builds exact APatch evidence for the accepted source binding, and performs no network mutation during preview | MUST |
| SDR-2 | The preview is a closed canonical disclosure plan bound to the exact intent, task/program/version, connection generation, result hash, evidence bundle and claimed time; submit requires `submit:<plan_hash>` and recomputes the plan before any Platform mutation | MUST |
| SDR-3 | Submission uses the same enrolled APatch key to publish and acknowledge the previewed evidence, then invoke the signed Platform create and submit commands with server-derived evidence and independent idempotency keys | MUST |
| SDR-4 | Exact retries are safe, and durable local state contains only the plan/result/evidence hashes plus bounded draft/submitted receipt identifiers and states—never result bytes, local paths, prompts, source, credentials or review capability | MUST |
| SDR-5 | The Inbox visibly exposes Prepare submission, the exact disclosure preview, Submit to Cowork and the final receipt for a source-bound consumed assignment; it exposes no manual hash/id fields and the performer cannot accept/reject or complete work from Studio | MUST |
