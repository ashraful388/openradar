"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import type { CreditProvider, Provider } from "../lib/snapshot";

const FRICTION_LABELS: Record<string, string> = {
  email: "Email",
  phone: "Phone",
  github: "GitHub",
  trial_card: "Credit Card",
};

function fmtUsd(n: number): string {
  return n % 1 === 0 ? `$${n}` : `$${n.toFixed(2)}`;
}

function fmtExpiry(days: number | null): string {
  if (days == null) return "No expiry";
  if (days === 30) return "30 days";
  return `${days} days`;
}

function fmtFriction(f: string): string {
  return FRICTION_LABELS[f] || f;
}

export function CreditsTable({
  creditProviders,
  providers,
}: {
  creditProviders: CreditProvider[];
  providers: Record<string, Provider>;
}) {
  const [q, setQ] = useState("");
  const [sortKey, setSortKey] = useState<"bonus" | "expiry" | "friction" | "name" | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return creditProviders.filter((cp) => {
      if (!needle) return true;
      const hay = `${cp.name} ${cp.models_available.join(" ")} ${cp.notes}`.toLowerCase();
      return hay.includes(needle);
    });
  }, [creditProviders, q]);

  const sorted = useMemo(() => {
    if (!sortKey) return filtered;
    const dir = sortDir === "asc" ? 1 : -1;
    const rows = [...filtered];
    rows.sort((a, b) => {
      switch (sortKey) {
        case "name":
          return dir * a.name.localeCompare(b.name);
        case "bonus":
          return dir * (a.signup_bonus_usd - b.signup_bonus_usd);
        case "expiry": {
          const av = a.credit_expiry_days ?? Number.POSITIVE_INFINITY;
          const bv = b.credit_expiry_days ?? Number.POSITIVE_INFINITY;
          return dir * (av - bv);
        }
        case "friction":
          return dir * a.signup_friction.localeCompare(b.signup_friction);
        default:
          return 0;
      }
    });
    return rows;
  }, [filtered, sortKey, sortDir]);

  const handleSort = (key: "bonus" | "expiry" | "friction" | "name") => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  };

  const SortIcon = ({ key, label }: { key: "bonus" | "expiry" | "friction" | "name"; label: string }) => (
    <button className="sort-btn" onClick={() => handleSort(key)} aria-label={`Sort by ${label}`}>
      {label}
      {sortKey === key && (
        <span className="sort-arrow">{sortDir === "asc" ? "▲" : "▼"}</span>
      )}
    </button>
  );

  return (
    <div className="credits-table-wrap">
      <div className="table-toolbar">
        <input
          type="search"
          placeholder="Search providers, models, notes…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          className="search-input"
          aria-label="Search credit providers"
        />
      </div>

      <div className="table-scroll">
        <table className="data-table credits-table">
          <thead>
            <tr>
              <th scope="col"><SortIcon key="name" label="Provider" /></th>
              <th scope="col"><SortIcon key="bonus" label="Signup Bonus" /></th>
              <th scope="col"><SortIcon key="expiry" label="Expires" /></th>
              <th scope="col"><SortIcon key="friction" label="Signup" /></th>
              <th scope="col">Models Available</th>
              <th scope="col">Notes</th>
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 ? (
              <tr>
                <td colSpan={6} className="empty-state">
                  No credit providers match your search.
                </td>
              </tr>
            ) : (
              sorted.map((cp) => {
                const provider = providers[cp.provider_id];
                return (
                  <tr key={cp.provider_id}>
                    <td className="provider-cell">
                      {provider ? (
                        <Link href={`/providers/${provider.slug}`} className="provider-link">
                          {cp.name}
                        </Link>
                      ) : (
                        cp.name
                      )}
                    </td>
                    <td className="bonus-cell">{fmtUsd(cp.signup_bonus_usd)}</td>
                    <td className="expiry-cell">{fmtExpiry(cp.credit_expiry_days)}</td>
                    <td className="friction-cell">
                      <span className={`friction-badge friction-${cp.signup_friction}`}>
                        {fmtFriction(cp.signup_friction)}
                      </span>
                    </td>
                    <td className="models-cell">
                      <ul className="model-list">
                        {cp.models_available.map((m, i) => (
                          <li key={i}>{m}</li>
                        ))}
                      </ul>
                    </td>
                    <td className="notes-cell">
                      <a href={cp.homepage} target="_blank" rel="noopener noreferrer" className="notes-link">
                        {cp.notes}
                      </a>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      <p className="table-footnote">
        Showing {sorted.length} of {creditProviders.length} credit providers.
        Data sourced from provider marketing pages and community reports — verify
        current offers before signing up.
      </p>
    </div>
  );
}