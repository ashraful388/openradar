import { getSnapshot } from "../../lib/snapshot";
import { FlagshipsTable } from "../../components/flagships-table";

export const dynamic = "force-static";

export default async function CheapFlagshipsPage() {
  const snap = await getSnapshot();
  return (
    <div className="page">
      <p className="kicker">Frontier-class, not frontier-priced</p>
      <h1 className="display">Cheap flagships</h1>
      <p className="lede">
        Paid models that are still considered frontier or near-frontier, ranked by absolute price.
        When free is too small and enterprise is too rich. Search by model or provider.
      </p>
      <FlagshipsTable flagships={snap.cheap_flagships} />
    </div>
  );
}
