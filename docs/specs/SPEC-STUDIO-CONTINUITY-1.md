# SPEC-STUDIO-CONTINUITY-1 -- Existing APatch Work and Verified Time

> **apatch artifact:** `spec:SPEC-STUDIO-CONTINUITY-1`
> **Anchors:** RFP-008
> **Implementation state:** R0 freezes traceability. R1-R8 require executable product proof.

## R0 RFP traceability gate

| RFP id | SPEC Rk | Disposition |
|--------|---------|-------------|
| CONT-1 | R1 | covered |
| CONT-2 | R2 | covered |
| CONT-3 | R3 | covered |
| CONT-4 | R4 | covered |
| CONT-5 | R5 | covered |
| CONT-6 | R6 | covered |
| CONT-7 | R7 | covered |
| CONT-8 | R8 | covered |

(verify: python3 -m pytest tests/test_studio_continuity_contract.py -q)

## R1 Canonical signed-session projection

The adapter groups exact APatch ledger records by governed session id and emits a
bounded content-safe imported-change projection with intent, time, requirement,
safe delta counts, mutation count, attestation count and derived proof state.

(verify: python3 -m pytest tests/continuity/test_ledger_change_projection.py -q)

## R2 Unified feed ordering and deduplication

Home merges durable Studio runs and imported changes by descending activity time.
A Studio run with an exact governed session id replaces its imported counterpart
without copying ledger truth into the runner journal.

(verify: python3 -m pytest tests/continuity/test_unified_change_feed.py -q)

## R3 Honest imported change cards

Imported cards use product language, show only supported proof and safe delta
fields, and expose no retry, review-note, rollback, delivery, source, path or full
diff action that Studio cannot honestly reconstruct.

(verify: python3 -m pytest tests/continuity/test_imported_change_cards.py -q)

## R4 Existing-work first-run continuity

The one-action first-run state appears only when both Studio runs and imported
signed changes are empty. An established APatch workspace opens with its signed
work visible immediately.

(verify: python3 -m pytest tests/continuity/test_existing_workspace_journey.py -q)

## R5 Workspace and period scoped time

Timesheet draft and verification call canonical APatch `run_timesheet` with the
selected project's stable id. The UI defaults to the last seven calendar days and
supports seven-day, thirty-day and valid custom ranges.

(verify: python3 -m pytest tests/continuity/test_timesheet_scope.py -q)

## R6 Useful time summary and grouping

The Time surface presents total estimated hours, governed changes, operations and
files before bounded rows, and supports grouping by day or requirement without a
second ContributionEvent aggregation.

(verify: python3 -m pytest tests/continuity/test_time_workflow.py -q)

## R7 Local canonical CSV export

Export serializes only the currently displayed canonical draft, includes its
estimate basis and accepted-time=false marker, and performs no network delivery or
authority decision.

(verify: python3 -m pytest tests/continuity/test_time_export_contract.py -q)

## R8 Continuity release proof

Focused continuity tests, the complete Python suite, production frontend build,
and desktop/mobile browser QA prove existing-work continuity and usable verified
time without weakening RFP-006 or RFP-007.

(verify: python3 -m pytest tests/continuity/test_continuity_journey.py -q)
