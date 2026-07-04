"""Admin · User management panel builder.

Users page as a browse-first workspace:
- searchable/filtered user list for quick navigation
- compact read-only summaries in-place
- explicit deep editing via dedicated profile page

Avoid inline autosave here; deeper edits live in panels_user_profile.py.
"""
from __future__ import annotations

import asyncio

import logging

from imperal_sdk import ui

from panels_sections import (
    _fetch_users,
    _fetch_roles,
    _fetch_user_extensions,
    _fetch_extensions,
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


def _build_user_summary(user: dict, user_exts: list[dict], extensions: list[dict]) -> list:
    """Compact read-only summary for the users list."""
    attrs = user.get("attributes", {})
    tenant = user.get("tenant_id", "default")
    auth_method = user.get("auth_method", "password")
    last_login = user.get("last_login", "Never")
    scopes = user.get("scopes", [])
    ext_count = len(user_exts or [])

    rows: list = [
        ui.KeyValue(items=[
            {"key": "Tenant", "value": tenant},
            {"key": "Auth", "value": auth_method},
            {"key": "Last Login", "value": str(last_login) or "Never"},
            {"key": "Direct Scopes", "value": str(len(scopes))},
        ], columns=2),
    ]

    rows.extend(_build_limit_badges(attrs))

    confirmation = attrs.get("confirmation_enabled", "inherit from role")
    rows += [
        ui.Divider(),
        ui.Stack([
            ui.Badge(label=f"Extensions: {ext_count}", color="blue" if ext_count else "gray"),
            ui.Badge(label=f"Confirmation: {confirmation}", color="gray"),
        ], direction="h", gap=1, wrap=True),
    ]
    rows.extend(_build_ext_badges(extensions, user_exts))
    return rows


# ── Main builder ──────────────────────────────────────────────────────


async def build_users(ctx, role_filter: str = "",
                      status_filter: str = "", selected_user_id: str = "",
                      **kwargs):
    """User management: browse list with explicit profile editing."""
    users, roles, extensions = await asyncio.gather(
        _fetch_users(), _fetch_roles(), _fetch_extensions(),
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

    # Build user list items (browse-first, no inline autosave editors)
    filter_bar = ui.Stack([
        ui.Select(
            options=[{"value": "", "label": "All Roles"}] + role_options,
            value=role_filter, param_name="role_filter",
            on_change=ui.Call("__panel__tools", section="management",
                             status_filter=status_filter,
                             selected_user_id=selected_user_id),
        ),
        ui.Select(
            options=[
                {"value": "", "label": "All Status"},
                {"value": "active", "label": "Active"},
                {"value": "inactive", "label": "Inactive"},
            ],
            value=status_filter, param_name="status_filter",
            on_change=ui.Call("__panel__tools", section="management",
                             role_filter=role_filter,
                             selected_user_id=selected_user_id),
        ),
    ], direction="h", gap=2)

    # Build user list items (browse-first, no inline autosave editors)
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
            expanded_content=_build_user_summary(
                u, user_ext_map.get(uid, []),
            ),
            actions=[
                ui.Button(
                    "Open Profile",
                    variant="secondary",
                    on_click=ui.Call("__panel__tools", section="user_profile", user_id=uid),
                ),
            ],
        ))

    count = (f"{len(filtered)} of {len(users)} users"
             if role_filter or status_filter else f"{len(users)} users")

    return ui.Stack(children=[
        ui.Header("User Management", level=3),
        ui.Text("Browse users here; open a profile for explicit editing.", variant="caption"),
        filter_bar,
        ui.Text(count, variant="caption"),
        ui.Card(
            title="Create New User",
            content=ui.Form(action="create_user", submit_label="Create User",
                children=[
                    ui.Input(placeholder="Email address", param_name="email"),
                    ui.Input(placeholder="Password", param_name="password"),
                    ui.Select(options=role_options, value="user",
                              param_name="role", placeholder="Select role"),
                ]),
        ),
        ui.Card(
            title="Users",
            content=ui.List(items=user_items, searchable=True),
        ),
    ])
