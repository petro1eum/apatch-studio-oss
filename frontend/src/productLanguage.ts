import type { AgentRun, Specification } from "./types";

export type ProductTone = "neutral" | "info" | "success" | "warning" | "danger";

export interface ProductState {
  label: string;
  tone: ProductTone;
}

export function changeState(run: AgentRun): ProductState {
  if (run.status === "succeeded" && run.plan_handoff) {
    return { label: "Plan ready", tone: "info" };
  }
  if (run.status === "succeeded" && run.mode === "new_change") {
    return { label: "Plan unavailable", tone: "warning" };
  }
  if (run.status === "succeeded") return { label: "Verified", tone: "success" };
  if (run.status === "failed" || run.status === "interrupted") {
    return { label: "Needs attention", tone: "danger" };
  }
  if (run.status === "cancelled") return { label: "Stopped", tone: "warning" };
  if (run.status === "queued") return { label: "Queued", tone: "neutral" };
  return { label: "In progress", tone: "info" };
}

export function proofState(run: AgentRun): ProductState {
  if (run.contribution?.contribution_receipt?.status === "recorded") {
    return { label: "Recorded", tone: "success" };
  }
  return changeState(run);
}

export function backlogState(specification: Specification): ProductState {
  if (specification.stale > 0) return { label: "Needs re-check", tone: "warning" };
  if (specification.done) return { label: "Verified", tone: "success" };
  if (specification.blocked > 0) return { label: "Blocked", tone: "danger" };
  return { label: "Ready", tone: "neutral" };
}

export function runtimeAttention(runtime: { hygiene: string; hygiene_issues: Array<{ type: string; count: number }>; requirements?: { ok: boolean; missing: string[] } }): string {
  if (runtime.requirements && !runtime.requirements.ok) {
    const count = runtime.requirements.missing.length;
    return `APatch runtime lacks ${count} required ${count === 1 ? "fix" : "fixes"}`;
  }
  const records = runtime.hygiene_issues.reduce((total, issue) => total + Math.max(0, issue.count || 0), 0);
  const amount = records > 0 ? ` (${records} ${records === 1 ? "record" : "records"})` : "";
  if (runtime.hygiene === "critical") return "Storage needs cleanup before new changes" + amount;
  if (runtime.hygiene === "degraded") return "Storage needs cleanup" + amount;
  return "Runtime check needed" + amount;
}

export function scopeState(scope: AgentRun["scope"]): ProductState {
  if (scope.status === "clean") return { label: "Requested scope only", tone: "success" };
  if (scope.status === "protected") return { label: "Extra writes prevented", tone: "warning" };
  if (scope.status === "attention") return { label: "Scope needs attention", tone: "danger" };
  return { label: "Scope check pending", tone: "neutral" };
}
