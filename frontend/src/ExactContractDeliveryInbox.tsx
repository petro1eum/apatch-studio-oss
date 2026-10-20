import { useEffect, useRef, useState } from "react";
import type { RunnerInfo, WorkspaceOverview } from "./types";
import {
  ExactDeliveryApiError, buildExactEvidence, importExactContract, listExactContracts,
  previewExactEvidence, publishExactEvidence, readExactChoices, readExactDelivery,
  readExactRun, runExactForDelivery,
} from "./exactContractDeliveryApi";
import type { EvidenceReady, ExactContractChoices, ExactContractDelivery, ExactContractRow, PublicationResult, SharePlan } from "./exactContractDeliveryApi";

const words = {
  en: { title: "Contracts with the customer", note: "Tests are fixed by the signed agreement. Studio cannot change them or accept work for the customer.",
    empty: "No agreed contracts are waiting.", unavailable: "Exact contract delivery is not configured for this workspace.",
    open: "Open agreed contract", loading: "Reading the agreed contract…", check: "Agreed check", runner: "Local agent",
    run: "Run and prepare customer delivery", build: "Prepare evidence", preview: "Preview what will be shared", refresh: "Refresh result",
    consent: "I checked the recipient and selection. Share only these evidence records.", publish: "Send selected evidence",
    received: "Evidence delivered. The customer still decides whether to accept the work on the site.",
    queued: "Waiting for a valid platform receipt. The customer still decides; work is not accepted.",
    cached: "Previously recorded delivery; a new receipt was not checked. The customer still decides.",
    local: "Evidence is ready locally. Nothing has been published.", notRun: "Execution has not started.", running: "Local execution is not yet verified.",
    verified: "Local tests passed. This is evidence, not customer acceptance.", ack: "Source acknowledgement received.",
    sourceWaiting: "Source acknowledgement is still pending; execution/evidence is not ready.", recipient: "Recipient", selection: "Selection",
    bundle: "Evidence record", time: "Time record", proof: "Agreement and proof references", requirement: "Agreed requirement",
    error: "This operation could not be completed. Refresh the selected contract before retrying.", changed: "The workspace, account or selection changed. Open the current contract and preview again.",
    importTitle: "Import a signed agreement", importLabel: "Signed agreement from the customer", import: "Import agreement", choose: "Select a contract to continue.",
  },
  ru: { title: "Договоры с заказчиком", note: "Тесты закреплены подписанным договором. Studio не может менять их или принимать работу за заказчика.",
    empty: "Согласованных договоров пока нет.", unavailable: "Передача согласованного договора ещё не настроена для этой рабочей области.",
    open: "Открыть согласованный договор", loading: "Читаем согласованный договор…", check: "Согласованная проверка", runner: "Локальный агент",
    run: "Выполнить и подготовить к передаче", build: "Подготовить доказательства", preview: "Посмотреть, что будет передано", refresh: "Обновить результат",
    consent: "Я проверил получателя и состав. Передать только эти записи доказательств.", publish: "Передать выбранные доказательства",
    received: "Доказательства доставлены. Принять работу ещё должен заказчик на сайте.",
    queued: "Ждём действительную квитанцию платформы. Работа ещё не принята заказчиком.",
    cached: "Доставка ранее отмечена; новая квитанция не проверялась. Решение остаётся за заказчиком.",
    local: "Доказательства готовы локально. Ничего не опубликовано.", notRun: "Выполнение ещё не началось.", running: "Локальное выполнение ещё не проверено.",
    verified: "Локальные тесты прошли. Это доказательства, а не приёмка заказчиком.", ack: "Привязка к источнику подтверждена.",
    sourceWaiting: "Подтверждение источника ещё ожидается; выполнение и доказательства не готовы.", recipient: "Получатель", selection: "Состав",
    bundle: "Запись доказательств", time: "Запись времени", proof: "Ссылки на договор и доказательства", requirement: "Согласованное требование",
    error: "Операцию не удалось завершить. Обновите выбранный договор перед повтором.", changed: "Рабочая область, аккаунт или выбор изменились. Откройте текущий договор и проверьте состав заново.",
    importTitle: "Импортировать подписанный договор", importLabel: "Подписанный договор от заказчика", import: "Импортировать договор", choose: "Выберите договор для продолжения.",
  },
};

export function ExactContractDeliveryInbox({ data, runners, onChanged }: {
  data: WorkspaceOverview; runners: RunnerInfo[]; onChanged: () => Promise<void>;
}) {
  const lang = document.documentElement.lang.startsWith("ru") ? "ru" : "en";
  const t = words[lang];
  const scope = [data.workspace.identity, data.workspace.operator, data.execution_intents.workspace_id ?? "exact-only"].join("|");
  const epoch = useRef(0);
  const scopeRef = useRef(scope);
  const requests = useRef(new Set<AbortController>());
  const busyRef = useRef(false);
  const [items, setItems] = useState<ExactContractRow[]>([]);
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [selected, setSelected] = useState<ExactContractRow | null>(null);
  const [choices, setChoices] = useState<ExactContractChoices | null>(null);
  const [requirement, setRequirement] = useState("");
  const availableRunners = runners.filter(item => item.available && ["codex", "claude"].includes(item.id));
  const [runner, setRunner] = useState<"codex" | "claude">((availableRunners[0]?.id as "codex" | "claude") ?? "codex");
  const [delivery, setDelivery] = useState<ExactContractDelivery | null>(null);
  const [runStatus, setRunStatus] = useState<string | null>(null);
  const [evidence, setEvidence] = useState<EvidenceReady | null>(null);
  const [plan, setPlan] = useState<SharePlan | null>(null);
  const [consent, setConsent] = useState(false);
  const [publication, setPublication] = useState<PublicationResult | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [envelope, setEnvelope] = useState("");

  // Invalidate at render, not only after effects: an old promise cannot land
  // between a new workspace/account render and its effect cleanup.
  if (scopeRef.current !== scope) { scopeRef.current = scope; epoch.current += 1; }

  function invalidate() {
    epoch.current += 1;
    requests.current.forEach(controller => controller.abort());
    requests.current.clear(); busyRef.current = false; setBusy(null);
    setChoices(null); setRequirement(""); setDelivery(null); setRunStatus(null);
    setEvidence(null); setPlan(null); setConsent(false); setPublication(null); setError(null);
  }
  function current(stamp: number) { return epoch.current === stamp && scopeRef.current === scope; }
  async function act(kind: string, work: (signal: AbortSignal, stamp: number) => Promise<void>) {
    if (busyRef.current) return;
    const stamp = epoch.current;
    const controller = new AbortController(); requests.current.add(controller);
    busyRef.current = true; setBusy(kind); setError(null);
    try { await work(controller.signal, stamp); }
    catch (reason) {
      if (current(stamp)) {
        const code = reason instanceof ExactDeliveryApiError ? reason.code : "delivery_request_failed";
        const changed = ["publication_context_changed", "workspace_identity_mismatch", "publication_preview_required"].includes(code);
        if (changed) { setPlan(null); setConsent(false); setPublication(null); }
        setError(changed ? t.changed : t.error);
      }
    } finally {
      requests.current.delete(controller);
      if (current(stamp)) { busyRef.current = false; setBusy(null); }
    }
  }
  useEffect(() => {
    invalidate(); setSelected(null); setItems([]); setWorkspaceId(null); setUnavailable(false);
    const stamp = epoch.current;
    const controller = new AbortController(); requests.current.add(controller);
    void listExactContracts(controller.signal).then(page => {
      if (!current(stamp)) return;
      if (data.execution_intents.workspace_id && page.workspace_id !== data.execution_intents.workspace_id) throw new ExactDeliveryApiError("workspace_identity_mismatch");
      setItems(page.items); setWorkspaceId(page.workspace_id);
    }).catch(() => { if (current(stamp)) setUnavailable(true); }).finally(() => requests.current.delete(controller));
    return () => { epoch.current += 1; requests.current.forEach(item => item.abort()); requests.current.clear(); };
  }, [scope]);

  function choose(item: ExactContractRow) {
    invalidate(); setSelected(item);
    void act("open", async (signal, stamp) => {
      const [nextChoices, nextDelivery] = await Promise.all([readExactChoices(item.handoff_id, signal), readExactDelivery(item.handoff_id, signal)]);
      if (!current(stamp)) return;
      if (nextChoices.workspace_id !== workspaceId) throw new ExactDeliveryApiError("workspace_identity_mismatch");
      setChoices(nextChoices); setRequirement(item.requirement ?? nextChoices.requirements[0].requirement); setDelivery(nextDelivery);
      if (nextDelivery.run_id) { const status = await readExactRun(nextDelivery.run_id, signal); if (current(stamp)) setRunStatus(status); }
    });
  }
  function run() {
    if (!selected || !choices || !requirement || !availableRunners.some(item => item.id === runner)) return;
    void act("run", async (signal, stamp) => {
      const result = await runExactForDelivery(selected.handoff_id, choices.workspace_id, runner, requirement, signal);
      if (!current(stamp)) return;
      setDelivery(result);
      if (result.run_id) { const status = await readExactRun(result.run_id, signal); if (current(stamp)) setRunStatus(status); }
      if (current(stamp)) await onChanged();
    });
  }
  function refresh() {
    if (!selected) return;
    void act("refresh", async (signal, stamp) => {
      const result = await readExactDelivery(selected.handoff_id, signal);
      if (!current(stamp)) return; setDelivery(result);
      if (result.run_id) { const status = await readExactRun(result.run_id, signal); if (current(stamp)) setRunStatus(status); }
    });
  }
  function build() {
    if (!selected || !delivery?.run_id || delivery.status !== "source_acknowledged" || runStatus !== "succeeded") return;
    void act("build", async (signal, stamp) => {
      const result = await buildExactEvidence(selected.handoff_id, delivery.run_id!, signal);
      if (!current(stamp)) return;
      if (result.source_binding_id !== delivery.source_binding_id || result.source_binding_hash !== delivery.source_binding_hash) throw new ExactDeliveryApiError("invalid_delivery_response");
      setEvidence(result); setPlan(null); setConsent(false); setPublication(null);
    });
  }
  function preview() {
    if (!evidence) return;
    void act("preview", async (signal, stamp) => {
      const result = await previewExactEvidence(evidence.source_binding_id, signal);
      if (!current(stamp)) return;
      if (result.evidence_bundle_ref.bundle_hash !== evidence.evidence_bundle_hash || result.timesheet_ref.timesheet_hash !== evidence.timesheet_hash) throw new ExactDeliveryApiError("invalid_delivery_response");
      setPlan(result); setConsent(false); setPublication(null);
    });
  }
  function publish() {
    if (!plan || !consent) return;
    void act("publish", async (signal, stamp) => { const result = await publishExactEvidence(plan, signal); if (current(stamp)) { setPublication(result); setConsent(false); } });
  }
  function importAgreement() {
    if (!envelope.trim()) return;
    void act("import", async (signal, stamp) => { await importExactContract(envelope, signal); const page = await listExactContracts(signal);
      if (current(stamp)) { setEnvelope(""); setItems(page.items); setWorkspaceId(page.workspace_id); setUnavailable(false); } });
  }

  const panel: React.CSSProperties = { border: "1px solid var(--tc-border, #ccd3df)", borderRadius: 12, padding: 16, marginBottom: 24, overflowWrap: "anywhere" };
  return <section style={panel} data-testid="exact-contract-inbox" aria-label={t.title}>
    <h2>{t.title}</h2><p>{t.note}</p>
    {unavailable ? <p role="status">{t.unavailable}</p> : <>
      {items.length === 0 ? <p>{t.empty}</p> : <div className="oi-action-row" style={{ flexWrap: "wrap" }}>{items.map((item, index) =>
        <button className="oi-button oi-button-secondary" type="button" key={item.handoff_id} data-testid={"exact-contract-open-" + item.handoff_id}
          onClick={() => choose(item)}>{t.open} {index + 1}</button>)}</div>}
      {selected ? <article style={{ marginTop: 16 }} data-testid="exact-contract-selected" data-handoff-id={selected.handoff_id}>
        {!choices ? <p role="status">{t.loading}</p> : <>
          <div className="oi-action-row" style={{ flexWrap: "wrap", alignItems: "end" }}>
            <label className="oi-field"><span>{t.check}</span><select data-testid="exact-contract-requirement" value={requirement}
              disabled={busy !== null || delivery?.status === "source_acknowledged"} onChange={event => { setRequirement(event.target.value); setPlan(null); setConsent(false); setEvidence(null); setPublication(null); }}>
              {choices.requirements.map((item, index) => <option key={item.requirement} value={item.requirement}>{t.check} {index + 1}</option>)}
            </select></label>
            <label className="oi-field"><span>{t.runner}</span><select data-testid="exact-contract-runner" value={runner} disabled={busy !== null || delivery?.status === "source_acknowledged"}
              onChange={event => setRunner(event.target.value as "codex" | "claude")}>{availableRunners.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
            <button className="oi-button oi-button-primary" type="button" data-testid="exact-contract-run" onClick={run}
              disabled={busy !== null || !requirement || !availableRunners.some(item => item.id === runner) || Boolean(delivery?.run_id)}>{t.run}</button>
          </div>
          <p role="status">{delivery?.status === "pending_source_ack" ? t.sourceWaiting : runStatus === "succeeded" ? t.verified : delivery?.run_id ? t.running : t.notRun}</p>
          <div className="oi-action-row" style={{ flexWrap: "wrap" }}>
            <button className="oi-button oi-button-secondary" type="button" disabled={busy !== null} onClick={refresh}>{t.refresh}</button>
            <button className="oi-button oi-button-secondary" type="button" data-testid="exact-contract-build" onClick={build}
              disabled={busy !== null || delivery?.status !== "source_acknowledged" || runStatus !== "succeeded"}>{t.build}</button>
            <button className="oi-button oi-button-secondary" type="button" data-testid="exact-evidence-preview" disabled={busy !== null || !evidence} onClick={preview}>{t.preview}</button>
          </div>
          {evidence && !publication ? <p role="status">{t.local}</p> : null}
          {plan ? <div style={{ marginTop: 16, padding: 12, background: "var(--tc-bg-subtle, #eef2f7)", borderRadius: 8 }}>
            <h3>{t.recipient}</h3><p>{plan.platform_origin} · {plan.project_group_id}</p>
            <h3>{t.selection}</h3><p>{t.bundle}: {plan.evidence_bundle_ref.bundle_id}<br />{t.time}: {plan.timesheet_ref.timesheet_id} · {plan.timesheet_ref.claimed_active_seconds} s</p>
            <label style={{ display: "flex", gap: 8, alignItems: "flex-start" }}><input data-testid="exact-evidence-consent" type="checkbox" checked={consent} disabled={busy !== null}
              onChange={event => setConsent(event.target.checked)} /><span>{t.consent}</span></label>
            <button className="oi-button oi-button-primary" style={{ marginTop: 12, maxWidth: "100%", whiteSpace: "normal" }} type="button" data-testid="exact-evidence-publish"
              disabled={busy !== null || !consent} onClick={publish}>{t.publish}</button>
          </div> : null}
          {publication ? <p role="status" data-testid="exact-evidence-delivery-status">{publication.synchronization.status === "acknowledged" ? t.received
            : publication.synchronization.status === "queued" ? t.queued : t.cached}</p> : null}
          <details className="oi-proof"><summary>{t.proof}</summary><dl><dt>{t.requirement}</dt><dd>{requirement}</dd>
            {delivery?.source_binding_id ? <><dt>{t.ack}</dt><dd>{delivery.source_binding_id}</dd></> : null}</dl></details>
        </>}
      </article> : <p>{t.choose}</p>}
      <details className="oi-proof" style={{ marginTop: 12 }}><summary>{t.importTitle}</summary><label className="oi-field"><span>{t.importLabel}</span>
        <textarea value={envelope} rows={4} onChange={event => setEnvelope(event.target.value)} /></label>
        <button className="oi-button oi-button-secondary" type="button" disabled={busy !== null || !envelope.trim()} onClick={importAgreement}>{t.import}</button></details>
    </>}
    {error ? <p role="alert" className="oi-alert is-error" data-testid="exact-contract-error">{error}</p> : null}
  </section>;
}
