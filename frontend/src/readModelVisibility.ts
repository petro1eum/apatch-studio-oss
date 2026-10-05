/** Document/configuration navigation is independent of signed-history readiness. */
export function canRenderWorkspaceView(view: string, status: string | undefined): boolean {
  return status !== "building" && status !== "unavailable"
    || view === "backlog" || view === "admin";
}
