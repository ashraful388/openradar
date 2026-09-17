"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import type { Provider } from "../lib/snapshot";
import { StatusDot } from "./status-dot";

export function ProvidersGrid({ providers, coverage }: {
  providers: Provider[];
  coverage?: Record<string, { listed: number; unknownTier: number }>;
}) {
  const [q, setQ] = useState("");
  const [region, setRegion] = useState("");
  const [friction, setFriction] = useState("");

  const regions = useMemo(() => {
    const set = new Set<string>(providers.map((p) => p.region).filter(Boolean));
    return Array.from(set).sort();
  }, [providers]);
  const frictions = useMemo(() => {
    const set = new Set<string>(providers.map((p) => p.signup_friction).filter(Boolean));
    return Array.from(set).sort();
  }, [providers]);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return providers.filter((p) => {
      if (region && p.region !== region) return false;
      if (friction && p.signup_friction !== friction) return false;
      if (!needle) return true;
      const hay = `${p.name} ${p.tagline} ${p.notes} ${p.api_base}`.toLowerCase();
      return hay.includes(needle);
    });
  }, [providers, q, region, friction]);

  return (
    <div className="providers-wrap">
      <div className="providers-filters">
        <input
          className="search"
          placeholder="search providers…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          aria-label="Search providers"
        />
        <select
          value={region}
          onChange={(e) => setRegion(e.target.value)}
          aria-label="Filter by region"
        >
          <option value="">all regions</option>
          {regions.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
        <select
          value={friction}
          onChange={(e) => setFriction(e.target.value)}
          aria-label="Filter by signup friction"
        >
          <option value="">all signup types</option>
          {frictions.map((f) => (
            <option key={f} value={f}>
              {f}
            </option>
          ))}
        </select>
        <span className="providers-count dim">
          {filtered.length} of {providers.length}
        </span>
      </div>

      {filtered.length === 0 ? (
        <p className="dim empty">No providers match. Try a broader filter.</p>
      ) : (
        <div className="provider-grid">
          {filtered.map((p) => (
            <Link key={p.id} href={`/providers/${p.slug}`} className="provider-card">
              <div className="provider-card-head">
                <h3 className="provider-name">{p.name}</h3>
                <StatusDot verifiedAt={p.last_verified} />
              </div>
              <p className="provider-tagline">{p.tagline}</p>
              {p.homepage ? (
                <p className="provider-host mono small dim">
                  {p.homepage.replace(/^https?:\/\//, "")}
                </p>
              ) : null}
              <dl className="provider-stats">
                <div>
                  <dt>Region</dt>
                  <dd>{p.region}</dd>
                </div>
                <div>
                  <dt>Free models</dt>
                  <dd className={p.free_model_count === 0 ? "dim" : "free-count"}>
                    {p.free_model_count === 0 && (p.probe_status !== "ok" || !coverage?.[p.id]?.listed || coverage[p.id].unknownTier > 0) ? (
                      <span
                        className="badge badge-needskey"
                        title="Free count is unknown, not zero: the live catalog or free-tier evidence is incomplete."
                      >
                        unknown
                      </span>
                    ) : (
                      `${p.free_model_count} ${p.probe_status === "ok" ? "known" : "reported"}`
                    )}
                  </dd>
                </div>
                <div>
                  <dt>Modalities</dt>
                  <dd>{p.modalities.slice(0, 3).join(" · ")}</dd>
                </div>
                <div>
                  <dt>Signup</dt>
                  <dd>{p.signup_friction}</dd>
                </div>
              </dl>
              <p className="small dim">
                Not a complete model list.{p.probe_status !== "ok" ? " No successful live catalog check." : " Free-tier evidence may be partial."}
                {coverage?.[p.id] ? ` ${coverage[p.id].listed} listed; ${coverage[p.id].unknownTier} with unknown tier.` : ""}
              </p>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
