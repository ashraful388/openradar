"""OpenRadar discovery agent.

Refreshes the free-AI-API directory every 10 hours by:
  1. Refreshing every known provider's /v1/models endpoint.
  2. Pulling models.dev's structured catalog.
  3. Parsing community lists (cheahjs/free-llm-api-resources, etc.).
  4. Running cheap search-API queries for "new free LLM API" prompts.
  5. (Optional) Sweeping Reddit, HN, X, Discord, Telegram when keys are set.
  6. Reading the public-submission inbox for human tips.

Writes a normalized snapshot to data/snapshot.json and a changelog entry
to data/changelog.md, then commits back to the repo so the static site
re-deploys.
"""
__version__ = "0.1.0"
