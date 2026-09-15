import { getSnapshot } from "../../lib/snapshot";
import { CreditsTable } from "../../components/credits-table";

export const dynamic = "force-static";

export default async function CreditsPage() {
  const snap = await getSnapshot();
  return (
    <div className="page">
      <p className="kicker">Providers with free signup credits</p>
      <h1 className="display">Free Credits</h1>
      <p className="lede">
        These providers don&rsquo;t offer permanently free inference, but give you
        a one-time (or recurring) credit balance when you sign up. Use them to
        try paid models at no cost — then decide if you want to continue.
        {snap.credit_providers.length} providers tracked.
      </p>
      <CreditsTable
        creditProviders={snap.credit_providers}
        providers={Object.fromEntries(snap.providers.map((p) => [p.id, p]))}
      />
    </div>
  );
}