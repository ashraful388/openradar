import { NextResponse } from "next/server";
import { promises as fs } from "fs";
import path from "path";

export async function POST(req: Request) {
  const body = await req.json().catch(() => null);
  if (!body?.provider_name || !body?.provider_url || !body?.source_url) {
    return NextResponse.json({ ok: false, error: "missing fields" }, { status: 400 });
  }
  const file = path.join(process.cwd(), "..", "..", "data", "submissions.jsonl");
  const line = JSON.stringify({ ...body, received_at: new Date().toISOString() }) + "\n";
  await fs.appendFile(file, line, "utf8").catch(async () => {
    // local dev fallback
    await fs.appendFile(path.join(process.cwd(), "submissions.jsonl"), line, "utf8");
  });
  return NextResponse.json({ ok: true });
}
