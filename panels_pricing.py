"""Admin · LLM Pricing panel — CRUD UI for llm_model_rates table (Sprint 4).

Reads via auth-gw GET /v1/internal/billing/model-rates.
Saves/deletes via handlers_pricing.py action handlers.
"""
from __future__ import annotations

import logging

import httpx
from imperal_sdk._shared_http import shared_http
from imperal_sdk import ui

from app import AUTH_GW, AUTH_SERVICE_TOKEN

log = logging.getLogger("admin")


_TIER_OPTIONS = [
    {"value": "economy",  "label": "Economy"},
    {"value": "standard", "label": "Standard"},
    {"value": "premium",  "label": "Premium"},
]


async def _fetch_rates() -> list[dict]:
    """Fetch all rates (including unavailable) for admin display."""
    if not AUTH_GW or not AUTH_SERVICE_TOKEN:
        return []
    url = (
        f"{AUTH_GW.rstrip('/')}"
        "/v1/internal/billing/model-rates?include_unavailable=true"
    )
    try:
        async with shared_http(timeout=5.0) as client:
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
    rates = await _fetch_rates()

    # DataTable cells are PLAIN STRINGS only — a UINode in a cell renders as
    # "[object Object]" (live 2026-07-12). Row actions follow the Payouts
    # pattern instead: on_row_click selects the row -> the form below edits it.
    rows = []
    for r in rates:
        model_id = r.get("id", "")
        rows.append({
            "id": model_id,
            "tier": r.get("tier", ""),
            "input": f"${float(r.get('input_cost_per_1k', 0)):.4f}",
            "output": f"${float(r.get('output_cost_per_1k', 0)):.4f}",
            "available": "Yes" if r.get("is_available", True)
                         else "No (disabled)",
        })

    # Row click (payouts pattern) OR explicit edit_id -> edit mode.
    _clicked = kwargs.get("row")
    edit_id = kwargs.get("edit_id", "") or (
        _clicked.get("id", "") if isinstance(_clicked, dict) else "")
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
                    ui.Toggle(label="Available", param_name="is_available"),
                ],
            ),
        ],
    )

    edit_actions = None
    if edit_id and edit_row:
        _avail = bool(edit_row.get("is_available", True))
        _buttons = []
        if _avail:
            _buttons.append(ui.Button(
                label="Disable model", variant="danger", size="sm",
                on_click=ui.Call("delete_llm_model_rate", model_id=edit_id),
            ))
        else:
            _buttons.append(ui.Text(
                "Model is disabled — re-enable via Save", variant="caption",
            ))
        # Guaranteed hard-delete (2026-08-29): the soft-delete above only ever
        # sets is_available=false — the row (and every stale/wrong rate in
        # it) stays in the table forever, which is exactly what made cleanup
        # here impossible. This actually removes the row. There is no
        # separate Redis step: llm_model_rates has no cache and no sync job
        # (see imperal_kernel/billing/resolver.py), so deleting the one row
        # here already IS the complete, guaranteed delete everywhere.
        _buttons.append(ui.Button(
            label="Delete permanently", variant="danger", size="sm",
            on_click=ui.Call(
                "hard_delete_llm_model_rate", model_id=edit_id,
                confirm=(f"Permanently delete the rate row for '{edit_id}'? "
                         "This removes it from the database for good — "
                         "there is nothing to restore afterwards. If you "
                         "just want to stop a model from being used, use "
                         "\"Disable model\" instead."),
            ),
        ))
        edit_actions = ui.Stack(direction="h", gap=2, children=_buttons)

    return ui.Stack(children=[
        ui.Header("LLM Pricing", level=3),
        ui.Card(
            title=f"LLM Model Rates ({len(rates)} total)",
            content=ui.Stack(direction="v", gap=1, children=[
                ui.DataTable(
                    columns=[
                        ui.DataColumn(key="id", label="Model ID", width=280),
                        ui.DataColumn(key="tier", label="Tier", width=110),
                        ui.DataColumn(key="input", label="Input $/1k", width=110),
                        ui.DataColumn(key="output", label="Output $/1k", width=110),
                        ui.DataColumn(key="available", label="Available", width=130),
                    ],
                    rows=rows,
                    on_row_click=ui.Call("__panel__tools", section="pricing"),
                ),
                ui.Text(
                    "These rates set the model's TIER and Imperal's raw provider "
                    "cost (USD, for cost attribution). What users PAY per action "
                    "is the per-tier platform fee — set in System Pricing, not "
                    "here. Click a row to edit it.",
                    variant="caption",
                ),
            ]),
        ),
        form,
    ] + ([edit_actions] if edit_actions else []), direction="v", gap=2)
