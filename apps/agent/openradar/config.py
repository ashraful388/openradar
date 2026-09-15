"""Runtime config for the agent.

Loaded from `data/config.json` if present, otherwise from defaults.
The settings dashboard at /settings in the web app writes this file;
the agent reads it on every run.

This is a thin layer on top of the catalog: every knob the user might
want to expose has a default, and the config file just overrides the
fields the user has changed. No provider ever gets removed by the config
itself; staleness is the agent's job, the user just sets preferences.
"""
from __future__ import annotations
import json
import os
from pathlib import Path

DEFAULTS: dict = {
    "agent": {
        # How often the agent should run, in hours. 1-24; the CI cron
        # matrix uses this to decide which schedule entry is live.
        "run_interval_hours": 10,
        # If true, run the LLM orchestrator on every cycle — the agent
        # decides which providers/models to investigate this run and
        # calls the scrapers as tools. Off by default (operator opt-in).
        "llm_orchestration_enabled": False,
        # Manual-only mode: skip the scheduled run; only respond to
        # explicit triggers (Run now button, workflow_dispatch).
        "manual_mode": False,
        "include_facebook": False,           # placeholder; ToS-restricted, off by default
        "include_search_apis": True,
        "include_community_lists": True,
        "auto_promote_candidates": True,     # if False, candidates go to a review queue instead
        "auto_remove_stale": False,          # never auto-remove by default
        # Global cap on 1-token free-classification probes per run
        # across all providers. 0 disables probing even if sources.probe
        # is enabled. Inconclusive probes (network errors, 429) don't
        # count against the budget.
        "probe_budget_per_run": 300,
        "log_level": "info",                 # debug | info | warn | error
    },
    "free_detection": {
        "free_only_when": "both_input_and_output_zero",  # both | either | min_or_max
        "min_dollar_threshold": 0.0,                     # anything > this is paid
        "respect_b_ai_pricing": True,                    # if a model already has b.ai pricing, never flip it
        "treat_credits_as_free": True,                   # signup credit windows count as free
    },
    "flagships": {
        "max_output_per_1m": 20.0,            # anything more expensive is excluded
        "require_tool_calling_or_vision": True,
        "min_quality_signal": "any",           # any | tool_calling | vision
    },
    "sources": {
        "openrouter":       {"enabled": True,  "weight": 1.0},
        "huggingface":      {"enabled": True,  "weight": 1.0},
        "models_dev":       {"enabled": True,  "weight": 1.0},
        "bai_static":       {"enabled": True,  "weight": 1.0},
        "bai_live":         {"enabled": True,  "weight": 1.5},  # only used if BAI_API_KEY is set
        "xkiro":            {"enabled": True,  "weight": 1.2},  # public tiered /v1/models
        "openrouter_providers": {"enabled": True, "weight": 0.9},  # openrouter.ai/providers directory mining
        "community_lists":  {"enabled": True,  "weight": 0.8},
        "search_apis":      {"enabled": True,  "weight": 0.6},
        "provider_endpoints":{"enabled": True,  "weight": 0.7},
        "verifier":         {"enabled": False, "weight": 1.0},  # legacy toggle; superseded by top-level `verifier.enabled`
        # 1-token live probe (ground-truth free classification). Needs
        # per-provider API keys in the environment; providers without a
        # key are simply not probed.
        "probe":            {"enabled": True,  "max_probes_per_provider": 40},
    },
    "verifier": {
        # LLM-based re-checker for the scrapers' claims. The API keys
        # live in data/.verifier-secrets.json (gitignored) — they're
        # configured via the web Settings → Intelligence panel. This
        # block only carries the public part: which provider cards to
        # use, and the auto-apply policy. Default off; opt in to spend
        # LLM credits. The per-run budget cap is no longer configurable
        # from the UI — set OPENRADAR_VERIFIER_BUDGET_PER_RUN on the
        # server if you need a different cap.
        "enabled": False,
        "primary_provider": "",     # name of a card in .verifier-secrets.json
        "secondary_provider": "",   # ditto, used for cross-check
        "auto_apply_expire": True,
        "expire_confidence_threshold": 0.7,
    },
    "ui": {
        "show_paid_models_on_provider_page": True,
        "models_page_view": "grouped",        # grouped | flat
        "default_region_filter": "",
        "highlight_status_dot_threshold_days": 7,
    },
    "notifications": {
        "new_provider_webhook_url": "",
        "expired_tier_webhook_url": "",
    },
}


def _config_path() -> Path:
    p = Path(os.environ.get("OPENRADAR_DATA", Path(__file__).resolve().parents[3] / "data")) / "config.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def load() -> dict:
    f = _config_path()
    if f.exists():
        try:
            user_cfg = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return json.loads(json.dumps(DEFAULTS))
        # Merge: user overrides defaults
        merged = json.loads(json.dumps(DEFAULTS))
        for section, vals in user_cfg.items():
            if section in merged and isinstance(vals, dict):
                merged[section].update(vals)
            else:
                merged[section] = vals
        # Migration: older configs use `run_frequency` (every_6_hours / etc).
        # Translate to the new `run_interval_hours` + `manual_mode` shape.
        # Note: the trigger is whether the user config explicitly set the
        # legacy key — not whether the merged dict has the new one, since
        # DEFAULTS already carries the new field. If the user already set
        # the new field, prefer it over the translation of the legacy one.
        user_agent = user_cfg.get("agent") if isinstance(user_cfg.get("agent"), dict) else {}
        if "run_frequency" in user_agent:
            legacy = user_agent["run_frequency"]
            agent = merged["agent"]
            # Drop the legacy key from the merged output regardless of
            # whether a translation was possible, so old configs don't
            # carry a dead key forward.
            agent.pop("run_frequency", None)
            if legacy == "manual":
                agent["manual_mode"] = True
            elif "run_interval_hours" not in user_agent:
                # Only translate when the user hasn't already set the new
                # field explicitly. If they have, their value wins.
                agent["run_interval_hours"] = {
                    "every_6_hours": 6,
                    "every_10_hours": 10,
                    "every_24_hours": 24,
                }.get(legacy, agent.get("run_interval_hours",
                                        DEFAULTS["agent"]["run_interval_hours"]))
        # Clamp the interval to the supported range; reject out-of-range
        # values rather than silently fall back, so the operator notices.
        agent = merged["agent"]
        try:
            iv = int(agent.get("run_interval_hours", DEFAULTS["agent"]["run_interval_hours"]))
            if iv < 1 or iv > 24:
                iv = DEFAULTS["agent"]["run_interval_hours"]
            agent["run_interval_hours"] = iv
        except (TypeError, ValueError):
            agent["run_interval_hours"] = DEFAULTS["agent"]["run_interval_hours"]
        return merged
    return json.loads(json.dumps(DEFAULTS))


def save(cfg: dict) -> Path:
    f = _config_path()
    f.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return f


def reset() -> dict:
    f = _config_path()
    if f.exists():
        f.unlink()
    return load()
