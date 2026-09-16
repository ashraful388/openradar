import { NextResponse } from "next/server";
import { promises as fs } from "fs";
import path from "path";

function issueBody(b: Record<string, unknown>): string {
  const row = (label: string, v: unknown) => `- **${label}:** ${v || "—"}`;
  return [
    "Provider submission from the OpenRadar Submit form.",
    "",
    row("Provider name", b.provider_name),
    row("Provider homepage", b.provider_url),
    row("API base URL", b.api_base),
    row("Free model(s) and limits", b.models),
    row("Source link", b.source_url),
    row("Email", b.email),
    "",
    "The discovery agent ingests open `provider-submission` issues on its next run.",
    "",
    "```json",
    JSON.stringify(b, null, 2),
    "```",
  ].join("\n");
}

export async function POST(req: Request) {
  const body = await req.json().catch(() => null);
  if (!body?.provider_name || !body?.provider_url || !body?.source_url) {
    return NextResponse.json({ ok: false, error: "missing fields" }, { status: 400 });
  }
  const line = JSON.stringify({ ...body, received_at: new Date().toISOString() }) + "\n";
  // 1. Local/dev path: append to the submissions inbox the agent reads.
  try {
    const file = path.join(process.cwd(), "..", "..", "data", "submissions.jsonl");
    await fs.appendFile(file, line, "utf8");
    return NextResponse.json({ ok: true });
  } catch {
    try {
      await fs.appendFile(path.join(process.cwd(), "submissions.jsonl"), line, "utf8");
      return NextResponse.json({ ok: true });
    } catch {
      // read-only FS (Vercel) — fall through to the GitHub issue path
    }
  }
  // 2. Deployed path: file the submission as a repo issue, which the
  // discovery agent ingests (changelog + promotion after a probe) and
  // closes. Needs GITHUB_TOKEN + OPENRADAR_GITHUB_REPO env vars.
  const token = process.env.GITHUB_TOKEN;
  const repo = process.env.OPENRADAR_GITHUB_REPO;
  if (!token || !repo) {
    return NextResponse.json(
      {
        ok: false,
        error:
          "Submissions storage is unavailable on this deployment. The operator needs to set the GITHUB_TOKEN and OPENRADAR_GITHUB_REPO environment variables, or open an issue at github.com/ashraful388/openradar.",
      },
      { status: 503 },
    );
  }
  try {
    const res = await fetch(`https://api.github.com/repos/${repo}/issues`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github+json",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
      },
      body: JSON.stringify({
        title: `Provider submission: ${body.provider_name}`,
        body: issueBody(body),
        labels: ["provider-submission"],
      }),
    });
    if (!res.ok) {
      return NextResponse.json(
        { ok: false, error: `GitHub refused the submission (HTTP ${res.status}).` },
        { status: 502 },
      );
    }
    const issue = await res.json();
    return NextResponse.json({ ok: true, via: "github-issue", issue_url: issue.html_url });
  } catch {
    return NextResponse.json(
      { ok: false, error: "Could not reach GitHub to record the submission. Try again later." },
      { status: 502 },
    );
  }
}
