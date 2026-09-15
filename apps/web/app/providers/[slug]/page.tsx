import Link from "next/link";
import { notFound } from "next/navigation";
import { getSnapshot } from "../../../lib/snapshot";
import { CopyCurl } from "../../../components/copy-curl";
import { StatusDot } from "../../../components/status-dot";
import type { Model, Provider } from "../../../lib/snapshot";

export const dynamic = "force-static";

export async function generateStaticParams() {
  const snap = await getSnapshot();
  return snap.providers.map((p) => ({ slug: p.slug }));
}

export default async function ProviderPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const snap = await getSnapshot();
  const provider = snap.providers.find((p) => p.slug === slug);
  if (!provider) notFound();

  const models = snap.models
    .filter((m) => m.provider_id === provider.id)
    .sort((a, b) => {
      // Free models first, then priced, then bare listings.
      if (a.is_free !== b.is_free) return a.is_free ? -1 : 1;
      return a.display_name.localeCompare(b.display_name);
    });

  const freeCount = models.filter((m) => m.is_free).length;
  const needsKey = provider.probe_status === "needs_key";
  const gated = provider.probe_status === "gated";
  const unreachable = provider.probe_status === "error";
  const sampleModel =
    models.find((m) => m.is_free)?.model_id ?? models[0]?.model_id ?? "MODEL_ID";

  return (
    <div className="page narrow">
      <p className="kicker">
        <Link href="/api-providers">API Providers</Link> / {provider.slug}
      </p>
      <h1 className="display">{provider.name}</h1>
      {provider.tagline ? <p className="lede">{provider.tagline}</p> : null}

      <div className="meta-grid">
        <div>
          <span className="meta-label">Region</span>
          <span className="meta-val">{provider.region || "—"}</span>
        </div>
        <div>
          <span className="meta-label">Signup</span>
          <span className="meta-val">{provider.signup_friction || "—"}</span>
        </div>
        <div>
          <span className="meta-label">Free models</span>
          <span className="meta-val">
            {freeCount}
            {models.length > 0 ? (
              <span className="dim"> of {models.length} listed</span>
            ) : null}
            {needsKey ? (
              <>
                {" "}
                <span className="badge badge-needskey">
                  {provider.api_key_env ?? "key"} not set
                </span>
              </>
            ) : null}
          </span>
        </div>
        <div>
          <span className="meta-label">Modalities</span>
          <span className="meta-val">
            {provider.modalities.join(" · ") || "—"}
          </span>
        </div>
        <div>
          <span className="meta-label">API base</span>
          <span className="meta-val mono small">{provider.api_base || "—"}</span>
        </div>
        <div>
          <span className="meta-label">Website</span>
          <span className="meta-val">
            {provider.homepage ? (
              <a href={provider.homepage} target="_blank" rel="noreferrer">
                {provider.homepage.replace(/^https?:\/\//, "")} ↗
              </a>
            ) : (
              "—"
            )}
          </span>
        </div>
        <div>
          <span className="meta-label">Last verified</span>
          <span className="meta-val">
            <StatusDot verifiedAt={provider.last_verified} />{" "}
            <span className="dim">{provider.last_verified.slice(0, 10)}</span>
          </span>
        </div>
      </div>

      {(needsKey || gated || unreachable) && (
        <p className="updated" role="note">
          {needsKey && (
            <>
              This provider&rsquo;s model list is gated behind login/API key — the
              numbers here are what community sources and aggregators reported,
              not a live verified count. Set{" "}
              <code className="mono">{provider.api_key_env ?? "a provider API key"}</code>{" "}
              in the agent environment to unlock verification.
            </>
          )}
          {gated && (
            <>
              The configured API key was rejected by this provider (expired or
              missing scope?) — its model list could not be re-verified this run.
            </>
          )}
          {unreachable && <>The provider&rsquo;s API was unreachable on the last agent run.</>}
        </p>
      )}

      {provider.notes ? (
        <div className="prose">
          <p>
            <span className="meta-label">Notes</span>
            {provider.notes}
          </p>
        </div>
      ) : null}
      {provider.catch ? (
        <div className="prose">
          <p>
            <span className="meta-label">Catch</span>
            {provider.catch}
          </p>
        </div>
      ) : null}

      <h2 className="section-title">Try it</h2>
      {provider.api_base ? (
        <CopyCurl
          base={provider.api_base}
          model={sampleModel}
          apiKeyEnv={provider.api_key_env ?? undefined}
        />
      ) : (
        <p className="dim">No public API base recorded for this provider.</p>
      )}

      <h2 className="section-title">
        Models <span className="dim">({models.length})</span>
      </h2>
      {models.length === 0 ? (
        <p className="dim empty">
          No models recorded yet
          {needsKey ? " — this provider's list is gated; set its API key to discover them." : "."}
        </p>
      ) : (
        <div className="model-list">
          {models.map((m) => (
            <ModelCard key={m.id} model={m} provider={provider} />
          ))}
        </div>
      )}
    </div>
  );
}

function ModelCard({ model, provider }: { model: Model; provider: Provider }) {
  const priced =
    model.input_per_1m != null || model.output_per_1m != null;
  return (
    <article className="model-card" id={model.id}>
      <div className="model-head">
        <h3 className="model-name">{model.display_name}</h3>
        {model.is_free ? (
          <span
            className={`badge ${model.free_verified_at ? "badge-free-verified" : "badge-free"}`}
            title={
              model.free_verified_at
                ? `Verified free by a live 1-token probe on ${model.free_verified_at.slice(0, 10)}`
                : "Free per docs/community sources"
            }
          >
            {model.free_verified_at ? "free ✓" : "free"}
          </span>
        ) : priced ? (
          <span className="badge badge-paid">paid</span>
        ) : (
          <span className="dim small" title="No free/paid evidence yet — the agent lists it, but its tier is unverified">
            unverified
          </span>
        )}
      </div>
      <div className="model-id-row">
        <span className="model-id-label">model id</span>
        <span className="model-id">{model.model_id}</span>
      </div>
      {model.free_limit ? <p className="model-limits">{model.free_limit}</p> : null}
      <p className="model-modality">
        {model.modality.join(" · ")}
        {model.context_window
          ? ` · ${model.context_window.toLocaleString()} context`
          : ""}
        {priced
          ? ` · $${(model.input_per_1m ?? 0).toFixed(2)} / $${(model.output_per_1m ?? 0).toFixed(2)} per 1M`
          : ""}
      </p>
      {provider.api_base ? (
        <CopyCurl
          base={provider.api_base}
          model={model.model_id}
          apiKeyEnv={provider.api_key_env ?? undefined}
        />
      ) : null}
    </article>
  );
}
