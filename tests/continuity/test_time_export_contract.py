from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

_NODE_EXPORT = r"""
import { timesheetDraftToCsv } from "./frontend/src/timesheetCsv.ts";

const csv = timesheetDraftToCsv({
  schema: "apatch.studio.timesheet-draft.v1",
  request_id: "apsreq_export_contract_001",
  source: "apatch.run_timesheet",
  project: { id: "project_123", name: 'Client, "Alpha"' },
  period: { since: "2026-08-25", until: "2026-08-31" },
  basis: "operation_spacing_estimate",
  accepted_time: false,
  group_by: ["day"],
  groups: [{
    key: ["2026-08-31"],
    sessions: 2,
    hours: 1.5,
    active_sec: 5400,
    ops: 7,
    files_touched: 3,
    insertions: 11,
    deletions: 4,
  }],
  warnings: [],
  disclaimer: "Estimate only.",
});
process.stdout.write(JSON.stringify(csv));
"""


def test_csv_serializes_the_displayed_canonical_draft() -> None:
    completed = subprocess.run(
        ["node", "--experimental-strip-types", "--input-type=module", "-e", _NODE_EXPORT],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    csv = json.loads(completed.stdout)

    assert 'project,"Client, ""Alpha"""' in csv
    assert "project_id,project_123" in csv
    assert "period_since,2026-08-25" in csv
    assert "period_until,2026-08-31" in csv
    assert "estimate_basis,operation_spacing_estimate" in csv
    assert "accepted_time,false" in csv
    assert "2026-08-31,2,1.5,5400,7,3,11,4" in csv


def test_export_is_local_only_and_cannot_accept_or_deliver_time() -> None:
    source = (ROOT / "frontend/src/timesheetCsv.ts").read_text(encoding="utf-8")

    for local_operation in ("new Blob", "URL.createObjectURL", 'document.createElement("a")', "anchor.click()"):
        assert local_operation in source
    for forbidden in ("fetch(", "request(", "runTimesheet(", "loadContributionHealth(", "accepted_time: true"):
        assert forbidden not in source
