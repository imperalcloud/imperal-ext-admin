"""Admin · Developer payouts panel — pending withdrawal requests."""
from __future__ import annotations

import logging

from imperal_sdk import ui

from app import _gw_request

log = logging.getLogger("admin")


async def build_payouts(ctx, **kwargs) -> ui.Stack:
    """Right panel: pending developer payout requests."""
    row = kwargs.get("row")
    stack_items = [ui.Header("Developer Payouts", level=2)]

    try:
        result = await _gw_request("GET", "/v1/admin/payouts/pending")
    except Exception as exc:
        log.error("Failed to fetch pending payouts: %s", exc)
        return ui.Stack(children=[
            *stack_items,
            ui.Alert(title="Error", message=str(exc), type="error"),
        ])

    payouts = result if isinstance(result, list) else result.get("items", [])

    if not payouts:
        return ui.Stack(children=[
            *stack_items,
            ui.Alert(title="No pending payouts", message="No developer payouts pending.", type="info"),
        ])

    rows = []
    for p in payouts:
        tokens = p.get("tokens", 0)
        usd = p.get("usd", 0)
        rows.append({
            "id":        p.get("id", ""),
            "developer": p.get("developer", ""),
            "email":     p.get("email", ""),
            "tokens":    f"{tokens:,}",
            "usd":       f"${usd:,.2f}" if isinstance(usd, (int, float)) else str(usd),
            "requested": p.get("requested_at", p.get("created_at", "")),
        })

    table = ui.DataTable(
        columns=[
            {"key": "id",        "label": "ID"},
            {"key": "developer", "label": "Developer"},
            {"key": "email",     "label": "Email"},
            {"key": "tokens",    "label": "Tokens"},
            {"key": "usd",       "label": "USD"},
            {"key": "requested", "label": "Requested"},
        ],
        rows=rows,
        on_row_click=ui.Call("__panel__tools", section="payouts"),
    )
    stack_items.append(table)

    # Detail actions when a row is selected
    if isinstance(row, dict) and row.get("id"):
        selected_id = row["id"]
        selected_dev = row.get("developer", str(selected_id))
        stack_items.append(ui.Divider())
        stack_items.append(ui.Text(f"Selected: **{selected_dev}** — {row.get('usd', '')} ({row.get('tokens', '')} tokens)"))
        stack_items.append(ui.Row(children=[
            ui.Button(
                label="Approve Payout",
                variant="primary",
                on_click=ui.Call("review_payout", payout_id=selected_id, action="approve"),
            ),
            ui.Button(
                label="Reject Payout",
                variant="danger",
                on_click=ui.Call("review_payout", payout_id=selected_id, action="reject"),
            ),
        ]))

    return ui.Stack(children=stack_items)
