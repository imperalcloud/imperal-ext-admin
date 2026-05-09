"""Admin · Panel declarations (sidebar + tools).

Two panels reproducing the full React admin UI:
- sidebar (left): 8-section navigation with active state
- tools (right): dynamic content based on selected section
"""
from __future__ import annotations

import logging

from imperal_sdk import ui
from imperal_sdk.ui.base import UINode

from app import ext
from panels_dashboard import build_dashboard
from panels_users import build_users as build_management
from panels_user_profile import build_user_profile
from panels_sections import build_system
from panels_llm import build_llm
from panels_extensions import build_extensions
from panels_roles import build_roles
from panels_scopes import build_scopes
from panels_audit import build_audit
from panels_ext_settings import build_ext_settings
from panels_ext_access_policy import build_ext_access_policy
from panels_ext_users import build_ext_users
from panels_payment import build_payment
from panels_developer import build_app_review
from panels_payouts import build_payouts
from panels_pricing import build_pricing  # Sprint 4

log = logging.getLogger("admin")


# ── Sidebar Panel (left) ─────────────────────────────────────────────

_SECTIONS = [
    {"id": "dashboard",  "label": "Dashboard",  "icon": "LayoutDashboard"},
    {"id": "management", "label": "Users",       "icon": "Users"},
    {"id": "extensions", "label": "Extensions",  "icon": "Puzzle"},
    {"id": "roles",      "label": "Roles",       "icon": "Shield"},
    {"id": "scopes",     "label": "Scopes",      "icon": "Key"},
    {"id": "audit",      "label": "Audit Log",   "icon": "FileText"},
    {"id": "system",     "label": "System",       "icon": "Settings"},
    {"id": "llm",        "label": "LLM Config",  "icon": "Brain"},
    {"id": "pricing",    "label": "LLM Pricing", "icon": "Tag"},
    {"id": "app_review", "label": "App Review",  "icon": "ClipboardCheck"},
    {"id": "payouts",    "label": "Payouts",      "icon": "Banknote"},
    {"id": "payment",  "label": "Payment",  "icon": "CreditCard"},
]


def _sidebar_item(section: dict, active: str) -> UINode:
    """Build a ListItem UINode with icon support."""
    props = {
        "id": section["id"],
        "title": section["label"],
        "icon": section.get("icon", ""),
        "on_click": {
            "action": "call",
            "function": "__panel__sidebar",
            "params": {"active": section["id"]},
        },
    }
    if section["id"] == active:
        props["selected"] = True
    return UINode(type="ListItem", props=props)


@ext.panel("sidebar", slot="left", title="Administration", icon="Shield")
async def admin_sidebar(ctx, active: str = "dashboard", **kwargs):
    """Left sidebar: 8-section navigation list."""
    items = [_sidebar_item(s, active) for s in _SECTIONS]
    return ui.List(items=items)


# ── Tools Panel (right) ──────────────────────────────────────────────

_BUILDERS = {
    "management":        build_management,
    "user_profile":      build_user_profile,
    "extensions":        build_extensions,
    "roles":             build_roles,
    "scopes":            build_scopes,
    "audit":             build_audit,
    "system":            build_system,
    "llm":               build_llm,
    "pricing":           build_pricing,
    "ext_settings":      build_ext_settings,
    "ext_access_policy": build_ext_access_policy,
    "ext_users":         build_ext_users,
    "app_review":        build_app_review,
    "payouts":           build_payouts,
    "payment":           build_payment,
}


@ext.panel("tools", slot="right", title="Dashboard", icon="LayoutDashboard")
async def admin_tools(ctx, section: str = "dashboard", **kwargs):
    """Right panel: content switches based on selected section.

    kwargs passes through filter params (resource, source, hours, role_filter,
    status_filter, user_id, app_id, tab, etc.) to each section builder.
    """
    try:
        builder = _BUILDERS.get(section)
        if builder:
            return await builder(ctx, **kwargs)
        return await build_dashboard(ctx)
    except Exception as e:
        log.error("Panel tools error for section=%s: %s", section, e)
        return ui.Alert(
            title=f"Error loading {section}",
            message=str(e),
            type="error",
        )
