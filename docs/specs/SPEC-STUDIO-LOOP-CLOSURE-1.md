# SPEC-STUDIO-LOOP-CLOSURE-1 -- APatch Studio Product Loop Closure

> **apatch artifact:** `spec:SPEC-STUDIO-LOOP-CLOSURE-1`
> **Anchors:** RFP-006
> **Implementation state:** R0 defines the executable contract. R1-R7 remain pending until their named product and interaction tests pass.

## R0 RFP traceability gate

Every mandatory RFP-006 acceptance outcome maps exactly once to an executable
requirement. This gate proves the contract shape and privacy boundary; it does
not claim that the product loop is already closed.

| RFP id | SPEC Rk | Disposition |
|--------|---------|-------------|
| LOOP-1 | R1 | covered |
| LOOP-2 | R2 | covered |
| LOOP-3 | R3 | covered |
| LOOP-4 | R4 | covered |
| LOOP-5 | R5 | covered |
| LOOP-6 | R6 | covered |
| LOOP-7 | R7 | covered |

(verify: python3 -m pytest tests/test_studio_loop_closure_contract.py -q)

## R1 Canonical file-drift status

Build every Studio specification row and workspace requirement total from one
file-drift-aware APatch coverage snapshot. Reuse one ledger read per refresh.
When coverage is unavailable, expose attention or unavailable state instead of
zero. Rebind and stale actions must consume the same requirement ids shown by
the summary.

(verify: python3 -m pytest tests/closure/test_stale_projection.py -q)

## R2 Work hygiene recovery

When canonical hygiene is degraded or critical, Work must expose preview and
explicitly confirmed safe cleanup without sending the user to another tab.
Refresh the overview after completion and show bounded deletion and reclaimed
byte counts. Clean workspaces show no false warning.

(verify: python3 -m pytest tests/closure/test_overview_hygiene.py -q)

## R3 Private local review handoff

Persist bounded reviewer notes and a content-safe phase timeline in the
owner-only run journal. Open the full local diff through a fixed-purpose
owner-only temporary artifact and allowlisted local launcher. HTTP responses
must contain neither source, paths, raw diff nor runner transcript.

(verify: python3 -m pytest tests/closure/test_local_review_handoff.py -q)

## R4 Governed Git delivery

Expose safe delivery status plus Commit staged changes, Push current branch and
Open pull request actions. Commit only an already staged set after APatch staged
notarization. Never auto-stage, force-push, accept arbitrary remote/ref/argv or
return repository URLs and paths. External effects require Studio confirmation.

(verify: python3 -m pytest tests/closure/test_delivery_workflow.py -q)

## R5 Optional signed Cowork Inbox

Expose Inbox only with explicit issuer trust. Verify a signed proposal before
preview, keep import inert, require explicit binding to a local SPEC, and preserve
decline, expiry and replay outcomes. Local workflows remain usable during Cowork
outage or when Cowork is not configured.

(verify: python3 -m pytest tests/actionable/test_inbox_workflow.py -q)

## R6 Canonical contribution and timesheet workflow

Render the local draft from APatch `run_timesheet` or its byte-equivalent MCP
operation; Studio must not aggregate ContributionEvent into a second truth. Let
the user request canonical verification and group by project, specification and
day. Label hours as operation-spacing estimates, not stopwatch, payroll or
accepted time.

Review exposes only allowlisted `contribution_receipt` and `avatar_sync`
fields from attestation, including `AVATAR_CONTRACT_UNAVAILABLE` and retryable
delivery failures. Admin exposes content-safe pending outbox, last acknowledgement
and Tracker availability. Missing providers never disable the local draft.

(verify: python3 -m pytest tests/closure/test_contribution_workflow.py -q)

## R7 Closed-loop release proof

Prove the complete local journey through focused backend and frontend
interaction tests, the full Python suite, production frontend build and desktop
and mobile browser QA. Compilation or label presence alone is insufficient.
The proof must cover stale attention, cleanup confirmation, local review,
delivery, contribution visibility and the optional signed Inbox.

(verify: python3 -m pytest tests/closure/test_loop_closure_journey.py -q)
