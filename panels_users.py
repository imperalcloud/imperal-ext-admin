"""Admin · User management panel builder.

Shows a filtered, searchable list of users with expandable cards.
Per-user extensions fetched from Auth GW for accurate badges.
Full profile editing available via section switch (panels_user_profile.py).
"""
from __future__ import annotations

import asyncio

import logging

from imperal_sdk import ui

from panels_billing_analytics import (
    fetch_user_billing_index, _panel_acting, _money, _when,
)
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


def _build_billing_rows(billing: dict | None) -> list:
    """Billing at a glance: plan, how it settles, and the NEXT DUE DATE.

    Owner ask 2026-08-13 — seeing the next charge date should not require
    opening a second screen.

    Two honesty rules carried over from the analytics section:
      * "will be charged" is card-on-file, never a plan name, so a card-mode
        row without a card is called out in red instead of looking healthy;
      * an absent billing index renders NOTHING rather than a confident
        "free / no date", which would be indistinguishable from fact.
    """
    if not billing:
        return []

    stamp, rel, colour = _when(billing.get("due_at"))
    mode = billing.get("mode") or "card"
    has_card = bool(billing.get("has_card"))
    status = billing.get("status") or "—"

    if mode == "card" and not has_card:
        settles = "by card — NO CARD ON FILE"
        settle_colour = "red"
    elif mode == "card":
        settles = "by card"
        settle_colour = "green"
    elif mode == "manual":
        settles = "manually / invoice"
        settle_colour = "blue"
    else:
        settles = "free (owner-set)"
        settle_colour = "gray"

    badges = [
        ui.Badge(label=f"{billing.get('plan') or '—'} · {status}",
                 color="green" if status == "active" else "gray"),
        ui.Badge(label=settles, color=settle_colour),
    ]
    if billing.get("cancelling"):
        badges.append(ui.Badge(label="cancels at period end", color="yellow"))
    if int(billing.get("failures") or 0):
        badges.append(ui.Badge(label=f"{billing['failures']} failed attempts",
                               color="red"))

    return [
        ui.Section(title="Billing", children=[
            ui.KeyValue(items=[
                {"key": "Next due", "value": f"{stamp}  ({rel})"},
                {"key": "Amount", "value": _money(billing.get("amount_cents"))},
            ], columns=2),
            ui.Stack(badges, direction="h", gap=1, wrap=True),
        ]),
    ]


def _build_orphan_rows(orphans: list[dict], q: str = "") -> list:
    """Subscriptions whose user account no longer exists.

    Owner ask 2026-08-13: "в users я не вижу часть тех, что ты показала, где
    только ID". Those rows are NOT hidden users — their user_id is absent
    from the users table entirely (deleted accounts, subscription left
    behind). The user list therefore had nothing to render for them, while
    the billing figures still counted their money. This block is the only
    place in the admin where they are visible at all.

    Honours the search box — an orphan has only an id to match on — so a
    filtered view never contradicts itself by listing unrelated rows
    underneath the people the operator actually searched for.

    Rendered only when such rows exist, so a clean platform shows no scary
    empty panel.
    """
    if not orphans:
        return []

    needle = q.strip().lower()
    if needle:
        orphans = [o for o in orphans
                   if needle in str(o.get("user_id") or "").lower()]
        if not orphans:
            return []

    chargeable = [o for o in orphans
                  if o.get("status") == "active" and o.get("has_card")]
    money = sum(int(o.get("amount_cents") or 0) for o in chargeable)

    items = []
    for o in orphans:
        stamp, rel, _ = _when(o.get("due_at"))
        card = "card on file" if o.get("has_card") else "no card"
        items.append(ui.ListItem(
            id=str(o.get("user_id") or ""),
            title=str(o.get("user_id") or "—"),
            subtitle=f"{o.get('plan') or '—'} · {o.get('status') or '—'} · {card}",
            meta=f"{rel} · {_money(o.get('amount_cents'))}",
        ))

    return [
        ui.Alert(
            message=(
                f"{len(orphans)} subscription(s) belong to accounts that no "
                f"longer exist. {len(chargeable)} of them are still active "
                f"WITH a card ({_money(money)}) — the sweep may keep charging "
                f"a deleted customer."
            ),
            type="warning",
        ),
        ui.Accordion(sections=[{
            "id": "orphans",
            "title": f"Orphaned subscriptions ({len(orphans)})",
            "children": [ui.List(items=items)],
        }]),
    ]


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
                         plan_options: list[dict],
                         billing: dict | None = None) -> list:
    """Build expanded_content for a single user ListItem.

    ``billing`` is this user's row from the billing index (plan, status,
    settlement mode, card-on-file, next due date). It is optional because a
    billing outage must degrade this card to what it showed before rather
    than break the user list.
    """
    uid = user.get("imperal_id", user.get("id", ""))
    role = user.get("role", "user")
    is_active = user.get("is_active", True)
    scopes = user.get("scopes", [])
    attrs = user.get("attributes", {})
    tenant = user.get("tenant_id", "default")
    auth_method = user.get("auth_method", "password")
    last_login = user.get("last_login", "Never")
    # Display-only MIRROR. The value that actually governs the 2-step gate lives
    # in unified_config.user_settings (served to the kernel by the Auth GW);
    # set_user_confirmation writes there and mirrors here for this caption.
    # Rendering the effective value would cost one gateway call PER USER row
    # (the /v1/users list carries no confirmation field), so an absent mirror is
    # labelled as the role default rather than asserted to be off.
    _conf_mirror = attrs.get("confirmation_enabled")
    confirmation = (
        "role default" if _conf_mirror is None
        else f"{'on' if _conf_mirror else 'off'} (mirror)"
    )
    # Current subscription plan (from the user record if present, else "free").
    current_plan = (
        user.get("plan")
        or (user.get("subscription") or {}).get("plan")
        or attrs.get("plan")
        or "free"
    )
    # Per-user Webbee Code access override: attribute "" (inherit) | "allow" | "deny".
    coding_access = attrs.get("coding_access") or "inherit"
    # Per-user Connections (SSH/MCP) access override: same tri-state.
    connections_access = attrs.get("connections_access") or "inherit"
    # Per-user File Reader access override: same tri-state.
    file_reader_access = attrs.get("file_reader_access") or "inherit"

    rows: list = [
        ui.Section(title="Identity", children=[
            ui.KeyValue(items=[
                {"key": "Email", "value": user.get("email", "—")},
                {"key": "Imperal ID", "value": uid},
                {"key": "Tenant", "value": tenant},
                {"key": "Auth Method", "value": auth_method},
                {"key": "Last Login", "value": str(last_login) or "Never"},
                {"key": "Registered", "value": str(user.get("created_at") or "—")[:16]},
            ], columns=2),
        ]),
        *_build_billing_rows(billing),
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
        ui.Divider(),
        ui.Text("Connections (SSH / MCP targets)", variant="caption"),
        ui.Select(
            options=[
                {"value": "inherit", "label": "Plan default"},
                {"value": "allow", "label": "Allow"},
                {"value": "deny", "label": "Deny"},
            ],
            value=connections_access,
            param_name="access",
            on_change=ui.Call("set_user_connections_access", user_id=uid),
        ),
        ui.Divider(),
        ui.Text("File Reader (document ingestion)", variant="caption"),
        ui.Select(
            options=[
                {"value": "inherit", "label": "Plan default"},
                {"value": "allow", "label": "Allow"},
                {"value": "deny", "label": "Deny"},
            ],
            value=file_reader_access,
            param_name="access",
            on_change=ui.Call("set_user_file_reader_access", user_id=uid),
        ),
    ]

    rows += [
        ui.Divider(),
        ui.Text(f"Confirmation (2-step): {confirmation}", variant="caption"),
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
                    **({"is_active": True} if not is_active else {
                        "confirm": (f"Deactivate {user.get('email', uid)}? "
                                    "They lose access immediately. You can "
                                    "Activate them again any time."),
                    }),
                ),
            ),
            ui.Button(
                "Delete",
                variant="danger",
                on_click=ui.Call(
                    "hard_delete_user", user_id=uid,
                    confirm=(f"Permanently delete {user.get('email', uid)}? "
                             "This erases the account, its balance, roles and "
                             "history for good — there is nothing to restore "
                             "afterwards. If you just want to lock them out, "
                             "use Deactivate instead."),
                ),
            ),
        ], direction="h", gap=2),
    ]
    return rows


# ── Main builder ──────────────────────────────────────────────────────


async def build_users(ctx, role_filter: str = "",
                      status_filter: str = "", q: str = "", **kwargs):
    """User management: expandable cards with inline editing + filters.

    ``q`` searches EVERY identifying field server-side (id, email, all name
    variants, nickname, company, tax id, phone, city, country, role) by
    reusing the same haystack the find_users tool uses. The list's built-in
    ``searchable`` flag only filters the strings already rendered on screen,
    so before this an operator could not find a person by imperal_id or
    company at all — the value simply was not on the row.
    """
    users, roles, all_scopes, extensions, plans, billing_index = await asyncio.gather(
        _fetch_users(), _fetch_roles(), _fetch_scope_names(), _fetch_extensions(),
        _fetch_plans(), fetch_user_billing_index(_panel_acting(ctx)),
    )
    billing_map = (billing_index or {}).get("users") or {}
    orphans = (billing_index or {}).get("orphaned_subscriptions") or []

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
    if q.strip():
        # local import: panels never import handlers at module scope.
        # Reusing the tool's own haystack keeps panel search and chat search
        # answering identically — two implementations would drift.
        from handlers_user_search import _identity_haystack
        needle = q.strip().lower()
        filtered = [u for u in filtered if needle in _identity_haystack(u)]
    if role_filter:
        filtered = [u for u in filtered if u.get("role") == role_filter]
    if status_filter == "active":
        filtered = [u for u in filtered if u.get("is_active", True)]
    elif status_filter == "inactive":
        filtered = [u for u in filtered if not u.get("is_active", True)]

    # Hard render cap (2026-08-29): with no search/filter narrowing the
    # result, a large tenant (thousands of accounts) previously built one
    # ui.ListItem PER USER with no limit at all -- the page would spend
    # minutes building + serializing a payload that size and often never
    # finish rendering. The gateway itself already paginates /v1/users
    # fine; this caps what THIS panel turns into UI nodes in one response,
    # same shape as the extensions panel's own render cap.
    _RENDER_CAP = 200
    total_filtered = len(filtered)
    truncated = total_filtered > _RENDER_CAP
    if truncated:
        filtered = filtered[:_RENDER_CAP]

    # Fetch per-user extensions in parallel (max 20)
    _uids = [u.get("imperal_id", u.get("id", "")) for u in filtered[:20]]
    _ext_results = await asyncio.gather(*[_fetch_user_extensions(uid) for uid in _uids])
    user_ext_map: dict[str, list[dict]] = dict(zip(_uids, _ext_results))

    # Search box — a Form because ui.Input has no on_change; submitting
    # re-renders this section server-side with the query applied.
    search_bar = ui.Form(
        action="__panel__tools",
        submit_label="Search",
        children=[
            ui.Input(
                placeholder="Search by email, ID, name, company, phone, city…",
                param_name="q", value=q,
            ),
            ui.Select(
                options=[{"value": "management", "label": "Users"}],
                value="management", param_name="section",
            ),
        ],
    )

    # Filter bar
    filter_bar = ui.Stack([
        ui.Select(
            options=[{"value": "", "label": "All Roles"}] + role_options,
            value=role_filter, param_name="role_filter",
            on_change=ui.Call("__panel__tools", section="management",
                             status_filter=status_filter, q=q),
        ),
        ui.Select(
            options=[
                {"value": "", "label": "All Status"},
                {"value": "active", "label": "Active"},
                {"value": "inactive", "label": "Inactive"},
            ],
            value=status_filter, param_name="status_filter",
            on_change=ui.Call("__panel__tools", section="management",
                             role_filter=role_filter, q=q),
        ),
    ], direction="h", gap=2)

    # Build user list items
    #
    # The COLLAPSED row carries the four things an operator looks for before
    # opening anything: email (title), imperal_id + plan + role (subtitle),
    # and the next due date (meta). Previously the row showed email and role
    # only, so finding someone by id meant expanding cards one at a time.
    user_items = []
    for u in filtered:
        uid = u.get("imperal_id", u.get("id", ""))
        is_active = u.get("is_active", True)
        ub = billing_map.get(uid) or {}

        plan_txt = ub.get("plan") or u.get("plan") or "free"
        subtitle = f"{uid} · {plan_txt} · {u.get('role', 'user')}"

        # meta = when money next moves. Silence beats a guess: with no
        # billing row the slot stays empty rather than implying "never".
        if ub:
            stamp, rel, _ = _when(ub.get("due_at"))
            if ub.get("mode") == "card" and not ub.get("has_card"):
                meta = f"{rel} · NO CARD"
            elif ub.get("mode") in ("manual", "free"):
                meta = f"{rel} · {ub.get('mode')}"
            else:
                meta = f"{rel} · {_money(ub.get('amount_cents'))}"
        else:
            meta = ""

        user_items.append(ui.ListItem(
            id=uid,
            title=u.get("email", "?"),
            subtitle=subtitle,
            meta=meta,
            badge=ui.Badge(
                "active" if is_active else "inactive",
                color="green" if is_active else "red",
            ),
            expandable=True,
            expanded_content=_build_user_expanded(
                u, role_options, all_scopes, extensions,
                user_ext_map.get(uid, []), plan_options, ub,
            ),
        ))

    count = (f"{len(filtered)} of {total_filtered} users"
             if role_filter or status_filter or q.strip()
             else f"{len(users)} users")
    if q.strip():
        count += f" · matching “{q.strip()}”"
    if truncated:
        count += f" (showing first {_RENDER_CAP} — narrow your search or filters to see the rest)"

    return ui.Stack(children=[
        ui.Header("User Management", level=3),
        search_bar,
        filter_bar,
        ui.Text(count, variant="caption"),
        *([ui.Alert(
            title="Large result — showing a page, not everyone",
            message=(f"{total_filtered} users match right now; only the "
                     f"first {_RENDER_CAP} are rendered below so the page "
                     "loads instantly instead of stalling. Use search or "
                     "the role/status filters to narrow it down to the "
                     "person you're after."),
            type="warning",
        )] if truncated else []),
        *_build_orphan_rows(orphans, q),
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
