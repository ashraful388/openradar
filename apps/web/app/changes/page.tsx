import { getSnapshot } from "../../lib/snapshot";

export const dynamic = "force-static";

export default async function ChangesPage() {
  const snap = await getSnapshot();
  return (
    <div className="page narrow">
      <p className="kicker">Activity log</p>
      <h1 className="display">What changed</h1>
      <p className="lede">
        The discovery agent runs every 10 hours. Every new free offer, expired tier, and pricing
        change is logged here. If a row is older than 7 days, the system has gone quiet.
      </p>
      <ol className="changelog changelog-list">
        {snap.changelog.map((c, i) => (
          <li key={i} className={`changelog-row changelog-${c.kind}`}>
            <time className="changelog-time mono">{new Date(c.at).toISOString().replace("T", " ").slice(0, 16)} UTC</time>
            <span className="changelog-kind">{c.kind}</span>
            <span className="changelog-text">{c.text}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}
