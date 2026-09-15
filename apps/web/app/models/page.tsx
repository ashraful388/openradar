import { getSnapshot } from "../../lib/snapshot";
import { ModelsTable } from "../../components/models-table";

export const dynamic = "force-static";

export default async function ModelsPage() {
  const snap = await getSnapshot();
  const free = snap.models.filter((m) => m.is_free).length;
  const paid = snap.models.length - free;
  const priced = snap.models.filter((m) => m.input_per_1m != null && m.output_per_1m != null).length;
  return (
    <div className="page">
      <p className="kicker">Every model we know about, in one table</p>
      <h1 className="display">Models</h1>
      <p className="lede">
        {free} free and {paid} paid model endpoints across {snap.providers.length} providers.
        {" "}{priced} have explicit per-million-token pricing. Use the filters to narrow the
        view (free only, has pricing, provider, modality, context window). Each row links
        to its provider&rsquo;s detail page. Use the &ldquo;compare&rdquo; checkboxes to put
        models side-by-side.
      </p>
      <ModelsTable
        models={snap.models}
        providers={Object.fromEntries(snap.providers.map((p) => [p.id, p]))}
      />
    </div>
  );
}
