"""Admin · Panel declarations (sidebar + tools).

Three-panel layout per federal v4.1.8 contract:
- sidebar (slot="left"): section navigation list with selected-highlight
- tools   (slot="center", center_overlay=True): dynamic content per active section
- chat is auto-collapsed to a 380px right rail by the panel host

Click flow:
  user clicks Users in sidebar
  → on_click=ui.Call("__panel__tools", active="management")
  → host fetches __panel__tools with {active}, sets center overlay
  → host passes the `active` param through to sidebar (panel-host
    contract); sidebar re-renders with selected=True on the matching item

Refresh flow (after a write action):
  handler returns ActionResult(refresh_panels=["sidebar", "tools"])
  → host re-fetches both panels with their last params; updated user
    lists / role tables / etc. appear without a manual reload.
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
from panels_pricing import build_pricing

log = logging.getLogger("admin")


# ── Sidebar Panel (left) ─────────────────────────────────────────────

_SECTIONS = [
    {"id": "dashboard",  "label": "Dashboard",   "icon": "LayoutDashboard"},
    {"id": "management", "label": "Users",       "icon": "Users"},
    {"id": "extensions", "label": "Extensions",  "icon": "Puzzle"},
    {"id": "roles",      "label": "Roles",       "icon": "Shield"},
    {"id": "scopes",     "label": "Scopes",      "icon": "Key"},
    {"id": "audit",      "label": "Audit Log",   "icon": "FileText"},
    {"id": "system",     "label": "System",      "icon": "Settings"},
    {"id": "llm",        "label": "LLM Config",  "icon": "Brain"},
    {"id": "pricing",    "label": "LLM Pricing", "icon": "Tag"},
    {"id": "app_review", "label": "App Review",  "icon": "ClipboardCheck"},
    {"id": "payouts",    "label": "Payouts",     "icon": "Banknote"},
    {"id": "payment",    "label": "Payment",     "icon": "CreditCard"},
]


def _sidebar_item(section: dict, active: str) -> UINode:
    """Sidebar list-item that opens its section in the center panel.

    `on_click=__panel__tools` triggers the host's center-overlay routing:
    the center re-renders for the new section, and the host's center→left
    param-passthrough forwards `active` back to the sidebar so the next
    sidebar render shows `selected=True` on this item.
    """
    props = {
        "id": section["id"],
        "title": section["label"],
        "icon": section.get("icon", ""),
        "on_click": {
            "action": "call",
            "function": "__panel__tools",
            "params": {"active": section["id"]},
        },
    }
    if section["id"] == active:
        props["selected"] = True
    return UINode(type="ListItem", props=props)


@ext.panel("sidebar", slot="left", title="Administration", icon="Shield")
async def admin_sidebar(ctx, active: str = "dashboard", **kwargs):
    """Left sidebar — section navigation."""
    items = [_sidebar_item(s, active) for s in _SECTIONS]
    root = ui.List(items=items)
    # Auto-open center on first mount so the user lands on a populated workspace.
    root.props["auto_action"] = ui.Call("__panel__tools", active=active)
    return root


# ── Tools Panel (center, overlay) ────────────────────────────────────

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


@ext.panel("tools", slot="center", title="Dashboard", icon="LayoutDashboard",
           center_overlay=True)
async def admin_tools(ctx, active: str = "dashboard", section: str = "",
                       **kwargs):
    """Center panel — content switches by `active` section.

    Accepts both `active` (canonical, sent by sidebar items) and `section`
    (cross-section navigation from inside another section — e.g. Edit Profile
    from Users list, or Configure from Extensions list). kwargs carries
    downstream filter params (resource, source, hours, role_filter,
    status_filter, user_id, app_id, tab, etc.) to each section builder.

    Priority: `section` wins over `active` because the panel host re-sends the
    current `active` on every Call — a Button shipping only `section="x"`
    would otherwise be drowned by the host-supplied `active=<current>` and the
    target section would never open.
    """
    current = section or active or "dashboard"
    try:
        builder = _BUILDERS.get(current)
        if builder:
            return await builder(ctx, **kwargs)
        return await build_dashboard(ctx)
    except Exception as e:
        log.error("Panel tools error for active=%s: %s", current, e)
        return ui.Alert(
            title=f"Error loading {current}",
            message=str(e),
            type="error",
        )
