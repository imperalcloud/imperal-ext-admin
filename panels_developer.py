"""Admin · App review panel — pending developer submissions."""
from __future__ import annotations

import logging

from imperal_sdk import ui

from app import _gw_request

log = logging.getLogger("admin")


async def build_app_review(ctx, **kwargs) -> ui.Stack:
    """Right panel: pending app submissions with approve/reject actions."""
    row = kwargs.get("row")
    selected_id = kwargs.get("selected_id") or kwargs.get("app_id") or ""
    stack_items = [
        ui.Header("App Review", level=3,
                  subtitle="Review pending developer submissions"),
    ]

    try:
        pending = await _gw_request("GET", "/v1/admin/apps/pending")
    except Exception as exc:
        log.error("Failed to fetch pending apps: %s", exc)
        return ui.Stack(children=[
            *stack_items,
            ui.Alert(title="Error", message=str(exc), type="error"),
        ])

    apps = pending if isinstance(pending, list) else pending.get("items", [])

    if not apps:
        return ui.Stack(children=[
            *stack_items,
            ui.Empty(message="No apps pending review.", icon="ClipboardCheck"),
        ])

    # Build table rows
    rows = []
    for a in apps:
        git_url = a.get("git_url", "")
        rows.append({
            "app_id":    a.get("app_id", ""),
            "name":      a.get("display_name", a.get("name", "")),
            "developer": a.get("developer_id", a.get("developer", "")),
            "category":  a.get("category", ""),
            "git_url":   git_url[:40] + ("…" if len(git_url) > 40 else ""),
            "submitted": a.get("submitted_at", a.get("created_at", "")),
        })

    table = ui.DataTable(
        columns=[
            ui.DataColumn(key="app_id",    label="App ID"),
            ui.DataColumn(key="name",      label="Name"),
            ui.DataColumn(key="developer", label="Developer"),
            ui.DataColumn(key="category",  label="Category"),
            ui.DataColumn(key="git_url",   label="Git URL"),
            ui.DataColumn(key="submitted", label="Submitted"),
        ],
        rows=rows,
        on_row_click=ui.Call("__panel__tools", section="app_review"),
    )
    stack_items.append(table)

    # Detail actions when a row is selected
    selected = None
    if isinstance(row, dict) and row.get("app_id"):
        selected = row
    elif selected_id:
        selected = next((r for r in rows if str(r.get("app_id", "")) == str(selected_id)), None)

    if isinstance(selected, dict) and selected.get("app_id"):
        selected_id = selected["app_id"]
        stack_items.append(ui.Divider())
        stack_items.append(ui.Section(title="Selected app", children=[
            ui.KeyValue(items=[
                {"key": "App ID", "value": selected_id},
                {"key": "Name", "value": selected.get("name", "—")},
                {"key": "Developer", "value": selected.get("developer", "—")},
                {"key": "Category", "value": selected.get("category", "—")},
                {"key": "Git URL", "value": selected.get("git_url", "—")},
                {"key": "Submitted", "value": selected.get("submitted", "—")},
            ], columns=2),
            ui.Stack(direction="h", gap=1, children=[
                ui.Button(
                    label="Approve",
                    variant="primary",
                    on_click=ui.Call("review_app", app_id=selected_id, action="approve"),
                ),
                ui.Button(
                    label="Reject",
                    variant="danger",
                    on_click=ui.Call("review_app", app_id=selected_id, action="reject",
                                      reason="Does not meet quality standards"),
                ),
            ]),
        ]))

    return ui.Stack(children=stack_items)
