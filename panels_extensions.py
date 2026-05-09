"""Admin panel: Extensions tab.

Displays all platform extensions with expandable details, status badges,
access policy info, tools list, category/status filters, and action buttons.
"""
from __future__ import annotations

import asyncio
from typing import Any

from imperal_sdk import ui

from app import _gw_request, _registry_get, _tenant_id
from panels_sections import _cached, _fetch_extensions as _fetch_extensions_shared


# ---------------------------------------------------------------------------
# Data fetchers
# ---------------------------------------------------------------------------

async def _fetch_extension_users_raw(app_id: str) -> list[dict]:
    try:
        result = await _gw_request("GET", f"/v1/extensions/{app_id}/users")
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return result.get("users", [])
    except Exception:
        pass
    return []


async def _fetch_extension_users(app_id: str) -> list[dict]:
    return await _cached(f"ext_users:{app_id}",
                         lambda: _fetch_extension_users_raw(app_id))


async def _fetch_access_policy_raw(app_id: str, tenant_id: str = "default") -> dict:
    try:
        cfg = await _gw_request(
            "GET",
            f"/v1/internal/config/app/{app_id}?tenant_id={tenant_id}&app_id={app_id}",
        )
        return (cfg or {}).get("config", {}).get("access_policy", {"mode": "public"})
    except Exception:
        return {"mode": "public"}


async def _fetch_access_policy(app_id: str, tenant_id: str = "default") -> dict:
    return await _cached(f"ext_policy:{tenant_id}:{app_id}",
                         lambda: _fetch_access_policy_raw(app_id, tenant_id))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _status_badge(app: dict) -> ui.Badge:
    status = app.get("status", "unknown")
    color = "green" if status == "active" else ("red" if status == "suspended" else "gray")
    return ui.Badge(label=status.capitalize(), color=color)


def _build_tools_section(app: dict) -> list:
    tools = app.get("tools") or []
    if not tools:
        return []
    badges = [ui.Badge(label=t.get("name", "?"), color="gray") for t in tools[:5]]
    if len(tools) > 5:
        badges.append(ui.Text(f"+{len(tools) - 5} more", variant="caption"))
    return [
        ui.Text(f"Tools ({len(tools)})", variant="caption"),
        ui.Stack(badges, direction="h", gap=1, wrap=True),
    ]


def _build_policy_summary(app_id: str, policy: dict) -> list:
    mode = policy.get("mode", "public")
    exc = policy.get("exceptions", {})
    req = policy.get("required_scopes") or []
    dr, du = exc.get("denied_roles") or [], exc.get("denied_users") or []

    children: list = [ui.Badge(label=f"Mode: {mode.capitalize()}",
                               color="blue" if mode == "public" else "orange")]
    if req:
        sc_badges = [ui.Badge(s, color="blue") for s in req[:5]]
        if len(req) > 5:
            sc_badges.append(ui.Text(f"+{len(req) - 5}", variant="caption"))
        children.append(ui.Stack(sc_badges, direction="h", gap=1, wrap=True))
    if dr:
        children.append(ui.Stack([ui.Badge(f"deny: {r}", color="red") for r in dr],
                                 direction="h", gap=1, wrap=True))
    if du:
        children.append(ui.Text(f"{len(du)} denied user(s)", variant="caption"))
    children.append(ui.Button(
        label="Edit Policy", variant="ghost",
        on_click=ui.Call("__panel__tools", section="ext_access_policy", app_id=app_id),
    ))
    return children


def _build_expanded_content(app: dict, user_count: int | None, policy: dict) -> list:
    app_id: str = app.get("app_id") or app.get("id", "")
    status: str = app.get("status", "unknown")
    description: str = app.get("description") or ""

    kv_items = [
        {"key": "Version", "value": str(app.get("version", "\u2014"))},
        {"key": "Category", "value": str(app.get("category") or "\u2014").capitalize()},
        {"key": "Status", "value": status.capitalize()},
        {"key": "Users", "value": str(user_count) if user_count is not None else "\u2014"},
    ]

    is_active = status == "active"
    nodes: list = [ui.KeyValue(items=kv_items, columns=2)]
    if description:
        nodes.append(ui.Text(content=description, variant="caption"))

    req_scopes = app.get("required_scopes") or app.get("scopes") or []
    if req_scopes:
        nodes.append(ui.Text("Required scopes: " + ", ".join(req_scopes), variant="caption"))

    nodes.extend(_build_tools_section(app))
    nodes.append(ui.Section(title="Access Policy",
                            children=_build_policy_summary(app_id, policy)))

    nodes.append(ui.Stack(children=[
        ui.Button(
            label="Suspend" if is_active else "Activate",
            variant="danger" if is_active else "primary",
            on_click=ui.Call("suspend_extension" if is_active else "activate_extension",
                             app_id=app_id),
        ),
        ui.Button(
            label="Settings", variant="primary",
            on_click=ui.Call("__panel__tools", section="ext_settings", app_id=app_id),
        ),
        ui.Button(
            label="Manage Users", variant="ghost",
            on_click=ui.Call("__panel__tools", section="ext_users", app_id=app_id),
        ),
    ], direction="h", gap=2))
    return nodes


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

async def build_extensions(ctx: Any, category_filter: str = "",
                           status_filter: str = "", **kwargs) -> ui.Stack:
    extensions = await _fetch_extensions_shared()
    if not extensions:
        return ui.Stack(children=[
            ui.Header(text="Extensions", level=3),
            ui.Empty(message="No extensions registered", icon="puzzle"),
        ], direction="v", gap=4)

    categories = sorted({e.get("category", "") for e in extensions if e.get("category")})
    cat_options = [{"value": "", "label": "All Categories"}] + [
        {"value": c, "label": c.capitalize()} for c in categories
    ]
    status_options = [
        {"value": "", "label": "All Status"},
        {"value": "active", "label": "Active"},
        {"value": "inactive", "label": "Inactive"},
    ]

    filtered = extensions
    if category_filter:
        filtered = [e for e in filtered if e.get("category") == category_filter]
    if status_filter == "active":
        filtered = [e for e in filtered if e.get("status") == "active"]
    elif status_filter == "inactive":
        filtered = [e for e in filtered if e.get("status") != "active"]

    filter_bar = ui.Stack([
        ui.Select(options=cat_options, value=category_filter, param_name="category_filter",
                  on_change=ui.Call("__panel__tools", section="extensions",
                                   status_filter=status_filter)),
        ui.Select(options=status_options, value=status_filter, param_name="status_filter",
                  on_change=ui.Call("__panel__tools", section="extensions",
                                   category_filter=category_filter)),
    ], direction="h", gap=2)

    _app_ids = [app.get("app_id") or app.get("id", "") for app in filtered]
    fetch_users = len(filtered) < 15

    _tid = _tenant_id(ctx)
    if fetch_users:
        _user_results, _policy_results = await asyncio.gather(
            asyncio.gather(*[_fetch_extension_users(aid) for aid in _app_ids]),
            asyncio.gather(*[_fetch_access_policy(aid, _tid) for aid in _app_ids]),
        )
        user_counts = {aid: len(ul) for aid, ul in zip(_app_ids, _user_results)}
    else:
        _policy_results = await asyncio.gather(
            *[_fetch_access_policy(aid, _tid) for aid in _app_ids])
        user_counts: dict[str, int] = {}

    policies = dict(zip(_app_ids, _policy_results))

    list_items: list[ui.ListItem] = []
    for app in filtered:
        app_id = app.get("app_id") or app.get("id", "")
        display_name = app.get("display_name") or app.get("name") or app_id
        uc = user_counts.get(app_id)
        parts: list[str] = []
        if uc is not None:
            parts.append(f"{uc} users")
        # Tools count from app registration (may be 0 — actual tools in Settings > Tools)
        tc = len(app.get("tools") or [])
        if tc > 0:
            parts.append(f"{tc} tools")
        cat = app.get("category")
        if cat:
            parts.append(cat.capitalize())

        list_items.append(ui.ListItem(
            id=app_id, title=display_name, subtitle=app_id,
            badge=_status_badge(app),
            meta=" \u00b7 ".join(parts) if parts else None,
            expandable=True,
            expanded_content=_build_expanded_content(
                app=app, user_count=uc,
                policy=policies.get(app_id, {"mode": "public"})),
        ))

    count = (f"{len(filtered)} of {len(extensions)}"
             if category_filter or status_filter else str(len(extensions)))

    return ui.Stack(children=[
        ui.Header(text="Extensions", level=3, subtitle=f"{count} registered"),
        filter_bar,
        ui.List(items=list_items, searchable=True),
    ], direction="v", gap=4)
