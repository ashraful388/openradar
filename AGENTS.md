# AGENTS.md — working notes for the agent (and for you)

This file is the operator's manual. It is not read by the runtime; the runtime reads `data/snapshot.json`. It is for the human or AI agent who maintains the project.

## What runs where

- **`apps/web`** — Next.js 15 App Router. Static-friendly, reads `data/snapshot.json` at build time.
- **`apps/agent`** — Python 3.12. The discovery worker. Single CLI entrypoint: `python -m openradar.cli`.
- **`.github/workflows/discover.yml`** — hourly cron `17 * * * *` (offset 17 minutes), gated by the `OPENRADAR_RUN_HOURS` repo variable. Commits `data/snapshot.json` and `data/changelog.md` back to the repo, which redeploys Vercel. The interval gate lives in a **step**, not the job-level `if:` — a job-if can't see the job's own `env` context, and referencing it invalidates the whole file (that bug silently disabled every scheduled and push run once; don't reintroduce it).

## Data flow

```
providers (catalog.py)
        +
models.dev / openrouter / per-provider /v1/models
        +
community lists (cheahjs/free-llm-api-resources etc.)
        +
search APIs (Brave / Tavily / Exa, optional)
        +
public submissions (submissions.jsonl)
        ↓
   normalize (models.py)
        ↓
   data/snapshot.json  ←──  committed  ──→  Vercel redeploy
        ↓
   data/changelog.md   ←──  committed
```

## What the agent does on each run

1. Load existing `data/snapshot.json`.
2. For every provider in `providers`, hit its `/v1/models` endpoint and bump `last_verified`. If the endpoint returns data, mark `status = active` and update `free_model_count`. Failures are logged to `changelog`, not fatal.
3. Pull `models.dev/api.json` and cross-reference (best-effort; models.dev is the source of truth for pricing/capabilities).
4. Pull the community-list READMEs (cheahjs and friends), regex out candidate hosts, log candidates to the changelog for human review.
5. If a search API key is set, run "new free LLM API 2026" queries and log hits to the changelog.
6. If Reddit / HN / X / Discord / Telegram keys are set, sweep them for recent "[provider] free API" mentions.
7. Append to `data/changelog.md`.
8. Commit and push.

## Things to know

- **No auto-removal.** The agent never deletes a provider. Stale or dead providers get a `status = stale` flag and a changelog entry; humans decide.
- **Free-tier classification is conservative.** A provider is marked `is_free = true` only when the public docs say so OR the agent verified with a 1-token probe (implemented in `sources/probe.py`: a `max_tokens=1` completion per model — HTTP 200 ⇒ free-verified, 402/403 ⇒ paid). Probe-verified rows carry `free_verified_at` and render as `free✓` in the UI. Caps: `sources.probe.max_probes_per_provider` (40) and `agent.probe_budget_per_run` (300) in `data/config.json`.
- **Gated providers are flagged, not faked.** When `/v1/models` returns 401/403 without a key, the provider gets `probe_status = "needs_key"` and the UI shows a `KEY?` badge ("count unknown, not zero") plus a changelog entry naming the env var to set. Models with no pricing evidence are "unverified", never "paid".
- **Provider API keys (BYOK).** The agent resolves each provider's `api_key_env` credential from (1) environment variables — repo secrets / Vercel env, the CI path — then (2) `data/.provider-keys.json`, written by **Settings → Provider API keys** (gitignored, masked previews only). With a key set, the run fetches the real model list and 1-token-probes it. Never commit keys anywhere.
- **Facebook Pages are not monitored. Use the submission form. The Submit form works in both deployments.** Locally it appends to `data/submissions.jsonl`. On Vercel the filesystem is read-only, so its API route instead files a GitHub issue labeled `provider-submission` — the agent ingests open issues each run, promotes the provider when its `/v1/models` probes as OpenAI-compatible (same bar as community-list candidates; gated endpoints get the `KEY?` badge), comments, and closes the issue. This needs **`GITHUB_TOKEN`** (a repo-scoped token with issues write) and **`OPENRADAR_GITHUB_REPO`** (e.g. `ashraful388/openradar`) set as Vercel env vars; without them the form shows a clear error instead of silently dropping the submission.
- **Intelligence (LLM verifier) is opt-in.** The verifier re-checks free-tier claims, model identity, and provider liveness using an LLM. The API key is **never** stored in `data/config.json` (the file is public on GitHub). Set `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` on the server (Vercel env, or repo secret for CI); configure everything else — endpoint URL, models, budget, auto-apply policy — from the **Settings → Intelligence** page, which writes the public part to `data/config.json` under the `verifier` key.
- **LLM orchestration is also opt-in (`agent.llm_orchestration_enabled`).** When on, an LLM (the same primary provider used by the verifier) plans each run: it picks which providers/models to investigate, calls the scrapers and judges as tools, and fills missing per-million-token prices for paid models. The orchestrator respects the same trust discipline as the verifier — every decision cites evidence, and the only mutations it can apply are `is_free: True → False` (on high-confidence expire verdicts) and price-fill when both cross-check passes agree. It never adds providers, never removes anything, and never auto-applies identity or liveness changes. The deterministic pipeline stays the safe default; the orchestrator is a sharper but riskier mode.
- **Run cadence is operator-controlled.** `agent.run_interval_hours` (1-24, default 1 = hourly) mirrors the CI schedule. CI's `discover.yml` fires hourly and a gate step compares the UTC hour against the `OPENRADAR_RUN_HOURS` repo variable (default 1) — intervals > 1 run only when the hour is a multiple. The **Settings → Agent → Run now** button runs the agent directly on the local server (single-flight, 10-minute cap, log to `data/.run.log`); on the hosted site there is no Python runtime and the filesystem is read-only, so the same button **dispatches the GitHub Actions run instead** (needs `GITHUB_TOKEN` with `workflow` scope + `OPENRADAR_GITHUB_REPO` as Vercel env vars, and returns a clear message when they're missing). The GitHub Actions **Run workflow** button is the manual equivalent for CI.
- **The catalog now covers paid models too.** `data/snapshot.json` stores every model the agent has seen, with `is_free=False` for paid rows and optional `input_per_1m`/`output_per_1m` prices. The `/models` page defaults to "show everything"; use the "free only" and "has pricing" filters to narrow. The home page and the cheap-flagships leaderboard still prioritize free / cheap.

## Common operations

| What you want to do | How |
|---|---|
| Add a provider | Edit `apps/agent/openradar/catalog.py` and add models in `data/snapshot.json` |
| Mark a provider as paid-only | Set `signup_friction = "trial_card"` and remove its models from the snapshot; the agent will keep it visible as "no free models" |
| Force a manual refresh | `gh workflow run discover.yml` (or use the Actions tab) |
| Override the data dir for local testing | `OPENRADAR_DATA=./tmp python -m openradar.cli` |
| Re-enable a search source | Set the env var in the repo secrets, no code change needed |
