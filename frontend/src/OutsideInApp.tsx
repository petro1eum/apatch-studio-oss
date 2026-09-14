import {
  FolderGit2,
  GitBranch,
  Home,
  Inbox,
  Library,
  ListTodo,
  LoaderCircle,
  Monitor,
  Moon,
  RefreshCw,
  Settings2,
  ShieldCheck,
  Sun,
  X,
} from "lucide-react";
import { runtimeAttention } from "./productLanguage";
import { useCallback, useEffect, useMemo, useState } from "react";

import { loadChangeFeed, loadOverview, loadRunners, refreshOverview } from "./api";
import { ChangeDetailView } from "./ChangeDetailView";
import { ProjectPlanView } from "./ProjectPlanView";
import { AdminView, InboxView } from "./OutsideInAdmin";
import { BacklogView, HomeView, LibraryView } from "./OutsideInViews";
import type { ConfirmRequest } from "./OutsideInViews";
import {
  canonicalOutsideInHash,
  outsideInNavigationTargets,
  outsideInRouteHash,
  parseOutsideInHash,
} from "./outsideInNavigation";
import type { OutsideInRoute, OutsideInViewId } from "./outsideInNavigation";
import type { AgentRun, ChangeFeedItem, ProjectHomeSummary, RunnerInfo, WorkspaceOverview } from "./types";

const icons: Record<OutsideInViewId, typeof Home> = {
  home: Home,
  backlog: ListTodo,
  library: Library,
  admin: Settings2,
  inbox: Inbox,
};

type Theme = "system" | "light" | "dark";

function readTheme(): Theme {
  const value = localStorage.getItem("apatch-studio-theme");
  return value === "light" || value === "dark" ? value : "system";
}

export function OutsideInApp() {
  const [route, setRoute] = useState<OutsideInRoute>(() => parseOutsideInHash(window.location.hash));
  const [data, setData] = useState<WorkspaceOverview | null>(null);
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [changes, setChanges] = useState<ChangeFeedItem[]>([]);
  const [home, setHome] = useState<ProjectHomeSummary | null>(null);
  const [runners, setRunners] = useState<RunnerInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [theme, setTheme] = useState<Theme>(readTheme);

  const hydrate = useCallback(async (force = false) => {
    try {
      if (force) setRefreshing(true);
      const [overview, changePage, runnerItems] = await Promise.all([
        force ? refreshOverview() : loadOverview(),
        loadChangeFeed(),
        loadRunners(),
      ]);
      setData(overview);
      setChanges(changePage.items);
      setHome(changePage.home);
      setRuns(
        changePage.items
          .filter((item): item is Extract<ChangeFeedItem, { kind: "studio_run" }> => item.kind === "studio_run")
          .map((item) => item.run),
      );
      setRunners(runnerItems);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Studio could not load this workspace.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { void hydrate(); }, [hydrate]);

  useEffect(() => {
    const sync = () => {
      const next = parseOutsideInHash(window.location.hash);
      const canonical = canonicalOutsideInHash(window.location.hash);
      if (canonical !== window.location.hash) window.history.replaceState(null, "", canonical);
      setRoute(next);
    };
    sync();
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);

  useEffect(() => {
    const active = runs.some((run) => run.status === "queued" || run.status === "running");
    if (!active) return;
    const timer = window.setInterval(() => void hydrate(), 2500);
    return () => window.clearInterval(timer);
  }, [hydrate, runs]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("apatch-studio-theme", theme);
  }, [theme]);

  const navigate = useCallback((view: OutsideInViewId, section?: string, resourceId: string | null = null) => {
    const target = outsideInNavigationTargets.find((item) => item.id === view)!;
    window.location.hash = outsideInRouteHash({
      view,
      section: section ?? target.default_section,
      resourceId,
    });
  }, []);

  const visibleNavigation = useMemo(
    () => outsideInNavigationTargets.filter((item) =>
      item.availability === "all"
      || (item.id === "inbox" && data?.product.features.execution_intents === true)),
    [data?.product.features.execution_intents],
  );

  const activeRuns = runs.filter((run) => run.status === "queued" || run.status === "running").length;
  const openPlans = data?.plans.items.filter((plan) => plan.state !== "complete").length ?? 0;
  const navCounts: Partial<Record<OutsideInViewId, number>> = { home: activeRuns, backlog: openPlans };

  async function confirmAction() {
    if (!confirm) return;
    setConfirming(true);
    try {
      await confirm.action();
      setConfirm(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The action could not complete.");
    } finally {
      setConfirming(false);
    }
  }

  if (loading) return <div className="oi-loading"><LoaderCircle className="spin" size={24} /><span>Opening workspace…</span></div>;
  if (!data || !home) return <div className="oi-loading is-error"><span>{error ?? "Workspace unavailable."}</span><button className="oi-button oi-button-primary" type="button" onClick={() => void hydrate()}>Retry</button></div>;

  return (
    <div className="oi-shell">
      <aside className="oi-sidebar">
        <div className="oi-brand"><span className="oi-brand-mark"><ShieldCheck size={18} /></span><div><strong>APatch Studio</strong><small className="oi-brand-edition">{data.product.edition.toUpperCase()} edition</small></div></div>
        <nav aria-label="Primary">
          <p className="oi-nav-section">Workspace</p>
          {visibleNavigation.map((item) => {
            const Icon = icons[item.id];
            const count = navCounts[item.id] ?? 0;
            return <button key={item.id} className={route.view === item.id ? "is-active" : ""} type="button" onClick={() => navigate(item.id)} title={item.label}><Icon size={18} /><span>{item.label}</span>{item.id === "inbox" && data.execution_intents.pending ? <em>{data.execution_intents.pending}</em> : count ? <b className="oi-nav-count">{count}</b> : null}</button>;
          })}
        </nav>
        <div className="oi-sidebar-footer">
          <div className="oi-theme-control" aria-label="Theme">
            <button className={theme === "system" ? "is-active" : ""} type="button" title="System theme" onClick={() => setTheme("system")}><Monitor size={14} /></button>
            <button className={theme === "light" ? "is-active" : ""} type="button" title="Light theme" onClick={() => setTheme("light")}><Sun size={14} /></button>
            <button className={theme === "dark" ? "is-active" : ""} type="button" title="Dark theme" onClick={() => setTheme("dark")}><Moon size={14} /></button>
          </div>
          <button className={"oi-runtime-card" + (data.runtime.hygiene === "clean" && data.runtime.requirements.ok ? "" : " is-attention")} type="button" title={data.runtime.hygiene === "clean" && data.runtime.requirements.ok ? "Open Admin" : runtimeAttention(data.runtime) + ". Open Admin for the next step."} onClick={() => navigate("admin", "runtime")}>
            <span>Local runtime</span>
            <strong>{data.runtime.enforcement ? "Protected" : "Audit mode"} · APatch {data.runtime.apatch_version}</strong>
            {data.runtime.hygiene === "clean" && data.runtime.requirements.ok ? null : <small>{runtimeAttention(data.runtime)} · {data.runtime.requirements.ok ? "Open Admin to run safe cleanup" : "Open Admin for the update step"}</small>}
          </button>
        </div>
      </aside>

      <div className="oi-workspace">
        <header className="oi-topbar">
          <div className="oi-topbar-context"><FolderGit2 size={16} /><strong>{data.workspace.name}</strong>{data.workspace.branch ? <span><GitBranch size={13} /><code>{data.workspace.branch}</code></span> : null}</div>
          <div className="oi-topbar-actions">
            <span className={"oi-topbar-state tone-" + home.state.tone} title={home.state.detail + ". " + home.state.next_step + "."}><span className={"oi-dot tone-" + home.state.tone} />{home.state.label}</span>
            <button className="oi-icon-button" type="button" title="Refresh workspace" disabled={refreshing} onClick={() => void hydrate(true)}><RefreshCw className={refreshing ? "spin" : ""} size={17} /></button>
          </div>
        </header>
        <main className="oi-main">
        {error ? <div className="oi-global-error" role="alert"><span>{error}</span><button type="button" title="Dismiss" onClick={() => setError(null)}><X size={15} /></button></div> : null}
        {route.view === "home" ? (
          route.resourceId ? (
            <ChangeDetailView
              resourceId={route.resourceId}
              item={changes.find((item) => item.id === route.resourceId)}
              data={data}
              onBack={() => navigate("home")}
              onOpenRun={(runId) => navigate("home", "feed", runId)}
              onOpenDocument={(documentId) => navigate("backlog", "requirements", documentId)}
              onChanged={() => hydrate(true)}
              requestConfirm={setConfirm}
            />
          ) : (
            <HomeView data={data} home={home} changes={changes} runners={runners} selectedRunId={null} onSelectRun={(runId) => navigate("home", "feed", runId)} onOpenPlans={() => navigate("backlog")} onOpenLibrary={() => navigate("library")} onOpenAdmin={() => navigate("admin")} onOpenPlan={(documentId) => navigate("backlog", "requirements", documentId)} onChanged={() => hydrate(true)} requestConfirm={setConfirm} />
          )
        ) : null}
        {route.view === "backlog" ? (route.resourceId ? <ProjectPlanView resourceId={route.resourceId} runners={runners} onBack={() => navigate("backlog")} onOpenDocument={(documentId) => navigate("backlog", "requirements", documentId)} onChanged={() => hydrate(true)} /> : <BacklogView data={data} onOpenPlan={(documentId) => navigate("backlog", "requirements", documentId)} />) : null}
        {route.view === "library" ? <LibraryView data={data} section={(["methods", "proof", "time"].includes(route.section) ? route.section : "methods") as "methods" | "proof" | "time"} onSection={(section) => navigate("library", section)} runners={runners} onChanged={() => hydrate(true)} /> : null}
        {route.view === "admin" ? <AdminView data={data} runners={runners} section={(["runtime", "workspaces", "rules"].includes(route.section) ? route.section : "runtime") as "runtime" | "workspaces" | "rules"} onSection={(section) => navigate("admin", section)} requestConfirm={setConfirm} onChanged={() => hydrate(true)} /> : null}
        {route.view === "inbox" ? <InboxView data={data} runners={runners} onChanged={() => hydrate(true)} /> : null}
        </main>
      </div>

      {confirm ? <div className="oi-dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !confirming) setConfirm(null); }}><section className="oi-dialog" role="alertdialog" aria-modal="true" aria-labelledby="oi-dialog-title"><button className="oi-dialog-close" type="button" title="Close" disabled={confirming} onClick={() => setConfirm(null)}><X size={17} /></button><h2 id="oi-dialog-title">{confirm.title}</h2><p>{confirm.message}</p><div className="oi-action-row"><button className="oi-button oi-button-secondary" type="button" disabled={confirming} onClick={() => setConfirm(null)}>Cancel</button><button className={"oi-button " + (confirm.tone === "danger" ? "oi-button-danger" : "oi-button-primary")} type="button" disabled={confirming} onClick={() => void confirmAction()}>{confirming ? <LoaderCircle className="spin" size={15} /> : null}{confirm.confirmLabel}</button></div></section></div> : null}
    </div>
  );
}
