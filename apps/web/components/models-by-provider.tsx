"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import type { Model, Provider } from "../lib/snapshot";

const ALL_MODALITIES = ["chat", "embedding", "image", "audio_tts", "audio_stt", "video", "rerank", "vision", "code", "ocr"];

export function ModelsByProvider({
  models,
  providers,
}: {
  models: Model[];
  providers: Record<string, Provider>;
}) {
  const [q, setQ] = useState("");
  const [mods, setMods] = useState<Set<string>>(new Set());
  const [onlyFree, setOnlyFree] = useState(true);
  const [openSet, setOpenSet] = useState<Set<string>>(new Set());

  const providerList = useMemo(
    () => Object.values(providers).sort((a, b) => a.name.localeCompare(b.name)),
    [providers]
  );

  const filteredByProvider = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const result: Record<string, Model[]> = {};
    for (const p of providerList) {
      const rows = models.filter((m) => {
        if (m.provider_id !== p.id) return false;
        if (onlyFree && !m.is_free) return false;
        if (mods.size > 0 && !m.modality.some((x) => mods.has(x))) return false;
        if (needle) {
          const hay = `${m.display_name} ${m.model_id} ${p.name}`.toLowerCase();
          if (!hay.includes(needle)) return false;
        }
        return true;
      });
      if (rows.length) result[p.id] = rows;
    }
    return result;
  }, [providerList, models, q, mods, onlyFree]);

  function toggleMod(m: string) {
    const next = new Set(mods);
    if (next.has(m)) next.delete(m);
    else next.add(m);
    setMods(next);
  }

  function toggleSection(pid: string) {
    const next = new Set(openSet);
    if (next.has(pid)) next.delete(pid);
    else next.add(pid);
    setOpenSet(next);
  }

  const totalShown = Object.values(filteredByProvider).reduce((a, b) => a + b.length, 0);
  const providerCount = Object.keys(filteredByProvider).length;

  return (
    <div className="models">
      <div className="filters">
        <input
          className="search"
          placeholder="search model id, name, or provider…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <label className="check">
          <input type="checkbox" checked={onlyFree} onChange={(e) => setOnlyFree(e.target.checked)} />
          free only
        </label>
        <div className="chips">
          {ALL_MODALITIES.map((m) => (
            <button
              key={m}
              type="button"
              className={`chip ${mods.has(m) ? "chip-on" : ""}`}
              onClick={() => toggleMod(m)}
            >
              {m}
            </button>
          ))}
        </div>
      </div>

      <p className="dim" style={{ margin: "0 0 24px" }}>
        {totalShown} free model{totalShown === 1 ? "" : "s"} across {providerCount} provider
        {providerCount === 1 ? "" : "s"}. Click a provider heading to open its full detail page; each
        row also links to the same page with that model in context.
      </p>

      {Object.entries(filteredByProvider).map(([pid, rows]) => {
        const p = providers[pid];
        if (!p) return null;
        const isOpen = openSet.size === 0 || openSet.has(pid);
        return (
          <section key={pid} className="provider-section">
            <header className="provider-section-head">
              <button
                type="button"
                className="disclosure"
                aria-expanded={isOpen}
                onClick={() => toggleSection(pid)}
              >
                <span className="caret">{isOpen ? "▾" : "▸"}</span>
                <h2 className="provider-section-name">{p.name}</h2>
              </button>
              <span className="provider-section-meta dim">
                {rows.length} model{rows.length === 1 ? "" : "s"} · {p.region}
              </span>
              <Link href={`/providers/${p.slug}`} className="provider-section-link">
                open provider →
              </Link>
            </header>
            {isOpen ? (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Model</th>
                    <th>Model ID</th>
                    <th>Modality</th>
                    <th className="col-num">Context</th>
                    <th>Limits</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((m) => (
                    <tr key={m.id} className="row-link">
                      <td>
                        <Link
                          href={`/providers/${p.slug}#${m.id}`}
                          className="cell-link"
                        >
                          {m.display_name}
                        </Link>
                        {m.is_free ? (
                          <span
                            className={`badge ${m.free_verified_at ? "badge-free-verified" : "badge-free"}`}
                            title={m.free_verified_at
                              ? `Verified free by a live 1-token probe on ${m.free_verified_at.slice(0, 10)}`
                              : "Free per docs/community sources"}
                          >
                            free
                          </span>
                        ) : null}
                      </td>
                      <td>
                        <Link
                          href={`/providers/${p.slug}#${m.id}`}
                          className="cell-link mono small"
                        >
                          {m.model_id}
                        </Link>
                      </td>
                      <td>{m.modality.join(", ")}</td>
                      <td className="col-num mono dim">
                        {m.context_window ? m.context_window.toLocaleString() : "—"}
                      </td>
                      <td className="dim">{m.free_limit || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : null}
          </section>
        );
      })}

      {providerCount === 0 ? (
        <p className="dim empty">Nothing matches. Loosen the filters.</p>
      ) : null}
    </div>
  );
}
