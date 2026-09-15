import { getSnapshot } from "../../lib/snapshot";
import { ProvidersGrid } from "../../components/providers-grid";

export const dynamic = "force-static";

export const metadata = {
  title: "API Providers — OpenRadar",
  description:
    "Every provider that offers a free AI model API. Search by name, filter by region or signup friction.",
};

export default async function ApiProvidersPage() {
  const snap = await getSnapshot();
  const totalFree = snap.providers.reduce((acc, p) => acc + p.free_model_count, 0);

  return (
    <div className="page providers-page">
      <header className="providers-header">
        <p className="kicker">The directory</p>
        <h1 className="display">API Providers</h1>
        <p className="lede">
          {snap.providers.length} providers, {totalFree} free model endpoints. Search by name,
          filter by region or signup friction. Click a provider for limits, catches, and a
          copy-pasteable curl.
        </p>
      </header>
      <ProvidersGrid providers={snap.providers} />
    </div>
  );
}
