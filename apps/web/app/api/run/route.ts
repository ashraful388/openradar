import { NextResponse } from "next/server";
import { promises as fs } from "fs";
import { spawn } from "child_process";
import path from "path";

const DATA_DIR = path.join(process.cwd(), "..", "..", "data");
const RUN_STATE_PATH = path.join(DATA_DIR, ".run-state.json");
const AGENT_DIR = path.join(process.cwd(), "..", "..", "apps", "agent");
const LOG_PATH = path.join(DATA_DIR, ".run.log");
const TIMEOUT_MS = 10 * 60 * 1000; // 10 minutes

type RunState = {
  last_job_id: string | null;
  last_status: "idle" | "running" | "done" | "failed" | "timeout";
  last_started: string | null;
  last_finished: string | null;
  last_summary: string;
  last_log_tail: string;
};

const EMPTY_STATE: RunState = {
  last_job_id: null,
  last_status: "idle",
  last_started: null,
  last_finished: null,
  last_summary: "",
  last_log_tail: "",
};

async function readState(): Promise<RunState> {
  try {
    const raw = await fs.readFile(RUN_STATE_PATH, "utf8");
    return { ...EMPTY_STATE, ...JSON.parse(raw) };
  } catch {
    return { ...EMPTY_STATE };
  }
}

async function writeState(s: RunState) {
  await fs.mkdir(DATA_DIR, { recursive: true });
  await fs.writeFile(RUN_STATE_PATH, JSON.stringify(s, null, 2), "utf8");
}

/** GET — return the current run state. Cheap; the form polls this. */
export async function GET() {
  return NextResponse.json(await readState());
}

/** POST — kick off a fresh agent run. Single-flight: rejects while a
 * job is already running. The job writes its own state to disk and
 * the form reads it via GET.
 */
export async function POST() {
  const cur = await readState();
  if (cur.last_status === "running") {
    return NextResponse.json(
      { ok: false, error: "a run is already in progress", state: cur },
      { status: 409 }
    );
  }

  const jobId = `run-${Date.now()}`;
  const started = new Date().toISOString();
  await writeState({
    last_job_id: jobId,
    last_status: "running",
    last_started: started,
    last_finished: null,
    last_summary: "agent run starting…",
    last_log_tail: "",
  });

  // Spawn the agent detached from the request lifecycle. We use
  // `detached: true` + `stdio: ["ignore", logfile, logfile]` so the
  // process keeps running after the POST returns. The form polls
  // GET /api/run to watch progress.
  await fs.mkdir(DATA_DIR, { recursive: true });
  const logFd = await fs.open(LOG_PATH, "a");
  await logFd.write(`\n\n=== ${jobId} started at ${started} ===\n`);

  const child = spawn(
    process.platform === "win32" ? "python" : "python3",
    ["-m", "openradar.cli"],
    {
      cwd: AGENT_DIR,
      detached: true,
      stdio: ["ignore", "pipe", "pipe"],
      env: { ...process.env, PYTHONUNBUFFERED: "1" },
      windowsHide: true,
    }
  );
  child.stdout?.on("data", (chunk: Buffer) => {
    fs.appendFile(LOG_PATH, chunk).catch(() => {});
  });
  child.stderr?.on("data", (chunk: Buffer) => {
    fs.appendFile(LOG_PATH, chunk).catch(() => {});
  });

  // Watchdog: enforce 10-minute cap. We can't kill the detached child
  // portably from here, so we just mark the state as "timeout" if it
  // hasn't finished in time. The child keeps running but the UI shows
  // the timeout.
  const watchdog = setTimeout(async () => {
    const st = await readState();
    if (st.last_job_id === jobId && st.last_status === "running") {
      await writeState({
        ...st,
        last_status: "timeout",
        last_finished: new Date().toISOString(),
        last_summary: "run exceeded 10-minute cap; check the log for partial output",
      });
    }
  }, TIMEOUT_MS);

  child.on("exit", async (code) => {
    clearTimeout(watchdog);
    const finished = new Date().toISOString();
    const st = await readState();
    if (st.last_job_id !== jobId) return; // a newer run already replaced us
    // Read the last few lines of the log for a quick summary.
    let tail = "";
    try {
      const text = await fs.readFile(LOG_PATH, "utf8");
      const lines = text.split("\n");
      tail = lines.slice(-5).join("\n");
    } catch {}
    await writeState({
      last_job_id: jobId,
      last_status: code === 0 ? "done" : "failed",
      last_started: st.last_started,
      last_finished: finished,
      last_summary: code === 0
        ? "agent run completed; refresh the page to see the new snapshot"
        : `agent run exited with code ${code}; check the log`,
      last_log_tail: tail,
    });
  });

  return NextResponse.json({ ok: true, job_id: jobId, started });
}

/** DELETE — clear the run state (used by the form's "dismiss" button). */
export async function DELETE() {
  await writeState({ ...EMPTY_STATE });
  return NextResponse.json({ ok: true });
}
