import type { TimesheetDraft } from "./types";


function cell(value: string | number | boolean | null) {
  const text = String(value ?? "");
  return /[",\n]/.test(text) ? '"' + text.replaceAll('"', '""') + '"' : text;
}

export function timesheetDraftToCsv(draft: TimesheetDraft) {
  const dimensions = draft.group_by;
  const rows: Array<Array<string | number | boolean | null>> = [
    ["APatch Studio verified time draft"],
    ["project", draft.project.name],
    ["project_id", draft.project.id],
    ["period_since", draft.period.since],
    ["period_until", draft.period.until],
    ["estimate_basis", draft.basis],
    ["accepted_time", draft.accepted_time],
    [],
    [...dimensions, "sessions", "hours", "active_sec", "ops", "files_touched", "insertions", "deletions"],
    ...draft.groups.map((group) => [
      ...dimensions.map((_dimension, index) => group.key[index] ?? ""),
      group.sessions,
      group.hours,
      group.active_sec,
      group.ops,
      group.files_touched,
      group.insertions,
      group.deletions,
    ]),
  ];
  return rows.map((row) => row.map(cell).join(",")).join("\n") + "\n";
}

export function downloadTimesheetCsv(draft: TimesheetDraft) {
  const csv = timesheetDraftToCsv(draft);
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "apatch-time-" + (draft.period.until ?? "draft") + ".csv";
  anchor.click();
  URL.revokeObjectURL(url);
}
