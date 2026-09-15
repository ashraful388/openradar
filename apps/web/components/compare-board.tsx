"use client";

import { useEffect, useState } from "react";
import type { Model, Provider } from "../lib/snapshot";
import { CopyCurl } from "./copy-curl";

export function CompareBoard({
  models,
  providers,
}: {
  models: Model[];
  providers: Record<string, Provider>;
}) {
  const [ids, setIds] = useState<string[]>([]);

  useEffect(() => {
    const sp = new URLSearchParams(window.location.search);
    const raw = sp.get("ids");
    if (raw) setIds(raw.split(",").filter(Boolean).slice(0, 4));
  }, []);

  const selected = ids.map((id) => models.find((m) => m.id === id)).filter(Boolean) as Model[];

  function add(id: string) {
    if (ids.length >= 4) return;
    if (ids.includes(id)) return;
    setIds([...ids, id]);
  }
  function remove(id: string) {
    setIds(ids.filter((x) => x !== id));
  }

  return (
    <div className="compare">
      <div className="compare-picker">
        <label>
          <span>Add a model (max 4)</span>
          <select
            onChange={(e) => {
              if (e.target.value) add(e.target.value);
              e.target.value = "";
            }}
            defaultValue=""
          >
            <option value="" disabled>
              pick a model…
            </option>
            {models
              .filter((m) => !ids.includes(m.id))
              .map((m) => (
                <option key={m.id} value={m.id}>
                  {m.display_name} · {providers[m.provider_id]?.name}
                </option>
              ))}
          </select>
        </label>
      </div>

      {selected.length === 0 ? (
        <p className="dim">Pick up to four models to compare.</p>
      ) : (
        <div className="compare-grid" style={{ gridTemplateColumns: `repeat(${selected.length}, 1fr)` }}>
          {selected.map((m) => {
            const p = providers[m.provider_id];
            return (
              <article key={m.id} className="compare-col">
                <header>
                  <h3>{m.display_name}</h3>
                  <p className="dim">{p?.name}</p>
                  <button className="link-btn" onClick={() => remove(m.id)}>
                    remove
                  </button>
                </header>
                <dl>
                  <div>
                    <dt>Modality</dt>
                    <dd>{m.modality.join(", ")}</dd>
                  </div>
                  <div>
                    <dt>Context</dt>
                    <dd className="mono">{m.context_window ? m.context_window.toLocaleString() : "—"}</dd>
                  </div>
                  <div>
                    <dt>Free kind</dt>
                    <dd>{m.free_kind}</dd>
                  </div>
                  <div>
                    <dt>Limits</dt>
                    <dd>{m.free_limit || "—"}</dd>
                  </div>
                  <div>
                    <dt>API base</dt>
                    <dd className="mono small">{p?.api_base || "—"}</dd>
                  </div>
                </dl>
                {p?.openai_compatible && p.api_base ? (
                  <CopyCurl base={p.api_base} model={m.model_id} apiKeyEnv={p.api_key_env} />
                ) : null}
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}
