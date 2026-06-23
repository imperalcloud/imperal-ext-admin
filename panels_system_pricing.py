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

    return ui.Stack(children=[
        ui.Header("System Pricing", level=3),
        ui.Card(title="Platform Fee by Tier", content=fees_form),
        ui.Card(title="Credit Rate", content=rate_form),
    ], direction="v", gap=2)
