"""Admin · model governance — WHICH model runs, and who is ignoring the system.

The panel could always SET a model. Nothing could ANSWER the two questions an
operator actually has:

  1. "For this purpose, which model will really run, at what tier, and what
     does one action therefore cost?"  (`llm_routing_report`)
  2. "Which extensions pin their own models instead of using the system
     defaults?"  (`audit_extension_models`) -- and then fix them
     (`reset_extension_models`).

Both matter for money, not tidiness: charging is per action, but the
per-action platform fee follows the TIER of the model that actually ran, so
the same 5-action automation costs ~305 credits on `economy` and ~11,005 on
`premium`. While the effective model was invisible, that swing looked random.

All three handlers are thin: the cascade/pricing logic lives in
`models_llm_routing` and the pin/reset policy in `models_ext_model_policy`,
both pure and unit-tested. Handlers only do I/O and shaping.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from app import (
    chat, ActionResult, _admin_put, _gw_request, _registry_get, _registry_put,
    _resolve_app_id, AUTH_GW, AUTH_SERVICE_TOKEN,
)
from models_ext_model_policy import (
    INHERIT,
    MODEL_SLOTS,
    build_reset_payload,
    diff_policy,
    read_policy,
)
from models_llm_routing import (
    CODE_TIER_SLOTS,
    DEFAULT_CATEGORY_PRICES,
    DEFAULT_TIER_FEES,
    PURPOSE_SLOTS,
    SUBSTITUTION_SLOTS,
    estimate_run_cost,
    normalise_rates,
    resolve_slot,
)
from models_model_governance import (
    ExtensionModelAuditResponse,
    ExtensionModelResetReceipt,
    LlmRoutingReportResponse,
)

log = logging.getLogger("admin")


# ── shared reads ─────────────────────────────────────────────────────────── #

async def _live_llm_config() -> dict:
    """The flat LLM Config Store document the kernel's cascade reads."""
    try:
        r = await _gw_request("GET", "/v1/internal/config/llm")
        # _gw_request returns the DECODED body (a dict), never a response
        # object: on HTTP >=400 it returns {"error": "HTTP ..."}. The old
        # check asked for r.status_code, which a dict NEVER has, so this read
        # always fell through to {} and every routing report refused to answer
        # ("Could not read the live LLM config") even while the gateway was
        # happily returning 200. Fixed 2026-08-08.
        if isinstance(r, dict) and "error" not in r:
            return r
        if isinstance(r, dict):
            log.warning("llm config read failed: %s", r.get("error"))
    except Exception as exc:  # pragma: no cover - network shape varies
        log.warning("llm config read failed: %s: %s", type(exc).__name__, exc)
    return {}


async def _live_model_rates() -> list[dict]:
    """Model rate rows -- the ONLY place a model's billing tier is defined."""
    try:
        r = await _gw_request(
            "GET", "/v1/internal/billing/model-rates?include_unavailable=true"
        )
        # Same decoded-body contract as _live_llm_config above: this endpoint
        # returns a LIST on success, and an error surfaces as {"error": ...}.
        if isinstance(r, list):
            return r
        if isinstance(r, dict):
            log.warning("model rates read failed: %s", r.get("error"))
    except Exception as exc:  # pragma: no cover
        log.warning("model rates read failed: %s: %s", type(exc).__name__, exc)
    return []


async def _live_tier_fees() -> tuple[dict[str, int], bool]:
    """Per-tier platform fees. Returns (fees, is_live).

    `is_live` is reported to the caller: a fee quietly guessed from built-in
    defaults would misstate real money, so every answer says which it used.
    """
    try:
        r = await _gw_request("GET", "/v1/internal/billing/platform-fees")
        # Same decoded-body contract as the two reads above.
        if isinstance(r, dict) and "error" not in r and r:
            fees = {k: int(v) for k, v in r.items()
                    if isinstance(v, (int, float))}
            if fees:
                return fees, True
        elif isinstance(r, dict) and "error" in r:
            log.warning("platform fees read failed: %s", r.get("error"))
    except Exception as exc:  # pragma: no cover
        log.warning("platform fees read failed: %s: %s", type(exc).__name__, exc)
    return dict(DEFAULT_TIER_FEES), False


# ── 1. routing report ────────────────────────────────────────────────────── #

class RoutingReportParams(BaseModel):
    """Ask what will really run, optionally costed for a concrete run."""

    actions: int = Field(
        default=5, ge=1, le=100,
        description=(
            "How many actions to cost the estimate for. Default 5 — the size "
            "of a typical automation run."
        ),
    )
    category: str = Field(
        default="read",
        description="Action category for the base price: read | write | destructive.",
    )
    include_code_tiers: bool = Field(
        default=True,
        description="Also report the three Webbee Code tiers (terminal /model).",
    )


@chat.function(
    "llm_routing_report", action_type="read",
    data_model=LlmRoutingReportResponse,
    description=(
        "Report WHICH model actually runs for every purpose slot (reasoning, "
        "routing, execution, judge, ...), its billing tier, the per-action "
        "platform fee, and the estimated credit cost of a run. Explains why "
        "identical automations can cost wildly different amounts of credits, "
        "and flags premium models on hot paths, unpriced models and silent "
        "substitutions (failover / per-extension override)."
    ),
)
async def fn_llm_routing_report(ctx, params: RoutingReportParams) -> ActionResult:
    """Report the effective model, tier and per-action cost of every slot."""
    cfg = await _live_llm_config()
    if not cfg:
        return ActionResult.error(
            "Could not read the live LLM config, so nothing here would be "
            "trustworthy. Reporting nothing rather than guessing."
        )

    rates = normalise_rates(await _live_model_rates())
    fees, fees_are_live = await _live_tier_fees()

    slots = list(PURPOSE_SLOTS)
    if params.include_code_tiers:
        slots += list(CODE_TIER_SLOTS)

    items, warnings = [], []
    for purpose, label in slots:
        resolved = resolve_slot(purpose, label, cfg, rates, fees)
        row = resolved.model_dump()
        row["id"] = purpose
        row["kind"] = "llmroutingslot"
        row["title"] = label
        row["estimated_run_credits"] = estimate_run_cost(
            resolved.platform_fee, params.actions, params.category,
        )
        items.append(row)
        warnings.extend(resolved.warnings)

    # Substitution slots: a model that can run WITHOUT the operator picking it
    # for this turn. These are the ones that make cost look random.
    substitutions = []
    for key, label in SUBSTITUTION_SLOTS:
        model = str(cfg.get(f"{key}_model") or "").strip()
        if not model:
            continue
        rate = rates.get(model)
        tier = rate.tier if rate and rate.tier else "unpriced"
        substitutions.append({
            "slot": key, "label": label, "model": model, "tier": tier,
            "platform_fee": int(fees.get(tier, 0)) if rate else 0,
        })
        warnings.append(
            f"{label}: '{model}' ({tier}) can run without being chosen for a "
            f"given turn — a different tier here changes what a run costs."
        )

    if not fees_are_live:
        warnings.append(
            "Live platform fees were unavailable; built-in defaults "
            f"({', '.join(f'{k}={v}' for k, v in sorted(fees.items()))}) were "
            "used. Treat the credit figures as indicative."
        )

    spread = [i["estimated_run_credits"] for i in items if i["estimated_run_credits"]]
    summary = (
        f"{len(items)} slots · {params.actions} {params.category} actions ≈ "
        f"{min(spread):,}–{max(spread):,} credits depending on the slot"
        if spread else f"{len(items)} slots (no priced model resolved)"
    )

    return ActionResult.success(
        data={
            "items": items,
            "total": len(items),
            "substitutions": substitutions,
            "tier_fees": fees,
            "fees_are_live": fees_are_live,
            "category_prices": DEFAULT_CATEGORY_PRICES,
            "actions_costed": params.actions,
            "warnings": warnings,
        },
        summary=summary,
    )


# ── 2. extension model audit ─────────────────────────────────────────────── #

class AuditExtModelsParams(BaseModel):
    """Audit which extensions pin their own models instead of inheriting."""

    app_id: str = Field(
        default="",
        description="Audit ONE extension. Blank = audit every active extension.",
    )
    only_deviating: bool = Field(
        default=False,
        description="Report only apps that do NOT use the system defaults.",
    )


async def _own_models(app_id: str) -> dict | None:
    """Return ONLY what `app_id` has explicitly stored under `models`.

    ``GET /v1/apps/{id}/settings`` is the RESOLVED view: Registry merges its own
    DEFAULT_CONFIG and the Gateway merges PLATFORM_DEFAULTS into it, so an app
    that pinned nothing comes back looking fully configured. Auditing or
    resetting off that view reports phantom pins and "resets" apps that never
    stored anything -- while missing the real residue.

    The app-scope row in the unified config store is the only honest answer:
    an absent key means inherit. Returns None when it cannot be read, so the
    caller can say so instead of guessing.
    """
    try:
        data = await _gw_request(
            "GET",
            f"/v1/internal/config/app/{app_id}?tenant_id=default&app_id={app_id}",
        )
    except Exception as exc:  # pragma: no cover
        log.warning("unresolved config read failed for %s: %s", app_id, exc)
        return None
    if not isinstance(data, dict):
        return None
    section = (data.get("config") or {}).get("models")
    return section if isinstance(section, dict) else {}


@chat.function(
    "audit_extension_models", action_type="read",
    data_model=ExtensionModelAuditResponse,
    description=(
        "Audit every extension's AI Models settings and report which ones pin "
        "their own model instead of inheriting the system default — the "
        "Primary / Intake / Analysis / Router slots, plus sampling overrides. "
        "Use before resetting apps to the system defaults."
    ),
)
async def fn_audit_extension_models(ctx, params: AuditExtModelsParams) -> ActionResult:
    """Report which extensions deviate from the system model defaults."""
    if params.app_id:
        aid = await _resolve_app_id(params.app_id)
        targets = [{"app_id": aid, "display_name": aid}]
    else:
        r = await _registry_get("/v1/apps?status=active")
        if getattr(r, "status_code", 0) != 200:
            return ActionResult.error(
                f"Could not list extensions: HTTP {getattr(r, 'status_code', '?')}"
            )
        apps = r.json()
        if not isinstance(apps, list):
            return ActionResult.error("Invalid response from registry")
        targets = [
            {
                "app_id": a.get("app_id") or a.get("id") or "",
                "display_name": a.get("display_name") or a.get("name") or "",
            }
            for a in apps if isinstance(a, dict)
        ]

    items, unreadable = [], []
    for t in targets:
        aid = t["app_id"]
        if not aid:
            continue
        own = await _own_models(aid)
        if own is None:
            # Say so rather than reporting a clean bill of health for an app
            # whose settings could not be read.
            unreadable.append(aid)
            continue

        # read_policy takes a settings-shaped document; give it the app's OWN
        # section so "inherited" never registers as a pin.
        policy = read_policy(aid, {"models": own}, display_name=t["display_name"])
        if params.only_deviating and policy.uses_system_defaults:
            continue
        row = policy.model_dump()
        row["id"] = aid
        row["kind"] = "extensionmodelpolicy"
        row["title"] = policy.display_name
        items.append(row)

    deviating = [i for i in items if not i["uses_system_defaults"]]
    summary = (
        f"{len(deviating)} of {len(items)} extensions pin their own model"
        if deviating else
        f"All {len(items)} audited extensions use the system defaults"
    )
    if unreadable:
        summary += f" · {len(unreadable)} unreadable"

    return ActionResult.success(
        data={
            "items": items,
            "total": len(items),
            "deviating_count": len(deviating),
            "unreadable_app_ids": unreadable,
        },
        summary=summary,
    )


# ── 3. reset to system defaults ──────────────────────────────────────────── #

class ResetExtModelsParams(BaseModel):
    """Return extensions to the system model defaults."""

    app_id: str = Field(
        default="",
        description="Reset ONE extension. Blank = every active extension.",
    )
    reset_sampling_params: bool = Field(
        default=False,
        description=(
            "Also hand temperature/max_tokens/thinking_mode back to the "
            "platform. Since the save path drops blanks, these keys are "
            "REMOVED outright — a real inherit, not a rewrite to 0.7 / 2048."
        ),
    )
    include_pinned: bool = Field(
        default=False,
        description=(
            "Also reset extensions that pin a model deliberately. Off by "
            "default: a fleet-wide sweep is meant to clear leftover residue, "
            "not to silently undo a choice someone made on purpose. Ignored "
            "when app_id names a single extension — asking for one app IS the "
            "explicit intent."
        ),
    )
    dry_run: bool = Field(
        default=True,
        description=(
            "Preview only: report the exact before -> after per key and change "
            "nothing. Defaults to TRUE — a fleet-wide model change never fires "
            "by accident. Set false WITH confirm=true to apply."
        ),
    )
    confirm: bool = Field(
        default=False,
        description="Required to actually write. Without it the call stays a preview.",
    )


async def _prune_models(app_id: str, models: dict) -> tuple[bool, str]:
    """Rewrite the app-scope `models` subtree wholesale instead of merging.

    Both Registry and the Gateway deep-merge a settings section, so a key that
    a reset OMITS keeps its old value and goes on shadowing the platform
    cascade. ``replace_paths`` is the Gateway's own opt-in prune
    (I-PANEL-SLOT-PRUNE) and is the only way an omitted key genuinely means
    "inherit".

    Returns (ok, error). A missing service token is reported rather than
    silently skipped: pruning is what makes the reset real, so skipping it
    would turn a half-finished reset into a success message.
    """
    if not (AUTH_GW and AUTH_SERVICE_TOKEN):
        return False, "gateway service token unavailable"
    try:
        await _admin_put(
            f"/v1/internal/config/app/{app_id}?tenant_id=default&app_id={app_id}",
            {
                "config": {"models": models},
                "replace_paths": ["models"],
                "updated_by": "admin-reset-extension-models",
            },
        )
    except Exception as exc:  # pragma: no cover
        log.warning("prune failed for %s: %s", app_id, exc)
        return False, f"{type(exc).__name__}: {exc}"
    return True, ""


@chat.function(
    "reset_extension_models", action_type="write",
    effects=["update:extension_settings"], event="extension_configured",
    data_model=ExtensionModelResetReceipt,
    description=(
        "Reset extensions' AI Models settings back to the system defaults, so "
        "every model slot inherits the platform cascade instead of pinning its "
        "own model. Previews by default (dry_run) — pass dry_run=false AND "
        "confirm=true to apply."
    ),
)
async def fn_reset_extension_models(ctx, params: ResetExtModelsParams) -> ActionResult:
    """Return extension model slots to '— Default —' (inherit)."""
    if params.app_id:
        aid = await _resolve_app_id(params.app_id)
        targets = [aid]
    else:
        r = await _registry_get("/v1/apps?status=active")
        if getattr(r, "status_code", 0) != 200:
            return ActionResult.error(
                f"Could not list extensions: HTTP {getattr(r, 'status_code', '?')}"
            )
        apps = r.json()
        if not isinstance(apps, list):
            return ActionResult.error("Invalid response from registry")
        targets = [a.get("app_id") or a.get("id") or ""
                   for a in apps if isinstance(a, dict)]

    would_change, unchanged, failed = [], [], []
    skipped_pinned: list[dict] = []

    for aid in targets:
        if not aid:
            continue
        own = await _own_models(aid)
        if own is None:
            failed.append({"app_id": aid, "error": "settings unreadable"})
            continue

        before = own

        # A deliberate pin is a decision, not residue. A fleet-wide sweep that
        # silently reverts it is indistinguishable from data loss to whoever
        # made that choice -- so a bulk run skips pinned apps and SAYS it did.
        # Naming a single app_id is itself the explicit intent, so that path is
        # never skipped.
        pinned_slots = [
            slot for slot, _role in MODEL_SLOTS
            if str(before.get(slot) or "").strip()
        ]
        if pinned_slots and not params.app_id and not params.include_pinned:
            skipped_pinned.append({"app_id": aid, "pinned": sorted(pinned_slots)})
            continue

        after = build_reset_payload(
            before, reset_params=params.reset_sampling_params
        )
        changes = diff_policy(before, after)
        if not changes:
            unchanged.append(aid)
            continue

        entry = {"app_id": aid, "changes": changes}
        if params.dry_run or not params.confirm:
            would_change.append(entry)
            continue

        try:
            w = await _registry_put(f"/v1/apps/{aid}/settings", {"models": after})
            if getattr(w, "status_code", 0) == 200:
                # Registry AND the Gateway both deep-merge a settings section,
                # so the keys this reset DROPPED would survive in the store and
                # keep shadowing the cascade — the reset would report success
                # while changing nothing that matters. Prune the app-scope row
                # explicitly (I-PANEL-SLOT-PRUNE) so an absent key is a real
                # inherit.
                pruned, prune_error = await _prune_models(aid, after)
                if pruned:
                    would_change.append(entry)
                else:
                    # Do NOT claim a clean reset we could not complete: the
                    # slots were rewritten but the dropped keys are still live.
                    failed.append({
                        "app_id": aid,
                        "error": f"slots reset, but store not pruned: {prune_error}",
                    })
            else:
                failed.append({
                    "app_id": aid,
                    "error": f"HTTP {getattr(w, 'status_code', '?')}",
                })
        except Exception as exc:  # pragma: no cover
            failed.append({"app_id": aid, "error": f"{type(exc).__name__}: {exc}"})

    applied = bool(not params.dry_run and params.confirm)
    verb = "reset" if applied else "would be reset"
    summary = (
        f"{len(would_change)} extension(s) {verb} to the system defaults · "
        f"{len(unchanged)} already clean"
    )
    if failed:
        summary += f" · {len(failed)} failed"
    if skipped_pinned:
        summary += (
            f" · {len(skipped_pinned)} skipped (deliberate pin — "
            "pass include_pinned=true to reset those too)"
        )
    if not applied and would_change:
        summary += " — preview only, pass dry_run=false and confirm=true to apply"

    return ActionResult.success(
        data={
            "applied": applied,
            "changed": would_change,
            "unchanged": unchanged,
            "failed": failed,
            "skipped_pinned": skipped_pinned,
            "inherit_value": INHERIT,
        },
        summary=summary,
        refresh_panels=["tools"] if applied else None,
    )
