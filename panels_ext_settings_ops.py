"""Admin · Extension Settings — Skeleton, Alerts, Router, Session, Context tabs.

Called from panels_ext_settings.py tab router. Returns list of UINodes.
"""
from __future__ import annotations

import json

from imperal_sdk import ui


# ── Skeleton tab ──────────────────────────────────────────────────────

_TTL_OPTIONS = [
    {"value": "15", "label": "15 seconds"},
    {"value": "30", "label": "30 seconds"},
    {"value": "60", "label": "1 minute"},
    {"value": "120", "label": "2 minutes"},
    {"value": "300", "label": "5 minutes"},
    {"value": "600", "label": "10 minutes"},
    {"value": "3600", "label": "1 hour"},
]


def _fmt_section_name(name: str) -> str:
    return name.replace("_", " ").title()


def build_skeleton_tab(app_id: str, settings: dict) -> list:
    skel = settings.get("skeleton", {})
    sections = skel.get("sections") or []
    if not sections:
        return [ui.Empty(message="No skeleton sections registered", icon="Database")]

    # Build defaults with current values for ALL fields
    defaults = {"app_id": app_id}
    for s in sections:
        name = s.get("section_name", "unknown")
        defaults[f"skel_ttl_{name}"] = str(s.get("ttl", 60))
        defaults[f"skel_alert_{name}"] = str(s.get("alert_on_change", False)).lower()

    form_children: list = []
    for s in sections:
        name = s.get("section_name", "unknown")
        ttl = str(s.get("ttl", 60))
        alert = s.get("alert_on_change", False)
        refresh = s.get("refresh_activity", "")
        alert_act = s.get("alert_activity", "")

        section_children: list = [
            ui.Text("Refresh every", variant="caption"),
            ui.Select(
                param_name=f"skel_ttl_{name}",
                value=ttl,
                options=_TTL_OPTIONS,
            ),
            ui.Toggle(
                label="Alert on change",
                param_name=f"skel_alert_{name}",
                value=alert,
            ),
            ui.Text(f"Refresh: {refresh}", variant="caption"),
        ]
        if alert_act:
            section_children.append(ui.Text(f"Alert: {alert_act}", variant="caption"))

        form_children.append(ui.Section(title=_fmt_section_name(name), children=section_children))

    return [ui.Form(
        action="save_ext_skeleton",
        submit_label="Save Skeleton Settings",
        defaults=defaults,
        children=form_children,
    )]


# ── Alerts tab ────────────────────────────────────────────────────────

def build_alerts_tab(app_id: str, settings: dict) -> list:
    a = settings.get("alerts", {})
    return [
        ui.Form(
            action="save_ext_alerts",
            submit_label="Save Alerts",
            defaults={
                "app_id": app_id,
                "enabled": bool(a.get("enabled", True)),
                "cooldown_seconds": str(a.get("cooldown_seconds", 60)),
                "max_per_hour": str(a.get("max_per_hour", 10)),
            },
            children=[
                ui.Toggle(
                    label="Enable proactive messaging",
                    param_name="enabled",
                    value=bool(a.get("enabled", True)),
                ),
                ui.Text("Cooldown (seconds)", variant="caption"),
                ui.Input(
                    param_name="cooldown_seconds",
                    value=str(a.get("cooldown_seconds", 60)),
                    placeholder="60",
                ),
                ui.Text("Max alerts per hour", variant="caption"),
                ui.Input(
                    param_name="max_per_hour",
                    value=str(a.get("max_per_hour", 10)),
                    placeholder="10",
                ),
            ],
        ),
    ]


# ── Router tab ────────────────────────────────────────────────────────

_FALLBACK_OPTIONS = [
    {"value": "first_tool", "label": "First tool"},
    {"value": "all_tools", "label": "All tools"},
    {"value": "none", "label": "None"},
    {"value": "error", "label": "Error"},
]


def build_router_tab(app_id: str, settings: dict) -> list:
    r = settings.get("router", {})
    return [
        ui.Form(
            action="save_ext_router",
            submit_label="Save Router",
            defaults={
                "app_id": app_id,
                "enabled": bool(r.get("enabled", True)),
                "timeout_ms": str(r.get("timeout_ms", 3000)),
                "fallback": r.get("fallback", "first_tool"),
            },
            children=[
                ui.Toggle(
                    label="Enable LLM routing",
                    param_name="enabled",
                    value=bool(r.get("enabled", True)),
                ),
                ui.Text("Timeout (ms, 500\u201310000)", variant="caption"),
                ui.Input(
                    param_name="timeout_ms",
                    value=str(r.get("timeout_ms", 3000)),
                    placeholder="3000",
                ),
                ui.Text("Fallback strategy", variant="caption"),
                ui.Select(
                    param_name="fallback",
                    value=r.get("fallback", "first_tool"),
                    options=_FALLBACK_OPTIONS,
                ),
            ],
        ),
    ]


# ── Session tab ───────────────────────────────────────────────────────

def build_session_tab(app_id: str, settings: dict) -> list:
    s = settings.get("session", {})
    return [
        ui.Form(
            action="save_ext_session",
            submit_label="Save Session",
            defaults={
                "app_id": app_id,
                "timeout_hours": str(s.get("timeout_hours", 24)),
                "max_history": str(s.get("max_history", 40)),
                "compress_at": str(s.get("compress_at", 30)),
                "history_ttl_days": str(s.get("history_ttl_days", 7)),
            },
            children=[
                ui.Text("Session timeout (hours)", variant="caption"),
                ui.Input(
                    param_name="timeout_hours",
                    value=str(s.get("timeout_hours", 24)),
                    placeholder="24",
                ),
                ui.Text("Max history messages", variant="caption"),
                ui.Input(
                    param_name="max_history",
                    value=str(s.get("max_history", 40)),
                    placeholder="40",
                ),
                ui.Text("Compress at", variant="caption"),
                ui.Input(
                    param_name="compress_at",
                    value=str(s.get("compress_at", 30)),
                    placeholder="30",
                ),
                ui.Text("History TTL (days)", variant="caption"),
                ui.Input(
                    param_name="history_ttl_days",
                    value=str(s.get("history_ttl_days", 7)),
                    placeholder="7",
                ),
            ],
        ),
    ]


# ── Context tab ───────────────────────────────────────────────────────

def build_context_tab(app_id: str, settings: dict) -> list:
    c = settings.get("context") or {}
    mr = c.get("max_tool_rounds")
    mrt = c.get("max_result_tokens")
    kr = c.get("keep_recent_verbatim")
    return [
        ui.Text(
            "Per-extension context limits. Empty = inherit platform defaults.",
            variant="caption",
        ),
        ui.Form(
            action="save_ext_context",
            submit_label="Save Context",
            defaults={
                "app_id": app_id,
                "max_tool_rounds": str(mr) if mr is not None else "",
                "max_result_tokens": str(mrt) if mrt is not None else "",
                "keep_recent_verbatim": str(kr) if kr is not None else "",
            },
            children=[
                ui.Text("Max tool rounds (platform default: 10)", variant="caption"),
                ui.Input(
                    param_name="max_tool_rounds",
                    value=str(mr) if mr is not None else "",
                    placeholder="10",
                ),
                ui.Text("Max result size tokens (platform default: 3000)", variant="caption"),
                ui.Input(
                    param_name="max_result_tokens",
                    value=str(mrt) if mrt is not None else "",
                    placeholder="3000",
                ),
                ui.Text("Keep recent verbatim (platform default: 6)", variant="caption"),
                ui.Input(
                    param_name="keep_recent_verbatim",
                    value=str(kr) if kr is not None else "",
                    placeholder="6",
                ),
            ],
        ),
        ui.Button(
            label="Clear overrides (use platform defaults)",
            variant="ghost",
            on_click=ui.Call("save_ext_context", app_id=app_id,
                             max_tool_rounds="", max_result_tokens="",
                             keep_recent_verbatim=""),
        ),
    ]
