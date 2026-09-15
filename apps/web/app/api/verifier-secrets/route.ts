import { NextResponse } from "next/server";
import { promises as fs } from "fs";
import path from "path";

const DATA_DIR = path.join(process.cwd(), "..", "..", "data");
const SECRETS_PATH = path.join(DATA_DIR, ".verifier-secrets.json");

type Provider = {
  name: string;
  base_url: string;
  api_format: "openai" | "anthropic" | "custom";
  api_key: string;
  models: { name: string; model_id: string }[];
};

type SecretsFile = { providers: Provider[] };

/** Mask an API key for display: keep the prefix and the last 4 chars. */
function maskKey(key: string): string {
  if (!key) return "";
  if (key.length <= 8) return "•".repeat(key.length);
  return key.slice(0, 4) + "•".repeat(Math.max(4, key.length - 8)) + key.slice(-4);
}

function publicView(p: Provider) {
  return {
    name: p.name,
    base_url: p.base_url,
    api_format: p.api_format,
    api_key_masked: maskKey(p.api_key || ""),
    api_key_set: Boolean(p.api_key),
    models: p.models || [],
  };
}

async function readFile(): Promise<SecretsFile> {
  try {
    const raw = await fs.readFile(SECRETS_PATH, "utf8");
    const parsed = JSON.parse(raw);
    if (parsed && Array.isArray(parsed.providers)) return parsed;
    return { providers: [] };
  } catch {
    return { providers: [] };
  }
}

async function writeFile(payload: SecretsFile): Promise<void> {
  await fs.mkdir(DATA_DIR, { recursive: true });
  await fs.writeFile(SECRETS_PATH, JSON.stringify(payload, null, 2), "utf8");
}

export async function GET() {
  const secrets = await readFile();
  // NEVER return the raw api_key over the wire. The form stores the
  // full key server-side and only sees a masked preview.
  return NextResponse.json({ providers: secrets.providers.map(publicView) });
}

export async function POST(req: Request) {
  const body = (await req.json().catch(() => null)) as
    | { providers?: Provider[] }
    | null;
  if (!body || !Array.isArray(body.providers)) {
    return NextResponse.json({ ok: false, error: "providers array required" }, { status: 400 });
  }
  // Validate: every provider needs a name + base_url + api_format.
  // api_key is required for NEW providers; for updates an empty key
  // means "leave unchanged" — the browser never sees raw keys (only
  // masked previews), so an empty field must NOT erase the stored one.
  const stored = await readFile();
  const storedByName = new Map(stored.providers.map((p) => [(p.name || "").toLowerCase(), p]));
  const cleaned: Provider[] = [];
  for (const p of body.providers) {
    if (!p || typeof p.name !== "string" || !p.name.trim()) {
      return NextResponse.json({ ok: false, error: "every provider needs a non-empty name" }, { status: 400 });
    }
    if (typeof p.base_url !== "string" || !p.base_url.trim()) {
      return NextResponse.json({ ok: false, error: `provider "${p.name}" needs a base_url` }, { status: 400 });
    }
    if (!["openai", "anthropic", "custom"].includes(p.api_format)) {
      return NextResponse.json({ ok: false, error: `provider "${p.name}" has an invalid api_format` }, { status: 400 });
    }
    let apiKey = typeof p.api_key === "string" ? p.api_key : "";
    if (!apiKey) {
      const prev = storedByName.get(p.name.trim().toLowerCase());
      if (prev?.api_key) apiKey = prev.api_key;
    }
    cleaned.push({
      name: p.name.trim(),
      base_url: p.base_url.trim(),
      api_format: p.api_format,
      api_key: apiKey,
      models: Array.isArray(p.models) ? p.models : [],
    });
  }
  await writeFile({ providers: cleaned });
  return NextResponse.json({ ok: true, providers: cleaned.map(publicView) });
}

export async function DELETE() {
  try {
    await fs.unlink(SECRETS_PATH);
  } catch {
    // already missing, fine
  }
  return NextResponse.json({ ok: true });
}
