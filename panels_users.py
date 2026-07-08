"""Admin · User management panel builder.

Shows a filtered, searchable list of users with expandable cards.
Per-user extensions fetched from Auth GW for accurate badges.
Full profile editing available via section switch (panels_user_profile.py).
"""
from __future__ import annotations

import asyncio

import logging

from imperal_sdk import ui

from panels_sections import (
    _fetch_users,
    _fetch_roles,
    _fetch_plans,
    _fetch_extensions,
    _fetch_user_extensions,
    _fetch_scope_names,
)

log = logging.getLogger("admin")

_LIMIT_KEYS = ["monthly_action_limit", "max_concurrent_tasks", "context_window"]


# ── Local data fetchers ───────────────────────────────────────────────





# ── Helpers ───────────────────────────────────────────────────────────


def _build_limit_badges(attrs: dict) -> list:
    """Return limit override badge rows only when overrides exist."""
    items = []
    if attrs.get("monthly_action_limit"):
        items.append(f"Actions: {attrs['monthly_action_limit']}/mo")
    if attrs.get("max_concurrent_tasks"):
        items.append(f"Tasks: {attrs['max_concurrent_tasks']}")
    if attrs.get("context_window"):
        items.append(f"History: {attrs['context_window']} msgs")
    if not items:
        return []
    return [
        ui.Divider(),
        ui.Text("Limit Overrides", variant="caption"),
        ui.Stack(
            [ui.Badge(label=t, color="yellow") for t in items],
            direction="h", gap=1, wrap=True,
        ),
    ]


def _build_ext_badges(extensions: list[dict], user_exts: list[dict]) -> list:
    """Extension access badges using per-user data from Auth GW.

    Colors: blue=enabled, red=disabled, gray=role_default.
    """
    if not extensions:
        return []
    # Build lookup: app_id -> user extension record
    ue_map = {e.get("app_id"): e for e in user_exts}
    badges = []
    for ext in extensions:
        app_id = ext.get("app_id", "")
        name = ext.get("display_name", app_id)
        ue = ue_map.get(app_id)
        if ue is None:
            continue  # user has no access record for this ext
        enabled = ue.get("enabled", True)
        has_access = ue.get("has_access", True)
        policy = ue.get("access_policy_type", "")
        if not has_access or not enabled:
            badges.append(ui.Badge(label=f"{name} (off)", color="red"))
        elif policy == "role_default" or ue.get("source") == "role_default":
            badges.append(ui.Badge(label=f"{name} (role)", color="gray"))
        else:
            badges.append(ui.Badge(label=name, color="blue"))
    if not badges:
        return []
    return [
        ui.Divider(),
        ui.Text("Extensions", variant="caption"),
        ui.Stack(badges, direction="h", gap=1, wrap=True),
    ]


def _build_user_expanded(user: dict, role_options: list[dict],
                         all_scopes: list[str],
                         extensions: list[dict],
                         user_exts: list[dict],
                         plan_options: list[dict]) -> list:
    """Build expanded_content for a single user ListItem."""
    uid = user.get("imperal_id", user.get("id", ""))
    role = user.get("role", "user")
    is_active = user.get("is_active", True)
    scopes = user.get("scopes", [])
    attrs = user.get("attributes", {})
    tenant = user.get("tenant_id", "default")
    auth_method = user.get("auth_method", "password")
    last_login = user.get("last_login", "Never")
    confirmation = attrs.get("confirmation_enabled", "inherit from role")
    # Current subscription plan (from the user record if present, else "free").
    current_plan = (
        user.get("plan")
        or (user.get("subscription") or {}).get("plan")
        or attrs.get("plan")
        or "free"
    )
    # Per-user Webbee Code access override: attribute "" (inherit) | "allow" | "deny".
    coding_access = attrs.get("coding_access") or "inherit"

    rows: list = [
        ui.Section(title="Identity", children=[
            ui.KeyValue(items=[
                {"key": "Imperal ID", "value": uid},
                {"key": "Tenant", "value": tenant},
                {"key": "Auth Method", "value": auth_method},
                {"key": "Last Login", "value": str(last_login) or "Never"},
            ], columns=2),
        ]),
        ui.Section(title="Role & Status", children=[
            ui.Stack([
                ui.Select(
                    options=role_options, value=role,
                    param_name="role",
                    on_change=ui.Call("update_user", user_id=uid),
                ),
                ui.Toggle(
                    label="Active", value=is_active,
                    param_name="is_active",
                    on_change=ui.Call("update_user", user_id=uid),
                ),
            ], direction="h", gap=3),
            ui.Text("Billing plan", variant="caption"),
            ui.Select(
                # Guard against an empty plan fetch so the current value always
                # has a matching option to render.
                options=plan_options or [{"value": current_plan, "label": current_plan}],
                value=current_plan,
                param_name="plan_ref",
                on_change=ui.Call("set_user_plan", user_id=uid),
            ),
        ]),
        ui.Text(f"User Scopes ({len(scopes)})", variant="caption"),
        ui.TagInput(
            values=scopes[:10], suggestions=all_scopes,
            param_name="scopes", placeholder="Add scope...",
            grouped_by=":",
            on_change=ui.Call("update_user", user_id=uid),
        ),
    ]

    rows.extend(_build_limit_badges(attrs))
    rows.extend(_build_ext_badges(extensions, user_exts))

    rows += [
        ui.Divider(),
        ui.Text("Webbee Code", variant="caption"),
        ui.Select(
            options=[
                {"value": "inherit", "label": "Plan default"},
                {"value": "allow", "label": "Allow"},
                {"value": "deny", "label": "Deny"},
            ],
            value=coding_access,
            param_name="access",
            on_change=ui.Call("set_user_coding_access", user_id=uid),
        ),
    ]

    rows += [
        ui.Divider(),
        ui.Text(f"Confirmation: {confirmation}", variant="caption"),
        ui.Stack([
            ui.Button(
                "Edit Profile",
                variant="secondary",
                on_click=ui.Call("__panel__tools",
                                section="user_profile", user_id=uid),
            ),
            ui.Button(
                "Deactivate" if is_active else "Activate",
                variant="danger" if is_active else "primary",
                on_click=ui.Call(
                    "deactivate_user" if is_active else "update_user",
                    user_id=uid,
                    **({"is_active": True} if not is_active else {}),
                ),
            ),
            ui.Button(
                "Delete",
                variant="danger",
                on_click=ui.Call("hard_delete_user", user_id=uid),
            ),
        ], direction="h", gap=2),
    ]
    return rows


# ── Main builder ──────────────────────────────────────────────────────


async def build_users(ctx, role_filter: str = "",
                      status_filter: str = "", **kwargs):
    """User management: expandable cards with inline editing + filters."""
    users, roles, all_scopes, extensions, plans = await asyncio.gather(
        _fetch_users(), _fetch_roles(), _fetch_scope_names(), _fetch_extensions(),
        _fetch_plans(),
    )

    if not users:
        return ui.Stack(children=[
            ui.Header("User Management", level=3),
            ui.Empty(message="No users found.", icon="Users"),
        ])

    role_options = [
        {"value": r.get("name", ""),
         "label": r.get("display_name", r.get("name", ""))}
        for r in roles
    ]
    # Plan selector options — value = plan NAME (user-plan accepts name OR id, and
    # the user record carries the plan name), label = plan name.
    plan_options = [
        {"value": p.get("name", ""), "label": p.get("name", "")}
        for p in plans if p.get("name")
    ]

    # Apply filters
    filtered = users
    if role_filter:
        filtered = [u for u in filtered if u.get("role") == role_filter]
    if status_filter == "active":
        filtered = [u for u in filtered if u.get("is_active", True)]
    elif status_filter == "inactive":
        filtered = [u for u in filtered if not u.get("is_active", True)]

    # Fetch per-user extensions in parallel (max 20)
    _uids = [u.get("imperal_id", u.get("id", "")) for u in filtered[:20]]
    _ext_results = await asyncio.gather(*[_fetch_user_extensions(uid) for uid in _uids])
    user_ext_map: dict[str, list[dict]] = dict(zip(_uids, _ext_results))

    # Filter bar
    filter_bar = ui.Stack([
        ui.Select(
            options=[{"value": "", "label": "All Roles"}] + role_options,
            value=role_filter, param_name="role_filter",
            on_change=ui.Call("__panel__tools", section="management",
                             status_filter=status_filter),
        ),
        ui.Select(
            options=[
                {"value": "", "label": "All Status"},
                {"value": "active", "label": "Active"},
                {"value": "inactive", "label": "Inactive"},
            ],
            value=status_filter, param_name="status_filter",
            on_change=ui.Call("__panel__tools", section="management",
                             role_filter=role_filter),
        ),
    ], direction="h", gap=2)

    # Build user list items
    user_items = []
    for u in filtered:
        uid = u.get("imperal_id", u.get("id", ""))
        is_active = u.get("is_active", True)
        user_items.append(ui.ListItem(
            id=uid,
            title=u.get("email", "?"),
            subtitle=u.get("role", "user"),
            badge=ui.Badge(
                "active" if is_active else "inactive",
                color="green" if is_active else "red",
            ),
            expandable=True,
            expanded_content=_build_user_expanded(
                u, role_options, all_scopes, extensions,
                user_ext_map.get(uid, []), plan_options,
            ),
        ))

    count = (f"{len(filtered)} of {len(users)} users"
             if role_filter or status_filter else f"{len(users)} users")

    return ui.Stack(children=[
        ui.Header("User Management", level=3),
        filter_bar,
        ui.Text(count, variant="caption"),
        ui.Accordion(sections=[{
            "id": "create",
            "title": "Create New User",
            "children": [
                ui.Form(action="create_user", submit_label="Create User",
                        children=[
                    ui.Input(placeholder="Email address", param_name="email"),
                    ui.Input(placeholder="Password", param_name="password"),
                    ui.Select(options=role_options, value="user",
                              param_name="role", placeholder="Select role"),
                ]),
            ],
        }]),
        ui.List(items=user_items, searchable=True),
    ])
