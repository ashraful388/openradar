"use client";

import { useEffect, useState } from "react";

const FREE_WHEN = [
  { value: "both_input_and_output_zero", label: "Both input and output are $0" },
  { value: "either_input_or_output_zero", label: "Either is $0" },
  { value: "min_or_max", label: "Min of input and output is $0" },
];

const LOG_LEVELS = ["debug", "info", "warn", "error"];

const SOURCES = [
  { key: "openrouter",        label: "OpenRouter",           desc: "/api/v1/models; adds :free variants" },
  { key: "huggingface",       label: "Hugging Face",         desc: "router.huggingface.co/v1/models" },
  { key: "models_dev",        label: "models.dev",           desc: "Structured pricing + capabilities" },
  { key: "bai_static",        label: "b.ai (static catalog)", desc: "The catalog in apps/agent/openradar/sources/bai.py" },
  { key: "bai_live",          label: "b.ai (live, requires BAI_API_KEY)", desc: "Pulls /v1/models when key is set" },
  { key: "community_lists",   label: "Community GitHub lists", desc: "cheahjs, zukixa, jamez-bondos" },
  { key: "search_apis",       label: "Search APIs (Brave/Tavily/Exa)", desc: "Web discovery; needs a key" },
  { key: "provider_endpoints",label: "Per-provider /v1/models", desc: "Polling every cataloged provider" },
];

const VERIFIER_PROVIDERS = [
  { value: "openai",    label: "OpenAI (or any OpenAI-compatible endpoint)" },
  { value: "anthropic", label: "Anthropic (requires a proxy; non-OpenAI-compatible)" },
  { value: "custom",    label: "Custom URL (self-hosted / Together / Groq / OpenRouter)" },
];

export function SettingsForm({
  initial,
  hasConfig,
  snapshotStats,
}: {
  initial: any;
  hasConfig: boolean;
  snapshotStats: { providers: number; models: number; free: number; flagships: number; snapshotAt: string } | null;
}) {
  const [cfg, setCfg] = useState<any>(
    initial || {
      agent: { run_interval_hours: 10, llm_orchestration_enabled: false, manual_mode: false,
               include_search_apis: true, include_community_lists: true,
               auto_promote_candidates: true, auto_remove_stale: false, log_level: "info" },
      free_detection: { free_only_when: "both_input_and_output_zero", min_dollar_threshold: 0,
                        respect_b_ai_pricing: true, treat_credits_as_free: true },
      flagships: { max_output_per_1m: 20.0, require_tool_calling_or_vision: true, min_quality_signal: "any" },
      sources: {
        openrouter: { enabled: true, weight: 1.0 },
        huggingface: { enabled: true, weight: 1.0 },
        models_dev: { enabled: true, weight: 1.0 },
        bai_static: { enabled: true, weight: 1.0 },
        bai_live: { enabled: true, weight: 1.5 },
        community_lists: { enabled: true, weight: 0.8 },
        search_apis: { enabled: true, weight: 0.6 },
        provider_endpoints: { enabled: true, weight: 0.7 },
        verifier: { enabled: false, weight: 1.0 },  // legacy; see Intelligence section below
      },
      verifier: {
        enabled: false,
        primary_provider: "",
        secondary_provider: "",
        auto_apply_expire: true,
        expire_confidence_threshold: 0.7,
      },
      ui: { show_paid_models_on_provider_page: true, models_page_view: "grouped",
            default_region_filter: "", highlight_status_dot_threshold_days: 7 },
      notifications: { new_provider_webhook_url: "", expired_tier_webhook_url: "" },
    }
  );
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<null | "ok" | "err">(null);
  const [errMsg, setErrMsg] = useState<string | null>(null);

  // Intelligence (LLM verifier) state — provider cards live in a
  // separate secrets file, not in the public config.json. The form
  // owns the editing flow for one card at a time.
  const [verifierProviders, setVerifierProviders] = useState<any[]>([]);
  const [editingProvider, setEditingProvider] = useState<any | null>(null);  // null = no card selected
  const [verifierErr, setVerifierErr] = useState<string | null>(null);
  const [verifierSaved, setVerifierSaved] = useState<null | "ok" | "err">(null);

  // Run-now state — polled from /api/run. The form shows a status row
  // and a button that triggers a fresh agent run.
  const [runState, setRunState] = useState<any>({ last_status: "idle" });
  const [runErr, setRunErr] = useState<string | null>(null);
  const [runMsg, setRunMsg] = useState<string | null>(null);
  const [runPending, setRunPending] = useState(false);

  // Load existing provider cards on mount.
  useEffect(() => {
    (async () => {
      try {
        const r = await fetch("/api/verifier-secrets");
        if (!r.ok) return;
        const data = await r.json();
        setVerifierProviders(data.providers || []);
      } catch {
        // silent — the form still works without a prior secrets file
      }
    })();
  }, []);

  // Provider API keys panel — slot list + masked saved state.
  const [providerKeyEnvs, setProviderKeyEnvs] = useState<
    { env: string; provider: string; slug: string; signup: string }[]
  >([]);
  const [providerKeysSaved, setProviderKeysSaved] = useState<
    Record<string, { masked: string; set: boolean }>
  >({});
  const [providerKeyDrafts, setProviderKeyDrafts] = useState<Record<string, string>>({});
  const [providerKeysPending, setProviderKeysPending] = useState(false);
  const [providerKeysSavedState, setProviderKeysSavedState] = useState<null | "ok" | "err">(null);
  const [providerKeysErrMsg, setProviderKeysErrMsg] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch("/api/provider-keys");
        if (!r.ok) return;
        const data = await r.json();
        setProviderKeyEnvs(data.slots || []);
        setProviderKeysSaved(data.keys || {});
      } catch {
        // silent — the panel still renders, just without saved state
      }
    })();
  }, []);

  async function saveProviderKeys() {
    setProviderKeysPending(true);
    setProviderKeysSavedState(null);
    setProviderKeysErrMsg(null);
    try {
      const r = await fetch("/api/provider-keys", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ keys: providerKeyDrafts }),
      });
      const data = await r.json();
      if (!r.ok || !data.ok) {
        setProviderKeysSavedState("err");
        setProviderKeysErrMsg(data.error ?? `HTTP ${r.status}`);
        return;
      }
      setProviderKeysSaved(data.keys || {});
      setProviderKeyDrafts({}); // inputs clear; saved placeholders show state
      setProviderKeysSavedState("ok");
    } catch (e: any) {
      setProviderKeysSavedState("err");
      setProviderKeysErrMsg(String(e?.message ?? e));
    } finally {
      setProviderKeysPending(false);
    }
  }

  // Poll /api/run so the status row stays current. Poll whenever the
  // tracked job is running (from the initial state OR a Run-now click)
  // and keep polling to the terminal state; a job started after mount
  // must still be watched.
  useEffect(() => {
    let timer: any = null;
    let cancelled = false;
    const tick = async () => {
      try {
        const r = await fetch("/api/run");
        if (!r.ok) return;
        const data = await r.json();
        if (cancelled) return;
        setRunState(data);
        if (data.last_status === "running" && timer == null) {
          timer = setInterval(tick, 2000);
        } else if (data.last_status !== "running" && timer != null) {
          clearInterval(timer);
          timer = null;
        }
      } catch {
        // silent — the row just keeps showing the last known state
      }
    };
    tick();
    return () => { cancelled = true; if (timer) clearInterval(timer); };
  }, [runState?.last_job_id]);

  async function runNow() {
    setRunErr(null);
    setRunMsg(null);
    setRunPending(true);
    try {
      const r = await fetch("/api/run", { method: "POST" });
      // Parse defensively: a crashed or empty response must surface a
      // real message instead of "Unexpected end of JSON input".
      const text = await r.text();
      let data: any = null;
      try {
        data = text ? JSON.parse(text) : null;
      } catch {
        data = null;
      }
      if (!r.ok || !data?.ok) {
        setRunErr(data?.error || `Run failed to start (HTTP ${r.status}).`);
        return;
      }
      if (data.via === "github-actions" || !data.job_id) {
        // Hosted deployment: no local agent to poll — the GitHub Actions
        // run was dispatched instead.
        setRunMsg(data.message || "Dispatched a GitHub Actions discovery run.");
        return;
      }
      setRunState({
        last_status: "running",
        last_job_id: data.job_id,
        last_started: data.started,
        last_summary: "agent run starting…",
      });
    } catch (e: any) {
      setRunErr(e?.message ?? "run failed");
    } finally {
      setRunPending(false);
    }
  }

  // Save the full provider list (called by Add/Edit/Delete).
  async function saveVerifierProviders(next: any[]): Promise<boolean> {
    setVerifierErr(null);
    setVerifierSaved(null);
    try {
      const r = await fetch("/api/verifier-secrets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ providers: next }),
      });
      if (!r.ok) {
        const t = await r.text();
        throw new Error(t || "save failed");
      }
      const data = await r.json();
      setVerifierProviders(data.providers || []);
      setVerifierSaved("ok");
      setTimeout(() => setVerifierSaved(null), 2500);
      return true;
    } catch (e: any) {
      setVerifierErr(e?.message ?? "save failed");
      setVerifierSaved("err");
      return false;
    }
  }

  function set<K extends keyof typeof cfg>(section: K, value: any) {
    setCfg((c: any) => ({ ...c, [section]: value }));
  }
  function setNested(section: string, key: string, value: any) {
    setCfg((c: any) => ({ ...c, [section]: { ...c[section], [key]: value } }));
  }
  function setSource(key: string, field: "enabled" | "weight", value: any) {
    setCfg((c: any) => ({
      ...c,
      sources: { ...c.sources, [key]: { ...c.sources[key], [field]: value } },
    }));
  }

  async function save() {
    setSaving(true);
    setSaved(null);
    setErrMsg(null);
    try {
      const res = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(cfg),
      });
      if (!res.ok) throw new Error(await res.text());
      setSaved("ok");
      setTimeout(() => setSaved(null), 2500);
    } catch (e: any) {
      setSaved("err");
      setErrMsg(e?.message ?? "save failed");
    } finally {
      setSaving(false);
    }
  }

  async function reset() {
    const res = await fetch("/api/settings", { method: "DELETE" });
    if (res.ok) {
      location.reload();
    }
  }

  return (
    <div className="settings">
      {!hasConfig ? (
        <p className="dim settings-banner">
          No <code className="mono">data/config.json</code> yet &mdash; the agent is running on
          defaults. Save below to make any change explicit.
        </p>
      ) : null}

      {snapshotStats ? (
        <section className="settings-stats">
          <h2 className="section-title">Last snapshot</h2>
          <ul className="stat-list">
            <li className="stat-row">
              <span className="stat-num">{snapshotStats.providers}</span>
              <span className="stat-label">providers</span>
            </li>
            <li className="stat-row">
              <span className="stat-num">{snapshotStats.models}</span>
              <span className="stat-label">total models</span>
            </li>
            <li className="stat-row">
              <span className="stat-num">{snapshotStats.free}</span>
              <span className="stat-label">free models</span>
            </li>
            <li className="stat-row">
              <span className="stat-num">{snapshotStats.flagships}</span>
              <span className="stat-label">cheap flagships</span>
            </li>
            <li className="stat-row">
              <span className="stat-num dim" style={{ fontSize: 14 }}>{new Date(snapshotStats.snapshotAt).toISOString().slice(0, 16).replace("T", " ")} UTC</span>
              <span className="stat-label dim">last refresh</span>
            </li>
          </ul>
        </section>
      ) : null}

      <section className="settings-block">
        <h2 className="section-title">Agent</h2>
        <Field label="Run every N hours" hint="How often the scheduled run fires. 1-24. The CI cron uses this same value.">
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <input type="number" min={1} max={24} step={1} style={{ width: 90 }}
                   value={cfg.agent.run_interval_hours ?? 10}
                   onChange={(e) => {
                     const v = parseInt(e.target.value);
                     setNested("agent", "run_interval_hours", Number.isFinite(v) ? v : 10);
                   }} />
            <span className="dim small">hours</span>
          </div>
        </Field>

        <Toggle label="Manual only" value={!!cfg.agent.manual_mode}
                 onChange={(v) => setNested("agent", "manual_mode", v)}
                 hint="When on, the scheduled run is suppressed — only Run now (below) and the GitHub Actions dispatch trigger will fire." />

        <div className="run-now-row">
          <div className="run-now-status">
            <div className={"run-now-dot run-now-dot-" + (runState.last_status || "idle")} />
            <div>
              <div className="run-now-headline">
                {runState.last_status === "running" ? "Agent is running…"
                 : runState.last_status === "done" ? "Last run: completed"
                 : runState.last_status === "failed" ? "Last run: failed"
                 : runState.last_status === "timeout" ? "Last run: timed out"
                 : "Idle — no run yet"}
              </div>
              <div className="run-now-meta dim small">
                {runState.last_started ? new Date(runState.last_started).toISOString().slice(0, 16).replace("T", " ") + " UTC" : ""}
                {runState.last_summary ? " · " + runState.last_summary : ""}
              </div>
            </div>
          </div>
          <button className="btn" onClick={runNow} disabled={runPending || runState.last_status === "running"}>
            {runState.last_status === "running" ? "Running…" : runPending ? "Starting…" : "Run now"}
          </button>
        </div>
        {runErr ? <p className="settings-err">{runErr}</p> : null}
        {runMsg ? <p className="settings-ok">{runMsg}</p> : null}

        <Field label="Log level" hint="Verbosity of the agent's run output.">
          <select value={cfg.agent.log_level} onChange={(e) => setNested("agent", "log_level", e.target.value)}>
            {LOG_LEVELS.map((l) => <option key={l} value={l}>{l}</option>)}
          </select>
        </Field>
        <Toggle label="Include search APIs" value={cfg.agent.include_search_apis}
                 onChange={(v) => setNested("agent", "include_search_apis", v)} />
        <Toggle label="Include community GitHub lists" value={cfg.agent.include_community_lists}
                 onChange={(v) => setNested("agent", "include_community_lists", v)} />
        <Toggle label="Auto-promote candidates with working /v1/models" value={cfg.agent.auto_promote_candidates}
                 onChange={(v) => setNested("agent", "auto_promote_candidates", v)}
                 hint="If off, discovered hosts go to a review queue instead of becoming providers." />
        <Toggle label="Auto-remove stale providers" value={cfg.agent.auto_remove_stale}
                 onChange={(v) => setNested("agent", "auto_remove_stale", v)}
                 hint="Off by default; stale providers keep their row with a low last_verified." />
      </section>

      <section className="settings-block">
        <h2 className="section-title">Orchestration</h2>
        <p className="dim" style={{ margin: "0 0 12px", fontSize: 13 }}>
          When enabled, the LLM becomes the controller of the discovery run. It picks which
          providers and models to investigate this cycle and dispatches scraper and judge
          tasks to the underlying sources. The same trust rules apply: every decision cites
          evidence, the only mutation the agent can apply is <code className="mono">is_free</code>
          {" "}True→False on high-confidence expires, and the orchestrator can also fill in
          missing per-million-token prices for paid models.
        </p>
        <Toggle label="Use LLM to plan this run" value={!!cfg.agent.llm_orchestration_enabled}
                 onChange={(v) => setNested("agent", "llm_orchestration_enabled", v)}
                 hint="When on, the agent runs an extra plan→execute step on every cycle. Requires the Intelligence section above to be configured (a primary provider card). Off by default — the deterministic pipeline is the safe default." />
        <p className="dim" style={{ marginTop: 8, fontSize: 12 }}>
          Every orchestrator decision lands in <code className="mono">data/snapshot.json</code> as
          {" "}<code className="mono">Change(kind="verifier", text=...)</code>. Set the
          Intelligence section's "Auto-apply expire verdicts" off to keep the orchestrator
          strictly advisory.
        </p>
      </section>

      <section className="settings-block">
        <h2 className="section-title">Free detection</h2>
        <Field label="Free condition" hint="What counts as a free model.">
          <select value={cfg.free_detection.free_only_when} onChange={(e) => setNested("free_detection", "free_only_when", e.target.value)}>
            {FREE_WHEN.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
          </select>
        </Field>
        <Field label="Min dollar threshold" hint="Anything priced above this is treated as paid.">
          <input type="number" min="0" step="0.01"
                 value={cfg.free_detection.min_dollar_threshold}
                 onChange={(e) => setNested("free_detection", "min_dollar_threshold", parseFloat(e.target.value) || 0)} />
        </Field>
        <Toggle label="Respect b.ai pricing" value={cfg.free_detection.respect_b_ai_pricing}
                 onChange={(v) => setNested("free_detection", "respect_b_ai_pricing", v)}
                 hint="Models already carrying b.ai pricing are never flipped by the $0 cross-reference." />
        <Toggle label="Treat signup credits as free" value={cfg.free_detection.treat_credits_as_free}
                 onChange={(v) => setNested("free_detection", "treat_credits_as_free", v)} />
      </section>

      <section className="settings-block">
        <h2 className="section-title">Cheap flagships leaderboard</h2>
        <Field label="Max $/M output" hint="Exclude anything more expensive from the leaderboard.">
          <input type="number" min="0" step="0.5"
                 value={cfg.flagships.max_output_per_1m}
                 onChange={(e) => setNested("flagships", "max_output_per_1m", parseFloat(e.target.value) || 0)} />
        </Field>
        <Toggle label="Require tool-calling or vision" value={cfg.flagships.require_tool_calling_or_vision}
                 onChange={(v) => setNested("flagships", "require_tool_calling_or_vision", v)}
                 hint="If on, only models with real flagship capabilities make the board." />
      </section>

      <section className="settings-block">
        <h2 className="section-title">Data sources</h2>
        <p className="dim" style={{ margin: "0 0 12px", fontSize: 13 }}>
          Each source can be disabled or re-weighted. Weight is informational for now; the
          agent uses enabled/disabled to decide whether to call the source at all.
        </p>
        <table className="data-table settings-sources">
          <thead>
            <tr>
              <th>Source</th>
              <th>Description</th>
              <th className="col-check">Enabled</th>
              <th className="col-num">Weight</th>
            </tr>
          </thead>
          <tbody>
            {SOURCES.map((s) => (
              <tr key={s.key}>
                <td className="mono small">{s.label}</td>
                <td className="dim small">{s.desc}</td>
                <td className="col-check">
                  <input type="checkbox"
                         checked={!!cfg.sources[s.key]?.enabled}
                         onChange={(e) => setSource(s.key, "enabled", e.target.checked)} />
                </td>
                <td className="col-num">
                  <input type="number" min="0" step="0.1" style={{ width: 70 }}
                         value={cfg.sources[s.key]?.weight ?? 1.0}
                         onChange={(e) => setSource(s.key, "weight", parseFloat(e.target.value) || 0)} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="settings-block">
        <h2 className="section-title">Provider API keys</h2>
        <p className="dim" style={{ margin: "0 0 12px", fontSize: 13 }}>
          Many providers only reveal their model list (and free tier) through an
          authenticated <code className="mono">/v1/models</code>. Paste one key per
          provider here &mdash; signup is free on all of them. Keys are stored in
          {" "}<code className="mono">data/.provider-keys.json</code> (gitignored), never
          sent back to the browser, and never written to the public config. Environment
          variables of the same name take precedence (that&rsquo;s the CI/Vercel path).
          The next agent run uses them to fetch real model lists and 1-token-verify
          which models are free.
        </p>
        <div className="provider-keys-list">
          {providerKeyEnvs.map((env) => (
            <div key={env.env} className="provider-key-row">
              <label className="provider-key-label" htmlFor={`pk-${env.env}`}>
                <span className="mono small">{env.env}</span>
                <span className="dim small" style={{ marginLeft: 8 }}>{env.provider}</span>
                {env.signup ? (
                  <a className="small" style={{ marginLeft: 8 }} href={env.signup} target="_blank" rel="noreferrer">
                    details ↗
                  </a>
                ) : null}
              </label>
              <input
                id={`pk-${env.env}`}
                type="password"
                autoComplete="off"
                placeholder={providerKeysSaved[env.env]?.set
                  ? `saved: ${providerKeysSaved[env.env]?.masked}`
                  : "paste API key…"}
                style={{ flex: 1 }}
                onChange={(e) => setProviderKeyDrafts((d) => ({ ...d, [env.env]: e.target.value }))}
              />
              {providerKeysSaved[env.env]?.set ? <span className="badge badge-free">saved</span> : null}
            </div>
          ))}
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 14 }}>
          <button type="button" onClick={saveProviderKeys} disabled={providerKeysPending}>
            {providerKeysPending ? "saving…" : "save keys"}
          </button>
          {providerKeysSavedState === "ok" ? <span className="badge badge-free">keys saved</span> : null}
          {providerKeysSavedState === "err" ? (
            <span className="badge badge-needskey">{providerKeysErrMsg ?? "save failed"}</span>
          ) : null}
        </div>
      </section>

      <section className="settings-block">
        <h2 className="section-title">Intelligence (LLM verifier)</h2>
        <p className="dim" style={{ margin: "0 0 12px", fontSize: 13 }}>
          The agent can use an LLM to re-check claims the scrapers made &mdash;
          free-tier status, model identity, provider liveness. Add one or more
          provider cards below; pick which one is used for the primary and the
          cross-check pass. The API keys are stored in
          {" "}<code className="mono">data/.verifier-secrets.json</code> (gitignored) and
          never written to <code className="mono">data/config.json</code>.
        </p>

        <Toggle label="Enable the verifier" value={!!cfg.verifier.enabled}
                 onChange={(v) => setNested("verifier", "enabled", v)}
                 hint="When off, no LLM calls are made regardless of the rest of this section." />

        <div className="verifier-grid">
          {/* Left rail: provider cards */}
          <div className="verifier-rail">
            <div className="verifier-rail-label">Providers</div>
            {verifierProviders.length === 0 ? (
              <p className="dim" style={{ fontSize: 13, margin: "8px 0" }}>No providers configured yet.</p>
            ) : null}
            <ul className="verifier-card-list">
              {verifierProviders.map((p) => {
                const active =
                  editingProvider && editingProvider.name === p.name;
                return (
                  <li key={p.name}
                      className={"verifier-card" + (active ? " verifier-card-active" : "")}
                      onClick={() => setEditingProvider({ ...p })}>
                    <div className="verifier-card-name">{p.name}</div>
                    <div className="verifier-card-meta">
                      <span className="verifier-card-format">{p.api_format}</span>
                      <span className={"verifier-card-key " + (p.api_key_set ? "set" : "missing")}>
                        {p.api_key_set ? "key set" : "key missing"}
                      </span>
                    </div>
                    <div className="verifier-card-models dim small">
                      {(p.models || []).length} model{(p.models || []).length === 1 ? "" : "s"}
                    </div>
                  </li>
                );
              })}
            </ul>
            <button className="btn btn-ghost verifier-add-btn"
                    onClick={() => setEditingProvider({
                      name: "",
                      base_url: "https://api.openai.com/v1/chat/completions",
                      api_format: "openai",
                      api_key: "",
                      models: [],
                    })}>
              + Add provider
            </button>
          </div>

          {/* Right panel: add/edit form */}
          <div className="verifier-form">
            {editingProvider ? (
              <VerifierProviderEditor
                provider={editingProvider}
                onChange={setEditingProvider}
                onSave={async () => {
                  // "New" means the editor is creating a card — the server
                  // marks existing cards with `api_key_masked` after a GET,
                  // so absence of that field is the reliable signal.
                  const isNew = editingProvider.api_key_masked === undefined;
                  if (isNew && verifierProviders.some(
                    (p) => p.name.toLowerCase() === editingProvider.name.toLowerCase()
                  )) {
                    setVerifierErr("A provider with that name already exists.");
                    return;
                  }
                  const next = isNew
                    ? [...verifierProviders, { ...editingProvider }]
                    : verifierProviders.map((p) =>
                        p.name === editingProvider.name ? { ...editingProvider } : p
                      );
                  const ok = await saveVerifierProviders(next);
                  if (ok) {
                    // First card added? Auto-pick it as Primary so the user
                    // doesn't have to do it themselves. If the operator
                    // already has a primary set, leave their choice alone.
                    if (isNew && !cfg.verifier?.primary_provider) {
                      setNested("verifier", "primary_provider", editingProvider.name);
                    }
                    setEditingProvider(null);
                  }
                }}
                onDelete={async () => {
                  const deletedName = editingProvider.name;
                  const next = verifierProviders.filter(
                    (p) => p.name !== deletedName
                  );
                  const ok = await saveVerifierProviders(next);
                  if (ok) {
                    // If the deleted card was the primary or secondary,
                    // clear that slot so we never point at a missing card.
                    if (cfg.verifier?.primary_provider === deletedName) {
                      setNested("verifier", "primary_provider", "");
                    }
                    if (cfg.verifier?.secondary_provider === deletedName) {
                      setNested("verifier", "secondary_provider", "");
                    }
                    setEditingProvider(null);
                  }
                }}
                onCancel={() => setEditingProvider(null)}
              />
            ) : (
              <div className="verifier-empty">
                <p className="dim">Select a provider on the left, or click <strong>+ Add provider</strong> to create one.</p>
              </div>
            )}
            {verifierErr ? <p className="settings-err">{verifierErr}</p> : null}
            {verifierSaved === "ok" ? <p className="settings-ok">Provider saved.</p> : null}
          </div>
        </div>

        {/* Below the cards: pick which provider is primary / secondary. */}
        <div className="verifier-pickers">
          <Field label="Primary provider" hint="Used for the first pass of every verdict.">
            <select value={cfg.verifier.primary_provider || ""}
                    onChange={(e) => setNested("verifier", "primary_provider", e.target.value)}>
              <option value="">— None —</option>
              {verifierProviders.map((p) => (
                <option key={p.name} value={p.name}>{p.name}</option>
              ))}
            </select>
          </Field>
          <Field label="Secondary provider (cross-check)"
                 hint="Used for the second pass. Disagreement → verdict is marked disputed and never mutates the snapshot. Leave empty to use the same provider twice.">
            <select value={cfg.verifier.secondary_provider || ""}
                    onChange={(e) => setNested("verifier", "secondary_provider", e.target.value)}>
              <option value="">— Same as primary —</option>
              {verifierProviders.map((p) => (
                <option key={p.name} value={p.name}>{p.name}</option>
              ))}
            </select>
          </Field>
        </div>

        <Toggle label="Auto-apply expire verdicts" value={!!cfg.verifier.auto_apply_expire}
                 onChange={(v) => setNested("verifier", "auto_apply_expire", v)}
                 hint="If on, the verifier flips is_free: True → False on any model whose free tier it confirms expired. If off, all verdicts are advisory only &mdash; recorded in changelog, snapshot unchanged." />

        <Field label="Expire confidence threshold"
               hint="Auto-apply only happens when the verifier's confidence is at or above this value (0.0–1.0).">
          <input type="number" min="0" max="1" step="0.05" style={{ width: 100 }}
                 value={cfg.verifier.expire_confidence_threshold ?? 0.7}
                 onChange={(e) => {
                   const v = parseFloat(e.target.value);
                   setNested("verifier", "expire_confidence_threshold", Number.isFinite(v) ? v : 0.7);
                 }} />
        </Field>

        <p className="dim" style={{ marginTop: 12, fontSize: 12 }}>
          Trust rules: the verifier can only confirm what the public docs say.
          Every verdict must cite an evidence URL or it's marked unverified.
          Provider liveness verdicts never auto-remove or auto-rebrand &mdash;
          humans decide. The per-run budget is server-side
          (<code className="mono">OPENRADAR_VERIFIER_BUDGET_PER_RUN</code>, default 50).
        </p>
      </section>

      <section className="settings-block">
        <h2 className="section-title">UI</h2>
        <Toggle label="Show paid models on the provider detail page" value={cfg.ui.show_paid_models_on_provider_page}
                 onChange={(v) => setNested("ui", "show_paid_models_on_provider_page", v)} />
        <Field label="Models page default view" hint="grouped = one section per provider. flat = single table.">
          <select value={cfg.ui.models_page_view} onChange={(e) => setNested("ui", "models_page_view", e.target.value)}>
            <option value="grouped">Grouped by provider</option>
            <option value="flat">Single flat table</option>
          </select>
        </Field>
        <Field label="Highlight-stale threshold (days)" hint="Status dot turns amber after this many days, red after 7.">
          <input type="number" min="1" step="1"
                 value={cfg.ui.highlight_status_dot_threshold_days}
                 onChange={(e) => setNested("ui", "highlight_status_dot_threshold_days", parseInt(e.target.value) || 7)} />
        </Field>
      </section>

      <section className="settings-block">
        <h2 className="section-title">Notifications</h2>
        <p className="dim" style={{ margin: "0 0 12px", fontSize: 13 }}>
          Optional webhook URLs. POSTed with a small JSON payload when the named event fires.
        </p>
        <Field label="New provider webhook">
          <input type="url" placeholder="https://hooks.example.com/new-provider"
                 value={cfg.notifications.new_provider_webhook_url}
                 onChange={(e) => setNested("notifications", "new_provider_webhook_url", e.target.value)} />
        </Field>
        <Field label="Expired tier webhook">
          <input type="url" placeholder="https://hooks.example.com/expired"
                 value={cfg.notifications.expired_tier_webhook_url}
                 onChange={(e) => setNested("notifications", "expired_tier_webhook_url", e.target.value)} />
        </Field>
      </section>

      <div className="settings-actions">
        <button className="btn" onClick={save} disabled={saving}>
          {saving ? "Saving…" : "Save settings"}
        </button>
        <button className="btn btn-ghost" onClick={reset}>Reset to defaults</button>
        {saved === "ok" ? <span className="settings-ok">Saved.</span> : null}
        {saved === "err" ? <span className="settings-err">Failed: {errMsg}</span> : null}
      </div>
    </div>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="settings-field">
      <div className="settings-field-label">
        <span className="settings-field-name">{label}</span>
        {hint ? <span className="settings-field-hint">{hint}</span> : null}
      </div>
      <div className="settings-field-control">{children}</div>
    </div>
  );
}

function Toggle({ label, value, onChange, hint }: { label: string; value: boolean; onChange: (v: boolean) => void; hint?: string }) {
  return (
    <label className="settings-toggle">
      <span className="settings-toggle-label">
        <span className="settings-field-name">{label}</span>
        {hint ? <span className="settings-field-hint">{hint}</span> : null}
      </span>
      <input type="checkbox" checked={value} onChange={(e) => onChange(e.target.checked)} />
    </label>
  );
}


// ----- Intelligence: per-provider editor ----------------------------------

function VerifierProviderEditor({
  provider,
  onChange,
  onSave,
  onDelete,
  onCancel,
}: {
  provider: any;
  onChange: (p: any) => void;
  onSave: () => void;
  onDelete: () => void;
  onCancel: () => void;
}) {
  const [showKey, setShowKey] = useState(false);
  const isExisting = provider.api_key_masked !== undefined;  // server marks existing cards with a masked key
  const isNew = !isExisting;
  return (
    <div className="verifier-editor">
      <h3 className="verifier-editor-title">
        {isNew ? "Add model provider" : `Edit "${provider.name}"`}
      </h3>
      <p className="dim small" style={{ margin: "0 0 12px" }}>
        Configure a custom LLM endpoint and at least one model. The API key is
        stored in <code className="mono">data/.verifier-secrets.json</code> (gitignored)
        and never sent to the browser after save.
      </p>

      <Field label="Name" hint="Identifier used in the primary/secondary provider pickers below. Must be unique.">
        <input type="text" placeholder="e.g. openai-main"
               value={provider.name || ""}
               onChange={(e) => onChange({ ...provider, name: e.target.value })} />
      </Field>

      <Field label="Base URL" hint="Full URL of the chat-completions endpoint.">
        <input type="url" placeholder="https://api.openai.com/v1/chat/completions"
               value={provider.base_url || ""}
               onChange={(e) => onChange({ ...provider, base_url: e.target.value })} />
      </Field>

      <Field label="API format" hint="Affects the request shape. Most providers are OpenAI-compatible.">
        <select value={provider.api_format || "openai"}
                onChange={(e) => {
                  const fmt = e.target.value;
                  const next = { ...provider, api_format: fmt };
                  // Auto-fill the Base URL when the user picks a preset,
                  // but only if they haven't already customised it.
                  if (!provider.base_url || provider.base_url.startsWith("https://api.openai.com") || provider.base_url.startsWith("https://api.anthropic.com")) {
                    if (fmt === "openai") next.base_url = "https://api.openai.com/v1/chat/completions";
                    else if (fmt === "anthropic") next.base_url = "https://api.anthropic.com/v1/messages";
                  }
                  onChange(next);
                }}>
          <option value="openai">OpenAI Chat Completions (/v1/chat/completions)</option>
          <option value="anthropic">Anthropic Messages (/v1/messages)</option>
          <option value="custom">Custom (raw passthrough)</option>
        </select>
      </Field>

      <Field label="API key"
             hint={isExisting && provider.api_key_set
                   ? `Currently set: ${provider.api_key_masked}. Leave blank to keep, or paste a new key to replace.`
                   : "Paste the key from the provider's dashboard."}>
        <div style={{ display: "flex", gap: 6 }}>
          <input type={showKey ? "text" : "password"}
                 placeholder={isExisting && provider.api_key_set ? "(unchanged)" : "Enter API key"}
                 value={provider.api_key || ""}
                 onChange={(e) => onChange({ ...provider, api_key: e.target.value })}
                 style={{ flex: 1 }} />
          <button type="button" className="btn btn-ghost"
                  onClick={() => setShowKey((s) => !s)}>
            {showKey ? "Hide" : "Show"}
          </button>
        </div>
      </Field>

      <div className="verifier-models">
        <div className="settings-field-label" style={{ marginBottom: 6 }}>
          <span className="settings-field-name">Model list</span>
          <span className="settings-field-hint">At least one model is required before this provider can be used.</span>
        </div>
        {(provider.models || []).length === 0 ? (
          <p className="dim small" style={{ margin: "4px 0 8px" }}>
            <em>No models are configured. Add a model to use it in chat.</em>
          </p>
        ) : (
          <ul className="verifier-model-list">
            {(provider.models || []).map((m: any, idx: number) => (
              <li key={idx} className="verifier-model-row">
                <input type="text" placeholder="Display name (e.g. GPT-4o mini)"
                       value={m.name || ""}
                       onChange={(e) => {
                        const next = [...provider.models];
                        next[idx] = { ...next[idx], name: e.target.value };
                        onChange({ ...provider, models: next });
                       }} />
                <input type="text" placeholder="model_id (e.g. gpt-4o-mini)"
                       value={m.model_id || ""}
                       onChange={(e) => {
                        const next = [...provider.models];
                        next[idx] = { ...next[idx], model_id: e.target.value };
                        onChange({ ...provider, models: next });
                       }} />
                <button type="button" className="btn btn-ghost"
                        onClick={() => onChange({ ...provider, models: provider.models.filter((_: any, i: number) => i !== idx) })}>
                  ✕
                </button>
              </li>
            ))}
          </ul>
        )}
        <button type="button" className="btn btn-ghost verifier-add-model"
                onClick={() => onChange({ ...provider, models: [...(provider.models || []), { name: "", model_id: "" }] })}>
          + Add model
        </button>
      </div>

      <div className="verifier-editor-actions">
        <button className="btn" onClick={onSave}
                disabled={
                  !provider.name?.trim()
                  || !provider.base_url?.trim()
                  || (provider.models || []).length === 0
                  || !(provider.models || []).every((m: any) => m.name?.trim() && m.model_id?.trim())
                }
                title={(() => {
                  if (!provider.name?.trim()) return "Name is required";
                  if (!provider.base_url?.trim()) return "Base URL is required";
                  if ((provider.models || []).length === 0) return "Add at least one model";
                  if (!(provider.models || []).every((m: any) => m.name?.trim() && m.model_id?.trim()))
                    return "Every model needs both a display name and a model_id";
                  return "";
                })()}>
          {isNew ? "Add provider" : "Save"}
        </button>
        {!isNew ? (
          <button className="btn btn-ghost" onClick={onDelete}>Delete</button>
        ) : null}
        <button className="btn btn-ghost" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}
