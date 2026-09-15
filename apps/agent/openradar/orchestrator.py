"""LLM-driven discovery orchestrator.

When `cfg.agent.llm_orchestration_enabled` is on, this module runs an
extra "plan → execute" cycle on top of the deterministic pipeline:

  1. Build a candidate list from the current snapshot:
       - providers that haven't been verified recently
       - free-tier claims not yet audited
       - paid models missing pricing
       - community-list candidates not yet probed
  2. Ask the LLM to pick the most valuable subset and assign a tool
     to each (scrape_provider / judge_free_tier / judge_pricing /
     judge_paid_status / judge_liveness).
  3. Execute the manifest by calling the same scrapers and judges the
     deterministic pipeline uses. Every tool call's verdict is
     recorded as a Change(kind='verifier', text=json.dumps(...)) —
     the same wire shape as the existing step 5b, so the web UI and
     changelog readers don't need to learn a new kind.

Trust discipline (unchanged from the existing verifier layer):

  * LLM can decide WHAT to investigate; it can only mutate the
    snapshot in narrow, reversible ways (is_free True→False; price
    fill when both passes agree).
  * Two-pass cross-check on every verdict that would mutate.
  * Every verdict must cite evidence_urls; no evidence → unverified.
  * Hard per-run budget (env OPENRADAR_VERIFIER_BUDGET_PER_RUN).
"""
from __future__ import annotations
import json
import os
import time
from typing import Any

import httpx
from pydantic import BaseModel, Field

from . import sources
from .models import Model, Provider, Snapshot, Change, now


# ----------------------------- plan schema ---------------------------------

class PlanTask(BaseModel):
    """A single investigation task chosen by the orchestrator."""
    tool: str = Field(description="scrape_provider | judge_free_tier | judge_pricing | judge_paid_status | judge_liveness")
    subject_id: str = Field(description="provider id (p_...) or model id (m_...)")
    reason: str = Field(default="", description="one-sentence justification")


class Plan(BaseModel):
    """The LLM's selection from the candidate set."""
    tasks: list[PlanTask] = Field(default_factory=list)


# ----------------------------- candidate builder --------------------------

def _build_candidates(snap: Snapshot, max_per_kind: int = 50) -> dict[str, list[dict]]:
    """Construct the candidate pool the orchestrator picks from.

    Returns a dict with kinds: stale_providers, free_models, paid_no_price,
    stale_liveness. Each entry is a small dict the LLM can reason about."""
    providers_by_id = {p.id: p for p in snap.providers}

    stale_providers: list[dict] = []
    for p in snap.providers:
        # Heuristic: anything not "active" or older than 7 days is worth re-probing.
        if p.status == "stale":
            stale_providers.append({"provider_id": p.id, "name": p.name,
                                    "api_base": p.api_base, "status": p.status,
                                    "last_verified": p.last_verified})

    free_models: list[dict] = []
    for m in snap.models:
        if m.is_free and m.free_kind != "trial_card":
            free_models.append({"model_id": m.id, "model": m.model_id,
                                "display_name": m.display_name, "provider_id": m.provider_id,
                                "free_kind": m.free_kind})
            if len(free_models) >= max_per_kind:
                break

    paid_no_price: list[dict] = []
    for m in snap.models:
        if m.is_free:
            continue
        if m.input_per_1m is None and m.output_per_1m is None:
            paid_no_price.append({"model_id": m.id, "model": m.model_id,
                                  "display_name": m.display_name, "provider_id": m.provider_id})
            if len(paid_no_price) >= max_per_kind:
                break

    stale_liveness: list[dict] = []
    for p in snap.providers:
        if p.status == "stale":
            stale_liveness.append({"provider_id": p.id, "name": p.name, "api_base": p.api_base})
            if len(stale_liveness) >= max_per_kind:
                break

    return {
        "stale_providers": stale_providers,
        "free_models": free_models,
        "paid_no_price": paid_no_price,
        "stale_liveness": stale_liveness,
    }


# ----------------------------- LLM plan call ------------------------------

_PLAN_SYSTEM = (
    "You are the controller of an AI inference price-tracking agent. "
    "From the candidate sets below, pick a JSON array of investigation "
    "tasks that will maximize the catalog's accuracy within the budget. "
    "Each task is one of: scrape_provider, judge_free_tier, "
    "judge_pricing, judge_paid_status, judge_liveness. Bias toward "
    "free-tier and pricing-gap tasks; skip candidates that look fine. "
    "Return JSON only, no prose, no markdown."
)

_PLAN_USER_TEMPLATE = """Snapshot at: {snapshot_at}
Total providers: {n_providers}
Total models: {n_models} (free: {n_free})
Budget for this run: {budget} tasks (cap it; this is enforced)

Candidate sets (subject_id is what you put in the task — provider ids look like p_xxx, model ids look like m_xxx):

### Stale providers ({n_stale_providers} candidates)
{stale_providers}

### Free-tier claims not yet audited ({n_free_models} candidates, capped)
{free_models}

### Paid models missing pricing ({n_paid_no_price} candidates, capped)
{paid_no_price}

### Stale providers needing liveness re-check ({n_stale_liveness} candidates, capped)
{stale_liveness}

Reply with strict JSON in this shape:
{{"tasks": [{{"tool": "scrape_provider", "subject_id": "p_x", "reason": "..."}}, ...]}}
If the catalog is healthy and nothing needs re-checking, return {{"tasks": []}}.
"""


def _call_planner(client: sources.verifier.LLMClient, prompt_user: str) -> Plan | None:
    """Single LLM call to get the plan. Returns None on failure (parser
    already maps parse errors to unverified; here we just return None
    so the orchestrator records 'no plan' and falls back to the
    deterministic pipeline)."""
    if not client.has_key():
        return None
    raw = client.chat(_PLAN_SYSTEM, prompt_user)
    if not raw:
        return None
    s = raw.strip()
    s = s.replace("```json", "").replace("```", "").strip()
    if not s.startswith("{"):
        return None
    try:
        return Plan.model_validate_json(s)
    except Exception:
        return None


# ----------------------------- task execution -----------------------------

def _execute_task(
    task: PlanTask,
    *,
    snap: Snapshot,
    primary_client: sources.verifier.LLMClient,
    secondary_client: sources.verifier.LLMClient | None,
    providers_by_id: dict[str, Provider],
    models_by_id: dict[str, Model],
) -> tuple[Change | None, bool]:
    """Run a single task. Returns (change_to_record, mutated_snapshot).

    The only mutations are: judge_free_tier with verdict=expire +
    auto_apply + confidence >= threshold flips is_free True→False;
    judge_pricing with verdict=confirm + agreed cross_check fills
    input_per_1m / output_per_1m. Everything else is advisory."""
    if task.tool == "scrape_provider":
        p = providers_by_id.get(task.subject_id)
        if not p or not p.api_base:
            return None, False
        from . import provider_keys
        key = provider_keys.get(p.api_key_env)
        rows = sources.openai_compat.list_models(p.api_base, api_key=key, timeout=10.0)
        n = len(rows)
        if rows:
            p.last_verified = now()
            p.status = "active"
        change = Change(
            kind="verifier",
            text=json.dumps({
                "subject_kind": "provider", "subject_id": p.id,
                "verdict": "confirm" if n else "unverified",
                "confidence": 1.0 if n else 0.0,
                "evidence_urls": [p.api_base] if n else [],
                "notes": f"orchestrator scrape: {n} rows from {p.name}",
            }, ensure_ascii=False),
        )
        return change, n > 0

    if task.tool in ("judge_free_tier", "judge_paid_status"):
        m = models_by_id.get(task.subject_id)
        if not m:
            return None, False
        p = providers_by_id.get(m.provider_id)
        if not p or not p.api_base:
            return None, False
        v = sources.verifier.judge_free_tier(m, p, client=primary_client)
        v = sources.verifier.cross_check(
            v, model=m, provider=p, client=primary_client,
            secondary_client=secondary_client,
        )
        mutated = False
        if (v.verdict == "expire" and v.confidence >= 0.7
                and m.is_free and m.free_kind != "trial_card"):
            m.is_free = False
            m.free_kind = "trial_card"
            m.free_limit = (m.free_limit or "") + " [orchestrator: expired]"
            mutated = True
        return Change(kind="verifier", text=json.dumps(v.model_dump(), ensure_ascii=False)), mutated

    if task.tool == "judge_pricing":
        m = models_by_id.get(task.subject_id)
        if not m:
            return None, False
        p = providers_by_id.get(m.provider_id)
        if not p or not p.api_base:
            return None, False
        v = sources.verifier.judge_pricing(m, p, client=primary_client)
        v = sources.verifier.cross_check_pricing(
            v, model=m, provider=p, client=primary_client,
            secondary_client=secondary_client,
        )
        mutated = False
        if v.verdict == "confirm" and v.proposed_delta:
            d = v.proposed_delta
            try:
                in_v = float(d.get("input_per_1m")) if d.get("input_per_1m") is not None else None
                out_v = float(d.get("output_per_1m")) if d.get("output_per_1m") is not None else None
                if in_v is not None and out_v is not None and in_v >= 0 and out_v >= 0:
                    if m.input_per_1m is None:
                        m.input_per_1m = in_v
                    if m.output_per_1m is None:
                        m.output_per_1m = out_v
                    mutated = True
            except (TypeError, ValueError):
                pass
        return Change(kind="verifier", text=json.dumps(v.model_dump(), ensure_ascii=False)), mutated

    if task.tool == "judge_liveness":
        p = providers_by_id.get(task.subject_id)
        if not p:
            return None, False
        v = sources.verifier.judge_liveness(p, client=primary_client)
        v = sources.verifier.cross_check(
            v, provider=p, client=primary_client,
            secondary_client=secondary_client,
        )
        # Liveness verdicts are advisory only — never auto-remove or rebrand.
        return Change(kind="verifier", text=json.dumps(v.model_dump(), ensure_ascii=False)), False

    return None, False


# ----------------------------- public entry point -------------------------

def run_orchestrator(
    snap: Snapshot,
    *,
    primary_provider: str = "",
    secondary_provider: str = "",
) -> dict[str, int]:
    """Plan + execute one orchestrated cycle. Returns counters for the
    run summary. Each executed task records a Change; the orchestrator
    itself records a summary Change at the end."""
    started = time.time()

    primary_client = sources.verifier.LLMClient(provider_name=primary_provider or None)
    if not primary_client.has_key():
        snap.changelog.append(Change(
            kind="verifier",
            text="orchestrator disabled: no LLM key configured "
                 "(add a provider in Settings → Intelligence, "
                 "or set OPENAI_API_KEY / ANTHROPIC_API_KEY)",
        ))
        return {"planned": 0, "executed": 0, "mutated": 0, "skipped": 0}

    if secondary_provider and secondary_provider.lower() != primary_provider.lower():
        secondary_client = sources.verifier.LLMClient(provider_name=secondary_provider)
    else:
        secondary_client = None

    budget = sources.verifier._budget()
    if budget <= 0:
        snap.changelog.append(Change(
            kind="verifier",
            text="orchestrator disabled: OPENRADAR_VERIFIER_BUDGET_PER_RUN is 0",
        ))
        return {"planned": 0, "executed": 0, "mutated": 0, "skipped": 0}

    # Build candidates and ask the LLM to pick.
    candidates = _build_candidates(snap)
    prompt_user = _PLAN_USER_TEMPLATE.format(
        snapshot_at=snap.snapshot_at,
        n_providers=len(snap.providers),
        n_models=len(snap.models),
        n_free=sum(1 for m in snap.models if m.is_free),
        budget=budget,
        n_stale_providers=len(candidates["stale_providers"]),
        stale_providers=json.dumps(candidates["stale_providers"][:20], ensure_ascii=False),
        n_free_models=len(candidates["free_models"]),
        free_models=json.dumps(candidates["free_models"][:20], ensure_ascii=False),
        n_paid_no_price=len(candidates["paid_no_price"]),
        paid_no_price=json.dumps(candidates["paid_no_price"][:20], ensure_ascii=False),
        n_stale_liveness=len(candidates["stale_liveness"]),
        stale_liveness=json.dumps(candidates["stale_liveness"][:20], ensure_ascii=False),
    )
    plan = _call_planner(primary_client, prompt_user)
    planned = len(plan.tasks) if plan else 0
    if plan is None:
        snap.changelog.append(Change(
            kind="verifier",
            text="orchestrator: planner returned no plan (LLM parse failed or empty); "
                 "falling back to deterministic pipeline",
        ))
        return {"planned": 0, "executed": 0, "mutated": 0, "skipped": 0}

    snap.changelog.append(Change(
        kind="verifier",
        text=f"orchestrator: plan={planned} tasks (budget={budget}, "
             f"candidates: stale={len(candidates['stale_providers'])}, "
             f"free={len(candidates['free_models'])}, "
             f"paid_no_price={len(candidates['paid_no_price'])}, "
             f"liveness={len(candidates['stale_liveness'])})",
    ))

    providers_by_id = {p.id: p for p in snap.providers}
    models_by_id = {m.id: m for m in snap.models}
    executed = mutated = 0
    skipped = 0

    for task in plan.tasks:
        if budget <= 0:
            skipped += len(plan.tasks) - executed
            snap.changelog.append(Change(
                kind="verifier",
                text=f"orchestrator: budget exhausted; {skipped} planned tasks skipped",
            ))
            break
        budget -= 1
        try:
            change, did_mutate = _execute_task(
                task, snap=snap,
                primary_client=primary_client,
                secondary_client=secondary_client,
                providers_by_id=providers_by_id,
                models_by_id=models_by_id,
            )
        except Exception as e:
            snap.changelog.append(Change(
                kind="verifier",
                text=f"orchestrator: task {task.tool}({task.subject_id}) raised {e.__class__.__name__}: {e}",
            ))
            skipped += 1
            continue
        if change is None:
            skipped += 1
            continue
        snap.changelog.append(change)
        executed += 1
        if did_mutate:
            mutated += 1

    snap.changelog.append(Change(
        kind="verifier",
        text=f"orchestrator: {executed}/{planned} executed, {mutated} mutated, "
             f"{skipped} skipped, in {time.time()-started:.1f}s",
    ))
    return {"planned": planned, "executed": executed, "mutated": mutated, "skipped": skipped}
