# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors.
# Licensed under the AGPL-3.0 License.
"""Admin · System Pricing panel — edit per-tier platform fee + $→credit rate.

Prefills from the source via the internal GET endpoints; saves via the
save_platform_fees / save_token_rate handlers.
"""
from __future__ import annotations

import logging

import httpx
from imperal_sdk import ui

from app import AUTH_GW, AUTH_SERVICE_TOKEN

log = logging.getLogger("admin")

_DEFAULT_FEES = {"economy": 60, "standard": 250, "premium": 2200}
_DEFAULT_RATE = 1000
_DEFAULT_CATS = {"read": 1, "write": 5, "destructive": 10}
_DEFAULT_CODING = {"markup": 3.0, "credits_per_dollar": 1000, "min_charge": 0, "grace_cap": 1000, "low_warn_threshold": 500}


async def _get(path: str) -> dict:
    if not AUTH_GW or not AUTH_SERVICE_TOKEN:
        return {}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{AUTH_GW.rstrip('/')}{path}",
                headers={"X-Service-Token": AUTH_SERVICE_TOKEN},
            )
        if resp.status_code != 200:
            log.warning("system-pricing _get %s status=%s", path, resp.status_code)
            return {}
        return resp.json()
    except Exception as e:
        log.warning("system-pricing _get %s error: %s: %s", path, type(e).__name__, e)
        return {}


async def build_system_pricing(ctx, **kwargs):
    fees = await _get("/v1/internal/billing/platform-fees") or {}
    rate = await _get("/v1/internal/billing/token-rate") or {}
    cats = await _get("/v1/internal/billing/category-defaults") or {}
    coding = await _get("/v1/internal/billing/coding-pricing") or {}

    fees_form = ui.Form(
        action="save_platform_fees",
        submit_label="Save Platform Fees",
        defaults={
            "economy": int(fees.get("economy", _DEFAULT_FEES["economy"])),
            "standard": int(fees.get("standard", _DEFAULT_FEES["standard"])),
            "premium": int(fees.get("premium", _DEFAULT_FEES["premium"])),
        },
        children=[
            ui.Section(title="Per-action platform fee (credits)", children=[
                ui.Text("Charged per agent action on top of the extension price; "
                        "BYOLLM users are not charged this. Applies within ~1 min.",
                        variant="caption"),
                ui.Text("Economy tier", variant="caption"),
                ui.Input(param_name="economy", placeholder="e.g. 60"),
                ui.Text("Standard tier (default model)", variant="caption"),
                ui.Input(param_name="standard", placeholder="e.g. 250"),
                ui.Text("Premium tier", variant="caption"),
                ui.Input(param_name="premium", placeholder="e.g. 2200"),
            ]),
        ],
    )

    rate_form = ui.Form(
        action="save_token_rate",
        submit_label="Save Credit Rate",
        defaults={"token_rate": int(rate.get("token_rate", _DEFAULT_RATE))},
        children=[
            ui.Section(title="$ → credit conversion", children=[
                ui.Text("How many credits a customer gets per $1 on top-up. "
                        "Applies within ~1 min.", variant="caption"),
                ui.Text("Credits per $1", variant="caption"),
                ui.Input(param_name="token_rate", placeholder="e.g. 1000"),
            ]),
        ],
    )

    cats_form = ui.Form(
        action="save_category_defaults",
        submit_label="Save Default Function Prices",
        defaults={
            "read": int(cats.get("read", _DEFAULT_CATS["read"])),
            "write": int(cats.get("write", _DEFAULT_CATS["write"])),
            "destructive": int(cats.get("destructive", _DEFAULT_CATS["destructive"])),
        },
        children=[
            ui.Section(title="Default base price per action (credits)", children=[
                ui.Text(
                    "The base price charged for an extension function when its developer "
                    "has NOT set an explicit per-function price. Picked by the action's type. "
                    "This is the function's own fee (the developer earns their revenue share of "
                    "it); the platform fee above is added on top separately. Applies within ~1 min.",
                    variant="caption"),
                ui.Text("Read actions (view/list/search)", variant="caption"),
                ui.Input(param_name="read", placeholder="e.g. 1"),
                ui.Text("Write actions (create/update)", variant="caption"),
                ui.Input(param_name="write", placeholder="e.g. 5"),
                ui.Text("Destructive actions (delete/remove)", variant="caption"),
                ui.Input(param_name="destructive", placeholder="e.g. 10"),
            ]),
        ],
    )

    coding_form = ui.Form(
        action="save_coding_pricing",
        submit_label="Save Coding Pricing",
        defaults={
            "markup": float(coding.get("markup", _DEFAULT_CODING["markup"])),
            "credits_per_dollar": int(coding.get("credits_per_dollar", _DEFAULT_CODING["credits_per_dollar"])),
            "min_charge": int(coding.get("min_charge", _DEFAULT_CODING["min_charge"])),
            "grace_cap": int(coding.get("grace_cap", _DEFAULT_CODING["grace_cap"])),
            "low_warn_threshold": int(coding.get("low_warn_threshold", _DEFAULT_CODING["low_warn_threshold"])),
        },
        children=[
            ui.Section(title="Coding agent (webbee-code terminal) pricing", children=[
                ui.Text("Coding turns charge credits = real LLM cost x markup. grace_cap bounds the "
                        "in-flight overdraft (server-capped at 20000); the user is warned below the "
                        "low-balance threshold. Applies within ~1 min.", variant="caption"),
                ui.Text("Markup (x real LLM cost)", variant="caption"),
                ui.Input(param_name="markup", placeholder="e.g. 3.0"),
                ui.Text("Credits per $1", variant="caption"),
                ui.Input(param_name="credits_per_dollar", placeholder="e.g. 1000"),
                ui.Text("Minimum charge per billed turn (credits)", variant="caption"),
                ui.Input(param_name="min_charge", placeholder="e.g. 0"),
                ui.Text("In-flight grace overdraft cap (credits)", variant="caption"),
                ui.Input(param_name="grace_cap", placeholder="e.g. 1000"),
                ui.Text("Low-balance warn threshold (credits)", variant="caption"),
                ui.Input(param_name="low_warn_threshold", placeholder="e.g. 500"),
            ]),
        ],
    )

    return ui.Stack(children=[
        ui.Header("System Pricing", level=3),
        ui.Text(
            "Every paid action costs base price + platform fee. The base price is the "
            "extension function's own fee (shared with its developer); the platform fee is "
            "Imperal's LLM-resale markup (kept in full). Set the global defaults here.",
            variant="caption"),
        ui.Card(title="Platform Fee by Tier (LLM resale — Imperal keeps 100%)", content=fees_form),
        ui.Card(title="Default Function Prices (base fee — dev revenue-shared)", content=cats_form),
        ui.Card(title="Credit Rate", content=rate_form),
        ui.Card(title="Coding Agent Pricing (webbee-code terminal)", content=coding_form),
    ], direction="v", gap=2)
