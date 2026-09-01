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
        selectable=True,
        selection_key="app_id",
        bulk_actions=[
            {
                "label": "Approve Selected",
                "icon": "CheckCheck",
                "variant": "primary",
                "action": ui.Call("bulk_review_apps", action="approve"),
                "confirm": "Are you sure you want to approve all selected applications?",
            },
            {
                "label": "Reject Selected",
                "icon": "XCircle",
                "variant": "danger",
                "action": ui.Call("bulk_review_apps", action="reject", reason="Rejected by administrator in bulk review"),
                "confirm": "Are you sure you want to reject all selected applications?",
            },
        ],
    )
    stack_items.append(table)

    # Bulk actions bar if there are pending apps
    all_app_ids = [a.get("app_id") for a in apps if a.get("app_id")]
    if len(all_app_ids) > 1:
        stack_items.append(ui.Section(
            title=f"Bulk Actions ({len(all_app_ids)} pending apps)",
            children=[
                ui.Text("Approve or reject all currently pending applications in one atomic batch:"),
                ui.Stack(direction="h", gap=1, children=[
                    ui.Button(
                        label=f"Approve All ({len(all_app_ids)})",
                        variant="primary",
                        on_click=ui.Call(
                            "bulk_review_apps",
                            app_ids=all_app_ids,
                            action="approve",
                            confirm=f"Are you sure you want to bulk approve all {len(all_app_ids)} pending apps and list them in the Marketplace?",
                        ),
                    ),
                    ui.Button(
                        label=f"Reject All ({len(all_app_ids)})",
                        variant="danger",
                        on_click=ui.Call(
                            "bulk_review_apps",
                            app_ids=all_app_ids,
                            action="reject",
                            reason="Bulk rejected by administrator",
                            confirm=f"Are you sure you want to bulk reject all {len(all_app_ids)} pending apps?",
                        ),
                    ),
                ]),
            ],
        ))

    # Detail actions when a row is selected
    selected = None
    raw_app_entry = None
    if isinstance(row, dict) and row.get("app_id"):
        selected = row
    elif selected_id:
        selected = next((r for r in rows if str(r.get("app_id", "")) == str(selected_id)), None)

    if selected:
        raw_app_entry = next((a for a in apps if a.get("app_id") == selected.get("app_id")), None)

    if isinstance(selected, dict) and selected.get("app_id"):
        selected_id = selected["app_id"]
        raw = raw_app_entry or {}
        desc = raw.get("description") or raw.get("short_description") or "—"
        version = raw.get("version") or "0.1.0"
        pricing_model = raw.get("pricing_model") or "free"

        stack_items.append(ui.Divider())
        stack_items.append(ui.Section(title=f"Selected app: {selected_id}", children=[
            ui.KeyValue(items=[
                {"key": "App ID", "value": selected_id},
                {"key": "Name", "value": selected.get("name", "—")},
                {"key": "Developer", "value": selected.get("developer", "—")},
                {"key": "Category", "value": selected.get("category", "—")},
                {"key": "Version", "value": version},
                {"key": "Pricing Model", "value": pricing_model},
                {"key": "Git URL", "value": selected.get("git_url", "—")},
                {"key": "Submitted", "value": selected.get("submitted", "—")},
            ], columns=2),
            ui.Text(f"**Description:** {desc}"),
            ui.Stack(direction="h", gap=1, children=[
                ui.Button(
                    label="Approve App",
                    variant="primary",
                    on_click=ui.Call("review_app", app_id=selected_id, action="approve"),
                ),
                ui.Button(
                    label="Reject App",
                    variant="danger",
                    on_click=ui.Call(
                        "review_app", app_id=selected_id, action="reject",
                        reason="Does not meet quality standards",
                        confirm=(f"Reject '{selected_id}'? The developer will "
                                 "need to fix it and resubmit before it can "
                                 "go live."),
                    ),
                ),
            ]),
        ]))

    return ui.Stack(children=stack_items)
