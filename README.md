# OpenRadar

A reference site for the open AI economy. Two surfaces, one data spine:

1. **Free API directory** — every provider that offers a genuinely free model API, with limits, the catch, and a copy-pasteable curl.
2. **Cheap flagships** — frontier and near-frontier models, ranked by absolute price.

A discovery agent runs every 10 hours and rewrites the data so the dashboard never goes stale. Source for the data, the seed catalog, the discovery worker, and the Next.js site all live in this monorepo.

## Why this exists

Most "free LLM API" lists are missing half the providers — particularly the Chinese set (Z.ai/GLM, Qwen, Moonshot, DeepSeek, SiliconFlow) and the small aggregators (Chutes.ai, Zuki, NagaAI, Anannas, Nscale, Public AI, GLHF, Targon). OpenRadar is built to be the canonical directory for these. The /changes page makes the 10-hour refresh visible — if a row is older than seven days, the system has gone quiet.

## Repo layout

```
apps/
  web/                Next.js dashboard (the public site)
  agent/              Python discovery agent (runs on GitHub Actions)
data/
  snapshot.json       normalized data the dashboard reads (committed)
  changelog.md        human-readable activity log
  submissions.jsonl   public-submission inbox (one JSON per line)
.github/workflows/
  discover.yml        cron job, every 10h
```

## Running the dashboard locally

```bash
npm install
npm run dev
# open http://localhost:3000
```

The dashboard reads `data/snapshot.json` at build time. If you edit it, restart the dev server.

## Running the agent locally

```bash
cd apps/agent
python -m pip install -e .
python -m openradar.cli
```

The agent writes to `data/snapshot.json`. It pulls from:

| Source | Always on? | Needs a key? |
|---|---|---|
| `models.dev/api.json` | yes | no |
| Per-provider `/v1/models` endpoints | yes | no |
| GitHub community lists (cheahjs, etc.) | yes | no |
| Brave / Tavily / Exa search APIs | only if a key is set | optional |
| Reddit / HN / X / Discord / Telegram | only if a key is set | optional |
| Public submission form | yes | no |

Facebook Pages monitoring is intentionally not included — ToS-restricted and not viable for an indie project. Use the manual submission form instead.

## Adding a new provider

1. Add a `Provider(...)` entry to `apps/agent/openradar/catalog.py`.
2. Add at least one `Model(...)` row in `data/snapshot.json` (the agent's first run will keep it, subsequent runs will refresh it).
3. Open a PR. The agent will start polling that provider's `/v1/models` on the next scheduled run.

If you don't have a PR handy, use the in-app `/submit` form.

## Resolving the "b.ai" mystery

The user who prompted this project mentioned a provider they wrote as "b.ai" that other dashboards miss. The most likely readings, in order:

1. **Z.ai** (Zhipu / BigModel / GLM) — has a free API tier, `.ai` TLD, and the `z`/`.` key adjacency makes it a common typo. Included as a first-class provider.
2. **Chutes.ai** — serverless inference, OpenAI-compatible at `https://llm.chutes.ai/v1`. Included.
3. Other `.ai` providers (Bytez, beta.ai, BAAI, etc.) are picked up automatically by the community-list ingestor.

## Deployment

- **Dashboard**: Vercel. Connect this repo, set the root to `apps/web`, build command `next build`, output is handled automatically.
- **Agent**: GitHub Actions, defined in `.github/workflows/discover.yml`. The workflow commits `data/snapshot.json` back to the repo on every successful run, so the static site re-deploys.

## Design

Editorial monochrome — Fraunces serif display + Inter body, single warm-red accent, generous whitespace, tables for data. Deliberately not the rounded-card-grid-leaderboard look that dominates this space. See `apps/web/styles/globals.css`.

## License

MIT.
