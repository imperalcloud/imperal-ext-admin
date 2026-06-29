"""Admin · Full user profile editor (section switch from users list).

Matches React Full Profile: identity, role, scopes, individual
limits, ABAC attributes, extension access.
Each area in a named Section for clarity.
"""
from __future__ import annotations

import asyncio
import logging

from imperal_sdk import ui

from app import _gw_request
from panels_sections import (
    _fetch_roles, _fetch_extensions, _fetch_user_extensions,
    _fetch_scope_names, _cached,
)

log = logging.getLogger("admin")


async def _fetch_effective_scopes_raw(user_id: str) -> list[str]:
    try:
        result = await _gw_request("GET", f"/v1/scopes/effective/{user_id}")
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return result.get("expanded", result.get("scopes", []))
        return []
    except Exception:
        return []


async def _fetch_effective_scopes(user_id: str) -> list[str]:
    return await _cached(
        f"eff_scopes:{user_id}",
        lambda: _fetch_effective_scopes_raw(user_id),
    )


async def _fetch_user_billing(user_id: str) -> tuple[dict, dict]:
    """Subscription (plan/status/renewal) + wallet for a user. Both gateway
    endpoints key on the canonical imperal_id — same truth the user's own
    billing extension reads. Best-effort: never breaks the profile editor."""
    async def _sub():
        return await _gw_request("GET", f"/v1/billing/internal/subscription/{user_id}")

    async def _bal():
        return await _gw_request("GET", f"/v1/billing/internal/balance/{user_id}")

    sub, bal = await asyncio.gather(_sub(), _bal())
    sub = sub if isinstance(sub, dict) and "error" not in sub else {}
    bal = bal if isinstance(bal, dict) and "error" not in bal else {}
    return sub, bal


def _role_default(roles, role_name, field, fallback) -> str:
    r = next((r for r in roles if r.get("name") == role_name), None)
    if r and r.get(field) is not None:
        return str(r[field])
    return str(fallback)


async def build_user_profile(ctx, user_id: str = "", **kwargs):
    if not user_id:
        return ui.Alert(message="No user selected", type="error")

    async def _get_user():
        return await _gw_request("GET", f"/v1/users/{user_id}")

    user = await _cached(f"user:{user_id}", _get_user)
    if not isinstance(user, dict) or "error" in user:
        return ui.Alert(message=f"User {user_id} not found", type="error")

    roles, all_scopes, extensions, user_exts, effective, billing = await asyncio.gather(
        _fetch_roles(), _fetch_scope_names(), _fetch_extensions(),
        _fetch_user_extensions(user_id), _fetch_effective_scopes(user_id),
        _fetch_user_billing(user_id),
    )
    sub_data, bal_data = billing

    email = user.get("email", "?")
    role = user.get("role", "user")
    is_active = user.get("is_active", True)
    scopes = user.get("scopes", [])
    attrs = user.get("attributes", {})
    tenant = user.get("tenant_id", "default")
    auth_method = user.get("auth_method", "password")
    last_login = user.get("last_login", "Never")

    role_options = [
        {"value": r.get("name", ""),
         "label": r.get("display_name", r.get("name", ""))}
        for r in roles
    ]

    nodes: list = [
        ui.Button(
            "\u2190 Back to Users", variant="ghost",
            on_click=ui.Call("__panel__tools", section="management"),
        ),
        ui.Header(email, level=3, subtitle=user_id),

        # ── Identity ──────────────────────────────────────────────
        ui.Section(title="Identity", children=[
            ui.KeyValue(items=[
                {"key": "Imperal ID", "value": user_id},
                {"key": "Tenant", "value": tenant},
                {"key": "Auth Method", "value": auth_method},
                {"key": "Last Login", "value": str(last_login) or "Never"},
            ], columns=2),
        ]),

        # ── Role & Status ─────────────────────────────────────────
        ui.Section(title="Role & Status", children=[
            ui.Text("Role", variant="caption"),
            ui.Select(
                options=role_options, value=role,
                param_name="role",
                on_change=ui.Call("update_user", user_id=user_id),
            ),
            ui.Toggle(
                label="Account active", value=is_active,
                param_name="is_active",
                on_change=ui.Call("update_user", user_id=user_id),
            ),
        ]),

        # ── User Scopes ───────────────────────────────────────────
        ui.Section(
            title=f"User Scopes ({len(scopes)})",
            children=[
                ui.TagInput(
                    values=scopes, suggestions=all_scopes,
                    param_name="scopes", placeholder="Add scope...",
                    grouped_by=":",
                    on_change=ui.Call("update_user", user_id=user_id),
                ),
            ],
        ),
    ]

    # ── Subscription & Billing ─────────────────────────────────────
    # Sourced from the gateway billing endpoints (keyed by imperal_id) so the
    # admin sees the user's REAL plan + renewal date + wallet — the same truth
    # the user's own billing extension reads.
    plan = (sub_data.get("plan") or bal_data.get("plan") or "free")
    sub_status = (sub_data.get("status") or "unknown")
    expires = sub_data.get("expires_at")
    cancel = bool(sub_data.get("cancel_at_period_end"))
    balance = int(bal_data.get("balance") or 0)
    cap = int(bal_data.get("cap") or 0)
    renew_key = "Cancels on" if cancel else "Renews"
    billing_items = [
        {"key": "Plan", "value": str(plan).upper()},
        {"key": "Status", "value": str(sub_status)},
        {"key": renew_key, "value": str(expires) if expires else "—"},
        {"key": "Token balance",
         "value": (f"{balance:,} / {cap:,}" if cap else f"{balance:,}")},
    ]
    nodes.insert(4, ui.Section(title="Subscription & Billing", children=[
        ui.KeyValue(items=billing_items, columns=2),
    ]))

    # ── Effective Scopes (role + user combined) ────────────────────
    if effective:
        eff_badges = [ui.Badge(label=s, color="blue")
                      for s in effective[:20]]
        if len(effective) > 20:
            eff_badges.append(
                ui.Badge(f"+{len(effective) - 20} more", color="gray"))
        nodes.append(ui.Section(
            title=f"Effective Scopes ({len(effective)})",
            collapsible=True,
            children=[
                ui.Text("Combined from role defaults + user overrides",
                        variant="caption"),
                ui.Stack(eff_badges, direction="h", gap=1, wrap=True),
            ],
        ))

    # ── Individual Limits ──────────────────────────────────────────
    nodes.append(ui.Section(
        title="Individual Limits",
        children=[
            ui.Text("Leave empty to inherit from role defaults",
                    variant="caption"),
            ui.Form(
                action="update_user_limits",
                submit_label="Save Limits",
                defaults={"user_id": user_id},
                children=[
                    ui.Text("Monthly action limit", variant="caption"),
                    ui.Input(
                        param_name="monthly_action_limit",
                        value=str(attrs.get("monthly_action_limit", "")),
                        placeholder=f"Role default: {_role_default(roles, role, 'monthly_action_limit', 500)}",
                    ),
                    ui.Text("Max concurrent tasks", variant="caption"),
                    ui.Input(
                        param_name="max_concurrent_tasks",
                        value=str(attrs.get("max_concurrent_tasks", "")),
                        placeholder=f"Role default: {_role_default(roles, role, 'max_concurrent_tasks', 3)}",
                    ),
                    ui.Text("History window (messages)", variant="caption"),
                    ui.Input(
                        param_name="context_window",
                        value=str(attrs.get("context_window", "")),
                        placeholder=f"Role default: {_role_default(roles, role, 'context_window', 20)}",
                    ),
                ],
            ),
        ],
    ))

    # ── Custom Attributes (ABAC) ───────────────────────────────────
    display_attrs = {
        k: v for k, v in attrs.items()
        if k not in ("monthly_action_limit", "max_concurrent_tasks",
                     "context_window", "confirmation_enabled",
                     "confirmation_skip_read")
    }
    attr_children: list = []
    if display_attrs:
        attr_children.append(ui.KeyValue(
            items=[{"key": k, "value": str(v)}
                   for k, v in display_attrs.items()],
            columns=2,
        ))
        for k in display_attrs:
            attr_children.append(ui.Button(
                f"Remove \u201c{k}\u201d", variant="ghost",
                on_click=ui.Call("remove_user_attribute",
                                 user_id=user_id, attr_key=k),
            ))
    else:
        attr_children.append(
            ui.Text("No custom attributes", variant="caption"))

    attr_children.append(ui.Form(
        action="set_user_attribute",
        submit_label="Add Attribute",
        defaults={"user_id": user_id},
        children=[
            ui.Stack([
                ui.Input(param_name="attr_key", placeholder="Key"),
                ui.Input(param_name="attr_value", placeholder="Value"),
            ], direction="h", gap=2),
        ],
    ))
    nodes.append(ui.Section(
        title=f"Custom Attributes ({len(display_attrs)})",
        collapsible=True,
        children=attr_children,
    ))

    # ── Extension Access ───────────────────────────────────────────
    if user_exts:
        ue_map = {e.get("app_id"): e for e in user_exts}
        ext_badges = []
        for ext in extensions:
            app_id = ext.get("app_id", "")
            name = ext.get("display_name", app_id)
            ue = ue_map.get(app_id)
            if ue is None:
                continue
            enabled = ue.get("enabled", True)
            has_access = ue.get("has_access", True)
            if not has_access or not enabled:
                ext_badges.append(
                    ui.Badge(label=f"{name} (off)", color="red"))
            elif ue.get("source") == "role_default":
                ext_badges.append(
                    ui.Badge(label=f"{name} (role)", color="gray"))
            else:
                ext_badges.append(ui.Badge(label=name, color="blue"))

        if ext_badges:
            nodes.append(ui.Section(
                title="Extension Access",
                children=[
                    ui.Stack(ext_badges, direction="h", gap=1, wrap=True),
                ],
            ))

    # ── Danger Zone ────────────────────────────────────────────────
    if is_active:
        nodes.append(ui.Divider())
        nodes.append(ui.Button(
            "Deactivate User", variant="danger",
            on_click=ui.Call("deactivate_user", user_id=user_id),
        ))

    return ui.Stack(children=nodes)
