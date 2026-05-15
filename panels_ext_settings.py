"""Admin · Extension Settings — tab router + General + read-only tabs.

Accessed via section=ext_settings&app_id=xxx&tab=general (default).
Tabs: general, models, persona, skeleton, alerts, router, session, context, tools, keys, monitoring.
"""
from __future__ import annotations

from typing import Any

from imperal_sdk import ui

from app import _registry_get, _resolve_app_id


# ── Data fetcher ──────────────────────────────────────────────────────

async def _fetch_settings(ctx, app_id: str) -> dict:
    aid = await _resolve_app_id(ctx, app_id)
    r = await _registry_get(ctx, f"/v1/apps/{aid}/settings")
    if r.status_code == 200:
        return r.json()
    return {}


# ── Tab definitions ───────────────────────────────────────────────────

_TABS = [
    ("general", "General"), ("models", "AI Models"), ("persona", "Persona"),
    ("skeleton", "Skeleton"), ("alerts", "Alerts"), ("router", "Router"),
    ("session", "Session"), ("context", "Context"), ("tools", "Tools"),
    ("keys", "API Keys"), ("monitoring", "Monitoring"),
]


def _tab_bar(app_id: str, active: str) -> ui.Stack:
    buttons = []
    for tab_id, label in _TABS:
        buttons.append(ui.Button(
            label=label,
            variant="primary" if tab_id == active else "ghost",
            on_click=ui.Call("__panel__tools",
                             section="ext_settings", app_id=app_id, tab=tab_id),
        ))
    return ui.Stack(buttons, direction="h", gap=1, wrap=True)


def _back_button() -> ui.Button:
    return ui.Button(
        label="\u2190 Back to Extensions",
        variant="ghost",
        on_click=ui.Call("__panel__tools", section="extensions"),
    )


# ── General tab ───────────────────────────────────────────────────────

def _build_general(app_id: str, data: dict) -> list:
    gen = data.get("general", {})
    return [
        ui.Form(
            action="save_ext_general",
            submit_label="Save General",
            defaults={
                "app_id": app_id,
                "display_name": gen.get("display_name", ""),
                "status": gen.get("status", "active"),
            },
            children=[
                ui.Text("Display Name", variant="caption"),
                ui.Input(
                    param_name="display_name",
                    value=gen.get("display_name", ""),
                    placeholder="Extension display name",
                ),
                ui.Text("Status", variant="caption"),
                ui.Select(
                    param_name="status",
                    value=gen.get("status", "active"),
                    options=[
                        {"value": "active", "label": "Active"},
                        {"value": "suspended", "label": "Suspended"},
                    ],
                ),
            ],
        ),
        ui.Divider(),
        ui.KeyValue(items=[
            {"key": "App ID", "value": gen.get("app_id", app_id)},
            {"key": "Version", "value": str(gen.get("version", "\u2014"))},
            {"key": "Namespace", "value": gen.get("namespace", "\u2014")},
            {"key": "Created", "value": (gen.get("created_at", "")[:10] or "\u2014")},
            {"key": "Updated", "value": (gen.get("updated_at", "")[:10] or "\u2014")},
        ], columns=2),
    ]


# ── Tools tab (read-only) ────────────────────────────────────────────

def _build_tools(data: dict) -> list:
    tools = data.get("tools") or []
    if not tools:
        return [ui.Empty(message="No tools registered", icon="wrench")]
    items = []
    for t in tools:
        name = t.get("name", "Unknown")
        activity = t.get("activity_name", "")
        desc = (t.get("description") or "")[:200]
        domains = t.get("domains") or []
        domain_badges = [ui.Badge(label=d, color="gray") for d in domains[:12]]
        if len(domains) > 12:
            domain_badges.append(ui.Text(f"+{len(domains) - 12} more",
                                         variant="caption"))
        children: list = [
            ui.Stack([
                ui.Text(name, variant="body"),
                ui.Badge(label="Active", color="green"),
            ], direction="h", gap=2, justify="between", align="center"),
            ui.Text(activity, variant="code"),
        ]
        if desc:
            children.append(ui.Text(desc, variant="caption"))
        if domain_badges:
            children.append(ui.Stack(domain_badges, direction="h", gap=1,
                                     wrap=True))
        items.append(ui.Card(title=None, content=ui.Stack(children, gap=2)))
    return items


# ── Keys tab (read-only) ─────────────────────────────────────────────

def _build_keys(data: dict) -> list:
    keys = data.get("keys") or []
    if not keys:
        return [ui.Empty(message="No API keys", icon="key")]
    return [ui.KeyValue(items=[
        {"key": "Prefix", "value": f"{k.get('prefix', '???')}..."},
        {"key": "Scope", "value": k.get("scope", "\u2014")},
        {"key": "Created", "value": (k.get("created_at", "")[:10] or "\u2014")},
    ], columns=3) for k in keys]


# ── Monitoring tab (read-only) ────────────────────────────────────────

def _build_monitoring(data: dict) -> list:
    mon = data.get("monitoring") or {}
    tracing = mon.get("tracing_enabled", False)
    return [
        ui.KeyValue(items=[
            {"key": "Tracing (SigNoz)", "value": "Enabled" if tracing else "Disabled"},
            {"key": "Namespace", "value": mon.get("namespace", "\u2014")},
        ], columns=2),
        ui.Badge(
            label="Enabled" if tracing else "Disabled",
            color="green" if tracing else "gray",
        ),
    ]


# ── Main builder ──────────────────────────────────────────────────────

async def build_ext_settings(ctx: Any, app_id: str = "",
                             tab: str = "general", **kwargs) -> ui.Stack:
    if not app_id:
        return ui.Alert(title="No extension selected", message="app_id required", type="error")

    settings = await _fetch_settings(ctx, app_id)
    if not settings:
        return ui.Alert(title="Settings not found",
                        message=f"Could not load settings for '{app_id}'", type="error")

    display_name = settings.get("general", {}).get("display_name", app_id)

    if tab == "general":
        content = _build_general(app_id, settings)
    elif tab == "tools":
        content = _build_tools(settings)
    elif tab == "keys":
        content = _build_keys(settings)
    elif tab == "monitoring":
        content = _build_monitoring(settings)
    else:
        from panels_ext_settings_ai import build_models_tab, build_persona_tab
        from panels_ext_settings_ops import (
            build_skeleton_tab, build_alerts_tab, build_router_tab,
            build_session_tab, build_context_tab,
        )
        tab_map = {
            "models": lambda: build_models_tab(app_id, settings),
            "persona": lambda: build_persona_tab(app_id, settings),
            "skeleton": lambda: build_skeleton_tab(app_id, settings),
            "alerts": lambda: build_alerts_tab(app_id, settings),
            "router": lambda: build_router_tab(app_id, settings),
            "session": lambda: build_session_tab(app_id, settings),
            "context": lambda: build_context_tab(app_id, settings),
        }
        builder = tab_map.get(tab)
        content = builder() if builder else [ui.Text(f"Unknown tab: {tab}")]

    return ui.Stack(children=[
        _back_button(),
        ui.Header(text=f"{display_name} \u2014 Settings", level=3, subtitle=app_id),
        _tab_bar(app_id, tab),
        ui.Divider(),
        *content,
    ], direction="v", gap=3)
