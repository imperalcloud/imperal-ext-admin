"""Admin · Extension Access Policy editor.

Full policy editing: mode select, required scopes, denied roles/users.
Role resolution shown inline (no chat messages).
Accessed via section=ext_access_policy&app_id=xxx.
"""
from __future__ import annotations

import asyncio
from typing import Any

from imperal_sdk import ui

from app import _gw_request, _registry_get, _resolve_app_id, _tenant_id
from panels_sections import _fetch_scopes, _fetch_roles


# ── Data fetcher ──────────────────────────────────────────────────────

async def _fetch_policy(app_id: str, tenant_id: str) -> dict:
    try:
        cfg = await _gw_request(
            "GET",
            f"/v1/internal/config/app/{app_id}?tenant_id={tenant_id}&app_id={app_id}",
        )
        return (cfg or {}).get("config", {}).get("access_policy",
                                                  {"mode": "public"})
    except Exception:
        return {"mode": "public"}


async def _fetch_app_functions(app_id: str) -> list[str]:
    """Fetch registered read-only function names for an extension from Registry settings + manifest."""
    try:
        from handlers_extensions import _extract_read_only_functions
        r = await _registry_get(f"/v1/apps/{app_id}/settings")
        if getattr(r, "status_code", 500) != 200:
            return []
        data = r.json() if hasattr(r, "json") else {}
        allowed = _extract_read_only_functions(app_id, data)
        if not allowed:
            return []
        return sorted(allowed)
    except Exception:
        return []


# ── Inline role resolution ────────────────────────────────────────────

def _build_role_resolution(policy: dict, all_roles: list[dict]) -> list:
    """Show which roles pass/fail this policy — inline, no chat."""
    mode = policy.get("mode", "public")
    req = policy.get("required_scopes", [])
    denied = policy.get("exceptions", {}).get("denied_roles", [])
    guest_on = policy.get("guest_enabled") is True
    raw_guest_fns = policy.get("guest_allowed_functions")
    guest_fns = (
        [str(f).strip() for f in raw_guest_fns if str(f).strip()]
        if isinstance(raw_guest_fns, list)
        else []
    )

    items: list = []
    if mode == "public" and not denied and not all_roles:
        items.append(ui.Text("All authenticated roles have access (public mode)", variant="caption"))

    seen_guest = False
    for role in all_roles:
        name = role.get("name", "")
        rs = role.get("default_scopes") or []

        if name == "guest":
            seen_guest = True
            if name in denied:
                status, color = "DENIED (role exception)", "red"
            elif guest_on and guest_fns:
                status, color = f"PARTIAL ({len(guest_fns)} fns)", "green"
            else:
                status, color = "DENIED (deny-by-default)", "red"
        elif name in denied:
            status, color = "Denied (role exception)", "red"
        elif req:
            has_all = all(
                r in rs or "*" in rs
                or f"{r.split(':')[0]}:*" in rs
                for r in req
            )
            if has_all:
                status, color = "Access granted", "green"
            else:
                missing = [r for r in req if r not in rs]
                status = f"Denied (missing: {', '.join(missing[:3])})"
                color = "red"
        elif mode == "restricted":
            status, color = "Denied (restricted)", "red"
        else:
            status, color = "Access granted", "green"

        items.append(ui.Stack([
            ui.Text(name, variant="body"),
            ui.Badge(label=status, color=color),
        ], direction="h", gap=2, justify="between", align="center"))

    if not seen_guest:
        if "guest" in denied:
            g_status, g_color = "DENIED (role exception)", "red"
        elif guest_on and guest_fns:
            g_status, g_color = f"PARTIAL ({len(guest_fns)} fns)", "green"
        else:
            g_status, g_color = "DENIED (deny-by-default)", "red"
        items.append(ui.Stack([
            ui.Text("guest", variant="body"),
            ui.Badge(label=g_status, color=g_color),
        ], direction="h", gap=2, justify="between", align="center"))

    return items


# ── Builder ───────────────────────────────────────────────────────────

async def build_ext_access_policy(ctx: Any, app_id: str = "",
                                  **kwargs) -> ui.Stack:
    if not app_id:
        return ui.Alert(title="No extension", message="app_id required",
                        type="error")

    aid = await _resolve_app_id(app_id)
    tid = _tenant_id(ctx)

    policy, all_scopes, all_roles, app_functions = await asyncio.gather(
        _fetch_policy(aid, tid),
        _fetch_scopes(),
        _fetch_roles(),
        _fetch_app_functions(aid),
    )

    mode = policy.get("mode", "public")
    exceptions = policy.get("exceptions", {})
    req_scopes = policy.get("required_scopes") or []
    denied_roles = exceptions.get("denied_roles") or []
    denied_users = exceptions.get("denied_users") or []
    guest_enabled = policy.get("guest_enabled") is True
    raw_guest_fns = policy.get("guest_allowed_functions")
    guest_fns = (
        [str(f).strip() for f in raw_guest_fns if str(f).strip()]
        if isinstance(raw_guest_fns, list)
        else []
    )

    scope_names = sorted(
        {s.get("name", "") for s in all_scopes if s.get("name")})
    role_names = sorted(
        {r.get("name", "") for r in all_roles if r.get("name")} | {"guest"})

    return ui.Stack(children=[
        ui.Button(
            label="\u2190 Back to Extensions",
            variant="ghost",
            on_click=ui.Call("__panel__tools", section="extensions"),
        ),
        ui.Header(
            text=f"Access Policy \u2014 {aid}",
            level=3,
            subtitle=f"Current mode: {mode}",
        ),

        # ── Access Mode ───────────────────────────────────────────
        ui.Form(
            action="set_access_policy",
            submit_label="Save Access Policy",
            defaults={"app_id": aid, "mode": mode},
            children=[
                ui.Text("Access Mode", variant="caption"),
                ui.Select(
                    param_name="mode",
                    value=mode,
                    options=[
                        {"value": "public",
                         "label": "Public \u2014 all users have access"},
                        {"value": "restricted",
                         "label": "Restricted \u2014 scope-based access"},
                    ],
                ),
            ],
        ),

        ui.Divider(),

        # ── Required Scopes ───────────────────────────────────────
        ui.Section(
            title="Required Scopes",
            children=[
                ui.Text(
                    "Scopes required for access in restricted mode",
                    variant="caption"),
                *(
                    [ui.Stack(
                        [ui.Badge(label=s, color="blue")
                         for s in req_scopes],
                        direction="h", gap=1, wrap=True,
                    )] if req_scopes
                    else [ui.Text("None", variant="caption")]
                ),
                ui.TagInput(
                    values=req_scopes,
                    suggestions=scope_names,
                    placeholder="Type to search scopes...",
                    param_name="required_scopes",
                    grouped_by=":",
                    on_change=ui.Call("set_access_policy",
                                      app_id=aid),
                ),
            ],
        ),

        # ── Denied Roles ──────────────────────────────────────────
        ui.Section(
            title="Denied Roles",
            children=[
                ui.Text(
                    "Roles explicitly blocked from this extension",
                    variant="caption"),
                *(
                    [ui.Stack(
                        [ui.Badge(label=r, color="red")
                         for r in denied_roles],
                        direction="h", gap=1, wrap=True,
                    )] if denied_roles
                    else [ui.Text("None", variant="caption")]
                ),
                ui.TagInput(
                    values=denied_roles,
                    suggestions=role_names,
                    placeholder="Type to search roles...",
                    param_name="denied_roles",
                    on_change=ui.Call("set_access_policy",
                                      app_id=aid),
                ),
            ],
        ),

        # ── Denied Users ──────────────────────────────────────────
        ui.Section(
            title="Denied Users",
            children=[
                ui.Text("User IDs explicitly blocked", variant="caption"),
                *(
                    [ui.Stack(
                        [ui.Badge(label=u, color="red")
                         for u in denied_users],
                        direction="h", gap=1, wrap=True,
                    )] if denied_users
                    else [ui.Text("None", variant="caption")]
                ),
                ui.TagInput(
                    values=denied_users,
                    suggestions=[],
                    placeholder="Enter user IDs...",
                    param_name="denied_users",
                    on_change=ui.Call("set_access_policy",
                                      app_id=aid),
                ),
            ],
        ),

        ui.Divider(),

        # ── Guest Showcase Access (Role: guest) ───────────────────
        ui.Section(
            title="Guest Showcase Access (Role: guest)",
            children=[
                ui.Text(
                    "Deny-by-default for guests. Only functions explicitly listed below are exposed when Guest Access is enabled.",
                    variant="caption",
                ),
                ui.Form(
                    action="set_access_policy",
                    submit_label="Save Guest Access",
                    defaults={
                        "app_id": aid,
                        "guest_enabled": guest_enabled,
                    },
                    children=[
                        ui.Toggle(
                            param_name="guest_enabled",
                            label="Enable Guest Access for this extension",
                            value=guest_enabled,
                        ),
                    ],
                ),
                ui.Text("Allowed Functions for Guest", variant="caption"),
                *(
                    [ui.Stack(
                        [ui.Badge(label=fn, color="green" if guest_enabled else "gray")
                         for fn in guest_fns],
                        direction="h", gap=1, wrap=True,
                    )] if guest_fns
                    else [ui.Text("None (all functions blocked for guest)", variant="caption")]
                ),
                ui.TagInput(
                    values=guest_fns,
                    suggestions=app_functions,
                    placeholder="Select functions allowed for guest...",
                    param_name="guest_allowed_functions",
                    on_change=ui.Call(
                        "set_access_policy",
                        app_id=aid,
                    ),
                ),
            ],
        ),

        ui.Divider(),

        # ── Role Resolution (inline) ──────────────────────────────
        ui.Section(
            title="Role Access Resolution",
            collapsible=True,
            children=_build_role_resolution(policy, all_roles),
        ),
    ], direction="v", gap=3)
