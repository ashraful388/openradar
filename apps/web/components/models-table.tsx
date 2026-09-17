"use client";

import { Fragment, useMemo, useState } from "react";
import Link from "next/link";
import type { Model, Provider } from "../lib/snapshot";

const ALL_MODALITIES = ["chat", "embedding", "image", "audio_tts", "audio_stt", "video", "rerank", "vision", "code", "ocr"];
const COMPARE_CAP = 4;

type SortKey = "model" | "provider" | "modality" | "context" | "pricing" | "free";
type SortDir = "asc" | "desc";

const SORT_COLUMNS: { key: SortKey; label: string; numeric?: boolean }[] = [
  { key: "model", label: "Model" },
  { key: "provider", label: "Provider" },
  { key: "modality", label: "Modality" },
  { key: "context", label: "Context", numeric: true },
  { key: "free", label: "Free?" },
  { key: "pricing", label: "Pricing (in / out per 1M)", numeric: true },
];

function priceOf(m: Model): number | null {
  if (m.input_per_1m == null || m.output_per_1m == null) return null;
  return m.input_per_1m + m.output_per_1m;
}

export function ModelsTable({
  models,
  providers,
}: {
  models: Model[];
  providers: Record<string, Provider>;
}) {
  const [q, setQ] = useState("");
  const [providerId, setProviderId] = useState("");
  const [mods, setMods] = useState<Set<string>>(new Set());
  const [onlyFree, setOnlyFree] = useState(false);
  const [onlyPriced, setOnlyPriced] = useState(false);
  const [compare, setCompare] = useState<Set<string>>(new Set());
  const [sortKey, setSortKey] = useState<SortKey | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>("asc");

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return models.filter((m) => {
      if (onlyFree && !m.is_free) return false;
      if (onlyPriced && (m.is_free || !((m.input_per_1m ?? 0) > 0 || (m.output_per_1m ?? 0) > 0))) return false;
      if (providerId && m.provider_id !== providerId) return false;
      if (mods.size > 0 && !m.modality.some((x) => mods.has(x))) return false;
      if (needle) {
        const hay = `${m.display_name} ${m.model_id} ${providers[m.provider_id]?.name ?? ""}`.toLowerCase();
        if (!hay.includes(needle)) return false;
      }
      return true;
    });
  }, [models, q, providerId, mods, onlyFree, onlyPriced, providers]);

  const sorted = useMemo(() => {
    if (!sortKey) return filtered;
    const dir = sortDir === "asc" ? 1 : -1;
    const rows = [...filtered];
    rows.sort((a, b) => {
      switch (sortKey) {
        case "model":
          return dir * a.display_name.localeCompare(b.display_name);
        case "provider":
          return dir * (providers[a.provider_id]?.name ?? "").localeCompare(providers[b.provider_id]?.name ?? "");
        case "modality":
          return dir * (a.modality.join(",")).localeCompare(b.modality.join(","));
        case "context": {
          const av = a.context_window ?? Number.POSITIVE_INFINITY;
          const bv = b.context_window ?? Number.POSITIVE_INFINITY;
          return dir * (av - bv);
        }
        case "pricing": {
          const av = priceOf(a) ?? Number.POSITIVE_INFINITY;
          const bv = priceOf(b) ?? Number.POSITIVE_INFINITY;
          return dir * (av - bv);
        }
        case "free": {
          const rank = (m: Model) => (m.is_free ? (m.free_evidence_source !== "docs" && m.free_verified_at ? 0 : 1) : 2);
          return dir * (rank(a) - rank(b));
        }
        default:
          return 0;
      }
    });
    return rows;
  }, [filtered, sortKey, sortDir, providers]);

  // Group by provider so the table can show section headers. When the
  // sort key is "provider", sections follow the sorted model order.
  const grouped = useMemo(() => {
    const m = new Map<string, Model[]>();
    for (const row of sorted) {
      if (!m.has(row.provider_id)) m.set(row.provider_id, []);
      m.get(row.provider_id)!.push(row);
    }
    const entries = Array.from(m.entries());
    if (sortKey === "provider") return entries;
    return entries.sort((a, b) =>
      (providers[a[0]]?.name ?? a[0]).localeCompare(providers[b[0]]?.name ?? b[0])
    );
  }, [sorted, sortKey, providers]);

  function toggleSort(key: SortKey) {
    if (sortKey !== key) {
      setSortKey(key);
      setSortDir("asc");
    } else if (sortDir === "asc") {
      setSortDir("desc");
    } else {
      setSortKey(null);
      setSortDir("asc");
    }
  }

  function toggleMod(m: string) {
    const next = new Set(mods);
    if (next.has(m)) next.delete(m);
    else next.add(m);
    setMods(next);
  }

  function toggleCompare(id: string) {
    const next = new Set(compare);
    if (next.has(id)) next.delete(id);
    else if (next.size < COMPARE_CAP) next.add(id);
    setCompare(next);
  }

  function toggleSelectAll() {
    if (compare.size > 0) {
      setCompare(new Set());
      return;
    }
    // Fill the compare tray with the top of the current (sorted) view.
    const next = new Set<string>();
    for (const m of sorted) {
      if (next.size >= COMPARE_CAP) break;
      next.add(m.id);
    }
    setCompare(next);
  }

  const allSelected = compare.size > 0;
  const totalShown = filtered.length;

  return (
    <div className="models">
      <div className="filters">
        <input
          className="search"
          placeholder="search model id, name, or provider…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <select
          value={providerId}
          onChange={(e) => setProviderId(e.target.value)}
          aria-label="Filter by provider"
        >
          <option value="">all providers</option>
          {Object.values(providers)
            .sort((a, b) => a.name.localeCompare(b.name))
            .map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
        </select>
      </div>
      <div className="filters chips-row">
        <div className="toggle-group" role="group" aria-label="Tier filters">
          <span
            className={`toggle-row ${onlyFree ? "toggle-on" : ""}`}
            role="switch"
            aria-checked={onlyFree}
            tabIndex={0}
            onClick={() => setOnlyFree((v) => !v)}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setOnlyFree((v) => !v); } }}
          >
            <span className="toggle-switch"><span className="toggle-knob" /></span>
            <span>Free Model</span>
          </span>
          <span
            className={`toggle-row ${onlyPriced ? "toggle-on" : ""}`}
            role="switch"
            aria-checked={onlyPriced}
            tabIndex={0}
            onClick={() => setOnlyPriced((v) => !v)}
            onKeyDown={(e) => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); setOnlyPriced((v) => !v); } }}
          >
            <span className="toggle-switch"><span className="toggle-knob" /></span>
            <span>Paid Model</span>
          </span>
        </div>
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

      {compare.size > 0 ? (
        <p className="compare-hint">
          {compare.size} model{compare.size > 1 ? "s" : ""} selected for compare.{" "}
          <a href={`/compare?ids=${Array.from(compare).join(",")}`}>open compare view &rarr;</a>
        </p>
      ) : null}

      <p className="dim models-count">
        {totalShown} model{totalShown === 1 ? "" : "s"} across {grouped.length} provider
        {grouped.length === 1 ? "" : "s"}.
      </p>

      <table className="data-table">
        <thead>
          <tr>
            <th className="col-check">
              <input
                type="checkbox"
                checked={allSelected}
                ref={(el) => {
                  if (el) el.indeterminate = false;
                }}
                onChange={toggleSelectAll}
                aria-label="Select models for compare"
                title={`Select the first ${COMPARE_CAP} of the current view for compare (click again to clear)`}
              />
            </th>
            {SORT_COLUMNS.map((c) => (
              <th key={c.key} className={c.numeric ? "col-num sortable" : "sortable"}>
                <button type="button" className="sort-btn" onClick={() => toggleSort(c.key)}>
                  {c.label}
                  <span className="sort-arrow dim">
                    {sortKey === c.key ? (sortDir === "asc" ? " ▲" : " ▼") : " ↕"}
                  </span>
                </button>
              </th>
            ))}
            <th>Limits</th>
          </tr>
        </thead>
        <tbody>
          {grouped.map(([pid, rows]) => {
            const p = providers[pid];
            return (
              <Fragment key={pid}>
                <tr className="section-header">
                  <td colSpan={8}>
                    <Link href={`/providers/${p?.slug ?? ""}`} className="section-link">
                      {p?.name ?? pid} <span className="dim">· {rows.length} model{rows.length === 1 ? "" : "s"}</span>
                    </Link>
                  </td>
                </tr>
                {rows.map((m) => (
                  <tr key={m.id} className="row-link">
                    <td className="col-check">
                      <input
                        type="checkbox"
                        checked={compare.has(m.id)}
                        onChange={() => toggleCompare(m.id)}
                      />
                    </td>
                    <td>
                      <Link href={`/providers/${p?.slug ?? ""}#${m.id}`} className="cell-link">
                        <div className="cell-name">{m.display_name}</div>
                        <div className="cell-id mono dim">{m.model_id}</div>
                      </Link>
                    </td>
                    <td className="dim">{p?.name ?? m.provider_id}</td>
                    <td>
                      <div className="cell-modalities">
                        {m.modality.map((x) => (
                          <span key={x} className="modality-pill">
                            {x}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="col-num mono dim">
                      {m.context_window ? m.context_window.toLocaleString() : "—"}
                    </td>
                    <td>
                      {m.is_free ? (
                        <span
                          className={`badge ${m.free_evidence_source !== "docs" && m.free_verified_at ? "badge-free-verified" : "badge-free"}`}
                          title={m.free_evidence_source === "docs"
                            ? "Documented free; not live verified"
                            : m.free_verified_at
                              ? `Verified free by a live 1-token probe on ${m.free_verified_at.slice(0, 10)}`
                              : m.free_limit || "Free per reported sources"}
                        >
                          {m.free_evidence_source === "docs" ? "documented free" : m.free_verified_at ? "free ✓" : "free"}
                        </span>
                      ) : (m.input_per_1m ?? 0) > 0 || (m.output_per_1m ?? 0) > 0 ? (
                        <span className="badge badge-paid">paid</span>
                      ) : (
                        <span className="dim">unverified</span>
                      )}
                    </td>
                    <td className="col-num mono dim">
                      {`${m.input_per_1m == null ? "?" : `$${m.input_per_1m.toFixed(2)}`} / ${m.output_per_1m == null ? "?" : `$${m.output_per_1m.toFixed(2)}`}`}
                    </td>
                    <td className="dim">{m.free_limit || "—"}</td>
                  </tr>
                ))}
              </Fragment>
            );
          })}
        </tbody>
      </table>
      {totalShown === 0 ? <p className="dim empty">Nothing matches. Loosen the filters.</p> : null}
    </div>
  );
}
