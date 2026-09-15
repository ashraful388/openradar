import { promises as fs } from "fs";
import path from "path";

export type Modality = "chat" | "embedding" | "image" | "audio_tts" | "audio_stt" | "video" | "rerank" | "vision" | "code" | "ocr";
export type FreeKind = "free_tier" | "free_credits" | "promo" | "trial_card" | "byok_required" | "community";
export type FreeEvidenceSource = "declared" | "openrouter" | "models_dev" | "bai" | "probe" | "verifier" | "xkiro" | "huggingface";

export type Provider = {
  id: string;
  slug: string;
  name: string;
  region: string;
  api_base: string;
  openai_compatible: boolean;
  api_key_env?: string;
  /** Provider's public website (docs/signup). Derived by the agent from
   *  the api_base host, or pinned in the catalog. */
  homepage?: string;
  signup_friction: string;
  modalities: Modality[];
  tagline: string;
  notes: string;
  catch: string;
  free_model_count: number;
  status: "active" | "stale" | "removed";
  /** Live evidence from the agent's last /v1/models probe:
   *  "needs_key" = gated behind login and no key configured — the model
   *  list is unknown, not empty. Absent on snapshots from older runs. */
  probe_status?: "ok" | "needs_key" | "gated" | "error" | "skipped" | "";
  first_seen: string;
  last_verified: string;
};

export type Model = {
  id: string;
  provider_id: string;
  model_id: string;
  display_name: string;
  modality: Modality[];
  context_window?: number;
  is_free: boolean;
  free_kind: FreeKind;
  free_limit: string;
  /** Set when is_free=True was confirmed by a live 1-token completion
   *  against the provider API (ground truth), not inferred from docs. */
  free_verified_at?: string | null;
  /** Which source classified this model as free */
  free_evidence_source?: FreeEvidenceSource | null;
  /** When the free evidence was recorded */
  free_evidence_timestamp?: string | null;
  input_per_1m?: number | null;
  output_per_1m?: number | null;
  cache_read_per_1m?: number | null;
  cache_write_per_1m?: number | null;
  last_verified: string;
};

export type CheapFlagship = {
  rank: number;
  model_id: string;
  display_name: string;
  provider: string;
  input_per_1m: number;
  output_per_1m: number;
  context_window?: number;
};

export type Change = {
  at: string;
  kind: "added" | "expired" | "pricing" | "verified" | "submit";
  text: string;
};

export type CreditProvider = {
  provider_id: string;
  name: string;
  signup_bonus_usd: number;
  credit_expiry_days: number | null;
  models_available: string[];
  signup_friction: string;
  homepage: string;
  notes: string;
};

export type Snapshot = {
  snapshot_at: string;
  schema_version: number;
  providers: Provider[];
  models: Model[];
  cheap_flagships: CheapFlagship[];
  changelog: Change[];
  credit_providers: CreditProvider[];
};

const CACHE: { snap: Snapshot | null; mtimeMs: number } = { snap: null, mtimeMs: 0 };

export async function getSnapshot(): Promise<Snapshot> {
  const file = path.join(process.cwd(), "..", "..", "data", "snapshot.json");
  // Re-read when the agent run rewrites the file, not just on process
  // start — otherwise a long-lived dev server serves stale data.
  const stat = await fs.stat(file);
  if (CACHE.snap && stat.mtimeMs === CACHE.mtimeMs) return CACHE.snap;
  const raw = await fs.readFile(file, "utf8");
  CACHE.snap = JSON.parse(raw) as Snapshot;
  CACHE.mtimeMs = stat.mtimeMs;
  return CACHE.snap;
}
