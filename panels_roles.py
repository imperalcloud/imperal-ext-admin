"""Admin · Roles panel section builder.

Displays a searchable list of roles with expandable details:
scope badges, editable limits, cascade toggle, policy, user count.
All actions are inline Forms or ui.Call() — no ui.Send().
"""
from __future__ import annotations

import asyncio
import logging

from imperal_sdk import ui

from panels_sections import _fetch_users, _fetch_roles, _fetch_scope_names

log = logging.getLogger("admin")

_SCOPE_PREVIEW = 5
_USER_PREVIEW = 5


# ── Expanded content builder ──────────────────────────────────────────


def _build_role_expanded(
    role: dict,
    role_users: list[dict],
    all_scopes: list[str],
) -> list:
    """Return expanded_content nodes for a single role ListItem."""
    name = role.get("name", "")
    role_id = str(role.get("id", name))
    is_system = role.get("is_system", False)
    scopes = role.get("default_scopes", [])
    policy = role.get("confirmation_policy", "default_on")
    monthly_limit = role.get("monthly_action_limit", 500)
    max_tasks = role.get("max_concurrent_tasks", 3)
    ctx_window = role.get("context_window", 20)
    default_exts = role.get("default_extensions", [])

    nodes: list = []

    # ── Default Scopes ─────────────────────────────────────────────
    scope_count = len(scopes)
    scope_preview: list = [
        ui.Badge(s, color="blue") for s in scopes[:_SCOPE_PREVIEW]
    ]
    overflow = scope_count - _SCOPE_PREVIEW
    if overflow > 0:
        scope_preview.append(
            ui.Badge(f"+{overflow} more", color="gray"))

    nodes.append(ui.Section(
        title=f"Default Scopes ({scope_count})",
        collapsible=True,
        children=[
            ui.Stack(children=scope_preview, direction="h", gap=1,
                     wrap=True),
            ui.TagInput(
                values=scopes[:20],
                suggestions=all_scopes,
                param_name="default_scopes",
                placeholder="Add scope...",
                grouped_by=":",
                on_change=ui.Call("update_role", role_id=role_id,
                                 role_name=name, cascade=False),
            ),
            ui.Toggle(
                label="Cascade changes to existing users",
                value=False,
                param_name="cascade",
                on_change=ui.Call("update_role", role_id=role_id,
                                 role_name=name),
            ),
        ],
    ))

    # ── Default Extensions ─────────────────────────────────────────
    if default_exts:
        nodes.append(ui.Section(
            title="Default Extensions",
            children=[
                ui.Stack(
                    [ui.Badge(label=e, color="cyan") for e in default_exts],
                    direction="h", gap=1, wrap=True,
                ),
            ],
        ))

    # ── Usage Limits ───────────────────────────────────────────────
    nodes.append(ui.Section(
        title="Usage Limits",
        collapsible=True,
        children=[
            ui.Form(
                action="update_role",
                submit_label="Save Limits",
                defaults={
                    "role_id": role_id,
                    "role_name": name,
                    "monthly_action_limit": str(monthly_limit),
                    "context_window": str(ctx_window),
                },
                children=[
                    ui.Text("Monthly action limit (0 = unlimited)",
                            variant="caption"),
                    ui.Input(
                        param_name="monthly_action_limit",
                        value=str(monthly_limit),
                        placeholder="500",
                    ),
                    ui.Text("History window in messages (5\u2013200)",
                            variant="caption"),
                    ui.Input(
                        param_name="context_window",
                        value=str(ctx_window),
                        placeholder="20",
                    ),
                ],
            ),
            ui.Form(
                action="set_task_limit",
                submit_label="Save Task Limit",
                children=[
                    ui.Input(param_name="role_name", value=name,
                             placeholder=name),
                    ui.Text("Max concurrent tasks (1\u201350)",
                            variant="caption"),
                    ui.Input(
                        param_name="max_tasks",
                        value=str(max_tasks),
                        placeholder="3",
                    ),
                ],
            ),
        ],
    ))

    # ── Action Confirmation ────────────────────────────────────────
    nodes.append(ui.Section(
        title="Action Confirmation",
        children=[
            ui.Select(
                options=[
                    {"value": "enforced",
                     "label": "Enforced \u2014 always require confirmation"},
                    {"value": "default_on",
                     "label": "Default On \u2014 user can disable"},
                    {"value": "default_off",
                     "label": "Default Off \u2014 user can enable"},
                    {"value": "disabled",
                     "label": "Disabled \u2014 never ask confirmation"},
                ],
                value=policy,
                param_name="policy",
                on_change=ui.Call("set_confirmation_policy",
                                  role_name=name),
            ),
        ],
    ))

    # ── Assigned Users ─────────────────────────────────────────────
    user_count = len(role_users)
    user_nodes: list = [
        ui.Text(u.get("email", u.get("imperal_id", "?")),
                variant="body")
        for u in role_users[:_USER_PREVIEW]
    ]
    user_overflow = user_count - _USER_PREVIEW
    if user_overflow > 0:
        user_nodes.append(
            ui.Text(f"+{user_overflow} more users", variant="caption"))

    nodes.append(ui.Section(
        title=f"Assigned Users ({user_count})",
        children=user_nodes,
    ))

    # ── Destructive actions ────────────────────────────────────────
    if not is_system:
        nodes.append(ui.Divider())
        nodes.append(ui.Button(
            "Delete Role",
            variant="danger",
            on_click=ui.Call("delete_role", role_id=role_id,
                             role_name=name),
        ))

    return nodes


# ── Main builder ──────────────────────────────────────────────────────


async def build_roles(ctx, **kwargs):
    """Roles management: searchable list with expandable role cards."""
    roles, users, all_scopes = await asyncio.gather(
        _fetch_roles(), _fetch_users(), _fetch_scope_names(),
    )

    create_form = ui.Accordion(sections=[{
        "id": "create",
        "title": "Create New Role",
        "children": [
            ui.Form(
                action="create_role",
                submit_label="Create Role",
                children=[
                    ui.Text("Role name", variant="caption"),
                    ui.Input(placeholder="e.g. editor",
                             param_name="name"),
                    ui.Text("Display name", variant="caption"),
                    ui.Input(placeholder="e.g. Editor",
                             param_name="display_name"),
                    ui.Text("Default Scopes", variant="caption"),
                    ui.TagInput(
                        values=[],
                        suggestions=all_scopes,
                        param_name="default_scopes",
                        placeholder="Add scope...",
                        grouped_by=":",
                    ),
                ],
            ),
        ],
    }])

    if not roles:
        return ui.Stack(children=[
            ui.Header("Roles", level=3,
                       subtitle="Manage platform roles and permissions"),
            create_form,
            ui.Empty(
                message="No roles found. Auth Gateway may be unreachable.",
                icon="Shield",
            ),
        ])

    users_by_role: dict[str, list[dict]] = {}
    for u in users:
        role_name = u.get("role", "")
        users_by_role.setdefault(role_name, []).append(u)

    items: list = []
    for role in roles:
        name = role.get("name", "")
        display_name = role.get("display_name", name)
        is_system = role.get("is_system", False)
        scopes = role.get("default_scopes", [])
        role_users = users_by_role.get(name, [])

        badge = ui.Badge("system", color="yellow") if is_system else None

        items.append(ui.ListItem(
            id=name,
            title=display_name,
            subtitle=name,
            badge=badge,
            meta=f"{len(role_users)} users \u00b7 {len(scopes)} scopes",
            expandable=True,
            expanded_content=_build_role_expanded(
                role, role_users, all_scopes),
        ))

    return ui.Stack(children=[
        ui.Header("Roles", level=3,
                   subtitle="Manage platform roles and permissions"),
        create_form,
        ui.List(items=items, searchable=True),
    ])
