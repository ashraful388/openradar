import { CompareBoard } from "../../components/compare-board";
import { getSnapshot } from "../../lib/snapshot";

export const dynamic = "force-static";

export default async function ComparePage() {
  const snap = await getSnapshot();
  return (
    <div className="page">
      <p className="kicker">Side by side</p>
      <h1 className="display">Compare</h1>
      <p className="lede">
        Pick two to four free models and see their limits, context windows, and curl snippets next
        to each other. Use this when you&rsquo;re choosing which endpoint to wire into a project.
      </p>
      <CompareBoard
        models={snap.models}
        providers={Object.fromEntries(snap.providers.map((p) => [p.id, p]))}
      />
    </div>
  );
}
