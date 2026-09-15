import Link from "next/link";
import { getSnapshot } from "../lib/snapshot";
import { ProvidersGrid } from "../components/providers-grid";
import { LastUpdated } from "../components/last-updated";

export const dynamic = "force-static";

export default async function HomePage() {
  const snap = await getSnapshot();
  const totalFree = snap.providers.reduce((acc, p) => acc + p.free_model_count, 0);
  const totalPriced = snap.models.filter((m) => m.input_per_1m != null && m.output_per_1m != null).length;
  const totalModels = snap.models.length;

  return (
    <div className="page">
      <section className="hero">
        <p className="kicker">A reference for the open AI economy</p>
        <h1 className="display">
          Every free AI model API, <br />
          and the flagships that <em>aren&rsquo;t</em> priced fortresses.
        </h1>
        <p className="lede">
          {snap.providers.length} providers, {totalFree} free model endpoints and
          {" "}{totalModels - totalFree} paid models with prices ({totalPriced} of them priced).
          {" "}The directory below is the full list &mdash; search and filter to find what you need.
        </p>
        <LastUpdated at={snap.snapshot_at} />
        <p className="hero-aux">
          Need just the <Link href="/api-providers">full API providers directory</Link>,
          a flat <Link href="/models">model table</Link>, or the{" "}
          <Link href="/cheap-flagships">cheap-flagships leaderboard</Link>?
        </p>
      </section>

      <section className="row">
        <div className="row-label">
          <span className="row-num">01</span>
          <h2 className="row-title">API Providers</h2>
          <p className="row-meta">
            Search by name, filter by region or signup friction. Click a provider for limits,
            catches, and a copy-pasteable curl.
          </p>
          <p className="row-foot">
            <Link href="/api-providers">open the full directory &rarr;</Link>
          </p>
        </div>
        <div className="row-body">
          <ProvidersGrid providers={snap.providers} />
        </div>
      </section>

      <section className="row">
        <div className="row-label">
          <span className="row-num">02</span>
          <h2 className="row-title">What changed today</h2>
          <p className="row-meta">
            New free offers, expired tiers, and pricing edits from the last agent run.
          </p>
        </div>
        <div className="row-body">
          <ul className="changelog">
            {snap.changelog.slice(0, 8).map((c, i) => (
              <li key={i} className={`changelog-row changelog-${c.kind}`}>
                <span className="changelog-time">{formatTime(c.at)}</span>
                <span className="changelog-text">{c.text}</span>
              </li>
            ))}
          </ul>
          <p className="row-foot">
            <Link href="/changes">Full changelog &rarr;</Link>
          </p>
        </div>
      </section>
    </div>
  );
}

function formatTime(iso: string) {
  const d = new Date(iso);
  return d.toISOString().slice(11, 16) + " UTC";
}
