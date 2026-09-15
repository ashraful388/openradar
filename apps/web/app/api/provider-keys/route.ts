import { NextResponse } from "next/server";
import { promises as fs } from "fs";
import path from "path";
import { getSnapshot } from "../../../lib/snapshot";

const DATA_DIR = path.join(process.cwd(), "..", "..", "data");
const KEYS_PATH = path.join(DATA_DIR, ".provider-keys.json");

type KeyMap = Record<string, string>;

/** Mask a key for display: prefix + dots + last 4. */
function maskKey(key: string): string {
  if (!key) return "";
  if (key.length <= 8) return "•".repeat(key.length);
  return key.slice(0, 4) + "•".repeat(Math.max(4, key.length - 8)) + key.slice(-4);
}

async function readKeys(): Promise<KeyMap> {
  try {
    const raw = await fs.readFile(KEYS_PATH, "utf8");
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed.keys === "object" && parsed.keys ? parsed.keys : {};
  } catch {
    return {};
  }
}

async function writeKeys(keys: KeyMap): Promise<void> {
  await fs.mkdir(DATA_DIR, { recursive: true });
  await fs.writeFile(KEYS_PATH, JSON.stringify({ keys }, null, 2), "utf8");
}

export async function GET() {
  const keys = await readKeys();
  // Only masked previews + set-flags go over the wire, never raw keys.
  const view: Record<string, { masked: string; set: boolean }> = {};
  for (const [env, val] of Object.entries(keys)) {
    view[env] = { masked: maskKey(val), set: Boolean(val) };
  }
  // The form needs the slot list (one per provider that declares an
  // api_key_env); derive it from the live snapshot so catalog additions
  // show up without a code change.
  let slots: { env: string; provider: string; slug: string; signup: string }[] = [];
  try {
    const snap = await getSnapshot();
    slots = snap.providers
      .filter((p) => p.api_key_env)
      .map((p) => ({
        env: p.api_key_env as string,
        provider: p.name,
        slug: p.slug,
        // Link a couple of known key-issuing dashboards; others fall back to the provider page.
        signup: /groq/i.test(p.slug) ? "https://console.groq.com/keys"
          : /google/i.test(p.slug) ? "https://aistudio.google.com/apikey"
          : /cerebras/i.test(p.slug) ? "https://cloud.cerebras.ai"
          : /mistral/i.test(p.slug) ? "https://console.mistral.ai/api-keys"
          : `/providers/${p.slug}`,
      }));
  } catch {
    // snapshot unavailable — the form just renders with no slots
  }
  return NextResponse.json({ keys: view, slots });
}

export async function POST(req: Request) {
  const body = (await req.json().catch(() => null)) as { keys?: KeyMap } | null;
  if (!body || typeof body.keys !== "object" || body.keys === null) {
    return NextResponse.json({ ok: false, error: "keys object required" }, { status: 400 });
  }
  const current = await readKeys();
  for (const [env, val] of Object.entries(body.keys)) {
    if (!/^[A-Z0-9_]+$/.test(env)) {
      return NextResponse.json(
        { ok: false, error: `invalid env var name: ${env}` },
        { status: 400 }
      );
    }
    if (typeof val !== "string") continue;
    const trimmed = val.trim();
    // Empty value = "remove this key"; masked echo (contains •) = "leave unchanged".
    if (trimmed === "") delete current[env];
    else if (!trimmed.includes("•")) current[env] = trimmed;
  }
  await writeKeys(current);
  const view: Record<string, { masked: string; set: boolean }> = {};
  for (const [env, val] of Object.entries(current)) {
    view[env] = { masked: maskKey(val), set: Boolean(val) };
  }
  return NextResponse.json({ ok: true, keys: view });
}
