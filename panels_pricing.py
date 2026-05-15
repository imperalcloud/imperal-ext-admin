"""Admin · LLM Pricing panel — CRUD UI for llm_model_rates table (Sprint 4).

Reads via auth-gw GET /v1/internal/billing/model-rates.
Saves/deletes via handlers_pricing.py action handlers.
"""
from __future__ import annotations

import logging

import httpx
from imperal_sdk import ui

from app import AUTH_GW, AUTH_SERVICE_TOKEN

log = logging.getLogger("admin")


_TIER_OPTIONS = [
    {"value": "economy",  "label": "Economy"},
    {"value": "standard", "label": "Standard"},
    {"value": "premium",  "label": "Premium"},
]


async def _fetch_rates(ctx) -> list[dict]:
    """Fetch all rates (including unavailable) for admin display."""
    if not AUTH_GW or not AUTH_SERVICE_TOKEN:
        return []
    url = (
        f"{AUTH_GW.rstrip('/')}"
        "/v1/internal/billing/model-rates?include_unavailable=true"
    )
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                url, headers={"X-Service-Token": AUTH_SERVICE_TOKEN},
            )
        if resp.status_code != 200:
            log.warning("_fetch_rates: status=%s", resp.status_code)
            return []
        return resp.json()
    except Exception as e:
        log.warning("_fetch_rates HTTP error: %s: %s", type(e).__name__, e)
        return []


async def build_pricing(ctx, **kwargs):
    """LLM Pricing: DataTable of rates + Form to add/edit a rate.

    kwargs:
        edit_id: model_id selected for edit (form pre-fills its values)
    """
    rates = await _fetch_rates(ctx)

    rows = []
    for r in rates:
        model_id = r.get("id", "")
        rows.append({
            "id": model_id,
            "tier": r.get("tier", ""),
            "input": f"${float(r.get('input_cost_per_1k', 0)):.4f}",
            "output": f"${float(r.get('output_cost_per_1k', 0)):.4f}",
            "platform_fee": str(r.get("platform_fee_default", 0)),
            "available": "Yes" if r.get("is_available", True)
                         else "No (disabled)",
            "_actions": ui.Stack(children=[
                ui.Button(
                    label="Edit", variant="ghost", size="sm",
                    on_click=ui.Call(
                        "__panel__tools",
                        section="pricing", edit_id=model_id,
                    ),
                ),
                ui.Button(
                    label="Disable", variant="danger", size="sm",
                    on_click=ui.Call(
                        "delete_llm_model_rate", model_id=model_id,
                    ),
                ),
            ], direction="h", gap=1),
        })

    edit_id = kwargs.get("edit_id", "")
    edit_row = next(
        (r for r in rates if r.get("id") == edit_id), {},
    ) if edit_id else {}

    form = ui.Form(
        action="save_llm_model_rate",
        submit_label="Save Rate" if edit_id else "Add Rate",
        defaults={
            "model_id": edit_row.get("id", ""),
            "tier": edit_row.get("tier", "standard"),
            "input_cost_per_1k": float(edit_row.get("input_cost_per_1k", 0)),
            "output_cost_per_1k": float(edit_row.get("output_cost_per_1k", 0)),
            "platform_fee_default": int(edit_row.get("platform_fee_default", 1)),
            "is_available": bool(edit_row.get("is_available", True)),
        },
        children=[
            ui.Section(
                title=("Edit Rate" if edit_id else "Add New Rate"),
                children=[
                    ui.Text("Model ID", variant="caption"),
                    ui.Input(
                        placeholder="e.g. claude-sonnet-4-20250514",
                        param_name="model_id",
                    ),
                    ui.Text("Tier", variant="caption"),
                    ui.Select(
                        options=_TIER_OPTIONS, param_name="tier",
                    ),
                    ui.Text(
                        "Input cost per 1k tokens (USD)", variant="caption",
                    ),
                    ui.Input(
                        param_name="input_cost_per_1k",
                        placeholder="e.g. 3.0",
                    ),
                    ui.Text(
                        "Output cost per 1k tokens (USD)", variant="caption",
                    ),
                    ui.Input(
                        param_name="output_cost_per_1k",
                        placeholder="e.g. 15.0",
                    ),
                    ui.Text(
                        "Platform fee tokens (default)", variant="caption",
                    ),
                    ui.Input(
                        param_name="platform_fee_default",
                        placeholder="e.g. 5",
                    ),
                    ui.Toggle(label="Available", param_name="is_available"),
                ],
            ),
        ],
    )

    return ui.Stack(children=[
        ui.Header("LLM Pricing", level=3),
        ui.Card(
            title=f"LLM Model Rates ({len(rates)} total)",
            content=ui.DataTable(
                columns=[
                    ui.DataColumn(key="id", label="Model ID", width=240),
                    ui.DataColumn(key="tier", label="Tier", width=100),
                    ui.DataColumn(key="input", label="Input $/1k", width=100),
                    ui.DataColumn(key="output", label="Output $/1k", width=100),
                    ui.DataColumn(
                        key="platform_fee", label="Plat. Fee", width=80,
                    ),
                    ui.DataColumn(key="available", label="Available", width=120),
                    ui.DataColumn(key="_actions", label="Actions", width=160),
                ],
                rows=rows,
            ),
        ),
        form,
    ], direction="v", gap=2)
