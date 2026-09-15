import { NextResponse } from "next/server";
import { promises as fs } from "fs";
import path from "path";

const CFG_PATH = path.join(process.cwd(), "..", "..", "data", "config.json");

export async function POST(req: Request) {
  const body = await req.json().catch(() => null);
  if (!body || typeof body !== "object") {
    return NextResponse.json({ ok: false, error: "invalid body" }, { status: 400 });
  }
  await fs.mkdir(path.dirname(CFG_PATH), { recursive: true });
  await fs.writeFile(CFG_PATH, JSON.stringify(body, null, 2), "utf8");
  return NextResponse.json({ ok: true });
}

export async function DELETE() {
  try {
    await fs.unlink(CFG_PATH);
  } catch {
    // already missing, fine
  }
  return NextResponse.json({ ok: true });
}
