"use client";

import { useMemo, useState } from "react";
import type { CheapFlagship } from "../lib/snapshot";

export function FlagshipsTable({ flagships }: { flagships: CheapFlagship[] }) {
  const [q, setQ] = useState("");

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return flagships;
    return flagships.filter(
      (f) =>
        f.display_name.toLowerCase().includes(needle) ||
        f.model_id.toLowerCase().includes(needle) ||
        f.provider.toLowerCase().includes(needle)
    );
  }, [flagships, q]);

  return (
    <div>
      <div className="filters" style={{ marginBottom: 16 }}>
        <input
          className="search"
          placeholder="search flagships by model or provider…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <span className="dim" style={{ fontSize: 13 }}>
          {filtered.length} of {flagships.length}
        </span>
      </div>

      <table className="data-table">
        <thead>
          <tr>
            <th className="col-rank">#</th>
            <th>Model</th>
            <th>Provider</th>
            <th className="col-num">$ / M in</th>
            <th className="col-num">$ / M out</th>
            <th className="col-num">Context</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((f) => (
            <tr key={`${f.provider}-${f.model_id}`}>
              <td className="col-rank mono">{f.rank}</td>
              <td>
                <div className="cell-name">{f.display_name}</div>
                <div className="cell-id mono dim">{f.model_id}</div>
              </td>
              <td className="dim">{f.provider}</td>
              <td className="col-num mono">${f.input_per_1m.toFixed(3)}</td>
              <td className="col-num mono">${f.output_per_1m.toFixed(3)}</td>
              <td className="col-num mono dim">{(f.context_window ?? 0).toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {filtered.length === 0 ? (
        <p className="dim empty">No matches. Try a different search.</p>
      ) : null}
    </div>
  );
}
