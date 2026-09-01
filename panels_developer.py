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

    # Build list items for pending apps with full multi-selection
    list_items = []
    for a in apps:
        app_id = a.get("app_id", "")
        name = a.get("display_name") or a.get("name") or app_id
        dev = a.get("developer_id") or a.get("developer_email") or a.get("developer", "")
        cat = a.get("category", "")
        git_url = a.get("git_url", "")
        ver = a.get("version", "")
        pricing = a.get("pricing_model", "")
        submitted = a.get("submitted_at") or a.get("created_at", "")

        meta_parts = []
        if cat:
            meta_parts.append(cat.capitalize())
        if ver:
            meta_parts.append(f"v{ver}")
        if pricing:
            meta_parts.append(pricing)
        if submitted:
            meta_parts.append(str(submitted)[:10])

        list_items.append(ui.ListItem(
            id=app_id,
            title=name,
            subtitle=f"{app_id} · by {dev}" if dev else app_id,
            meta=" · ".join(meta_parts) if meta_parts else None,
            badge=ui.Badge(label="Pending", color="yellow"),
            expandable=True,
            expanded_content=ui.Stack(gap=1, children=[
                ui.Text(f"**Git URL:** `{git_url}`" if git_url else "**Git URL:** None"),
                ui.Text(f"**Description:** {a.get('description') or a.get('short_description') or 'No description provided.'}"),
                ui.Stack(direction="h", gap=1, children=[
                    ui.Button(
                        label="Approve",
                        variant="primary",
                        on_click=ui.Call(
                            "review_app",
                            app_id=app_id,
                            action="approve",
                            confirm=f"Approve '{name}' and list it in the Marketplace?",
                        ),
                    ),
                    ui.Button(
                        label="Reject",
                        variant="danger",
                        on_click=ui.Call(
                            "review_app",
                            app_id=app_id,
                            action="reject",
                            reason="Rejected by administrator",
                            confirm=f"Reject '{name}' submission?",
                        ),
                    ),
                ]),
            ]),
        ))

    # Bulk actions definition for ui.List (native SDK DUI schema: selectable, bulk_actions)
    bulk_actions = [
        {
            "label": "Approve Selected",
            "icon": "CheckCheck",
            "variant": "primary",
            "action": ui.Call("bulk_review_apps", action="approve"),
        },
        {
            "label": "Reject Selected",
            "icon": "XCircle",
            "variant": "danger",
            "action": ui.Call("bulk_review_apps", action="reject", reason="Rejected by administrator in bulk review"),
        },
    ]

    list_view = ui.List(
        items=list_items,
        searchable=True,
        selectable=True,
        bulk_actions=bulk_actions,
    )
    stack_items.append(list_view)

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
