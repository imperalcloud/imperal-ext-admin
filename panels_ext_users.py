"""Admin · Extension User Management.

Per-user enable/disable for a specific extension.
Accessed via section=ext_users&app_id=xxx.
"""
from __future__ import annotations

from typing import Any

from imperal_sdk import ui

from app import _resolve_app_id
from panels_extensions import _fetch_extension_users


# ── Builder ───────────────────────────────────────────────────────────

async def build_ext_users(ctx: Any, app_id: str = "", **kwargs) -> ui.Stack:
    if not app_id:
        return ui.Alert(title="No extension", message="app_id required", type="error")

    aid = await _resolve_app_id(ctx, app_id)
    users = await _fetch_extension_users(ctx, aid)

    granted = [u for u in users if u.get("access") == "granted"]
    denied = [u for u in users if u.get("access") == "denied"]
    other = [u for u in users if u.get("access") not in ("granted", "denied")]
    sorted_users = granted + denied + other

    list_items: list[ui.ListItem] = []
    for u in sorted_users:
        uid = u.get("user_id") or u.get("imperal_id") or u.get("id", "")
        email = u.get("email", "")
        role = u.get("role", "")
        access = u.get("access", "unknown")
        has_access = access == "granted"

        badge_color = "green" if has_access else ("red" if access == "denied" else "gray")

        if has_access:
            action_btn = ui.Button(
                label="Deny Access",
                variant="danger",
                on_click=ui.Call("deny_extension", app_id=aid, user=uid),
            )
        else:
            action_btn = ui.Button(
                label="Grant Access",
                variant="primary",
                on_click=ui.Call("allow_extension", app_id=aid, user=uid),
            )

        display = email or uid
        subtitle_parts = []
        if role:
            subtitle_parts.append(f"Role: {role}")
        if uid and uid != email:
            subtitle_parts.append(uid)

        list_items.append(ui.ListItem(
            id=uid,
            title=display,
            subtitle=" \u00b7 ".join(subtitle_parts) if subtitle_parts else None,
            badge=ui.Badge(label=access.capitalize(), color=badge_color),
            expandable=True,
            expanded_content=[action_btn],
        ))

    return ui.Stack(children=[
        ui.Button(
            label="\u2190 Back to Extensions",
            variant="ghost",
            on_click=ui.Call("__panel__tools", section="extensions"),
        ),
        ui.Header(
            text=f"User Management \u2014 {aid}",
            level=3,
            subtitle=f"{len(granted)} granted, {len(denied)} denied, {len(other)} other",
        ),
        ui.Stats(children=[
            ui.Stat(label="Granted", value=str(len(granted)), color="green"),
            ui.Stat(label="Denied", value=str(len(denied)), color="red"),
            ui.Stat(label="Total", value=str(len(sorted_users))),
        ], columns=3),
        ui.List(items=list_items, searchable=True) if list_items else
        ui.Empty(message="No users found for this extension", icon="users"),
    ], direction="v", gap=3)
