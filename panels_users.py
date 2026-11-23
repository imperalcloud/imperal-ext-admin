"""Admin · Users: a list to FIND a person, a profile to change one.

Rebuilt 2026-11-23 on the owner's report ("there it is a mess: must be
convenient, must not lag, must show everything right"). What was measured in
the old screen and what replaces it:

  * One render made up to 57 gateway calls: users, roles, scopes, extensions,
    plans, the billing index and then ONE call per row for that user's
    extensions. Now three: users, roles, the billing index.
  * Every row carried a full edit card (about 6.5 KB each), built for all 50
    rows of the page whether opened or not. Now a row is four strings and a
    click that opens the profile.
  * The card's scope editor showed the first 10 scopes and saved the field
    whole: one edit of a user with more than 10 scopes deleted the rest.
    There is no editing here any more; the profile edits the full set.
  * A gateway failure read as "No users found". Now the failure is shown as a
    failure, with the gateway's own words.

Everything that changes a user lives in panels_user_profile.py.
"""
from __future__ import annotations

import asyncio
import logging

from imperal_sdk import ui

from render_cap import build_capped_list

from panels_billing_analytics import (
    fetch_user_billing_index, _panel_acting, _money, _when,
)
from panels_sections import _fetch_users_checked, _fetch_roles

log = logging.getLogger("admin")

PAGE = 50

SORTS = [
    {"value": "", "label": "Newest first"},
    {"value": "email", "label": "Email A-Z"},
    {"value": "last_login", "label": "Last login"},
]


def _uid(u: dict) -> str:
    return str(u.get("imperal_id") or u.get("id") or "")


def _name(u: dict) -> str:
    a = u.get("attributes")
    a = a if isinstance(a, dict) else {}
    return str(u.get("display_name") or a.get("display_name")
               or u.get("full_name") or a.get("full_name") or "").strip()


def _plan(u: dict, ub: dict) -> str:
    """The plan a row names. ONE rule: the subscription row of the billing
    index when the user has one, else the plan the user record carries, else
    nothing is claimed. The old row fell back to an invented "free"."""
    return str(ub.get("plan") or u.get("plan") or "no plan on record")


def _sorted(users: list[dict], sort: str) -> list[dict]:
    if sort == "email":
        return sorted(users, key=lambda u: str(u.get("email") or "").lower())
    if sort == "last_login":
        # never-logged-in users last
        return sorted(users, key=lambda u: str(u.get("last_login") or ""), reverse=True)
    return users          # the gateway's own order: newest account first


def _build_orphan_rows(orphans: list[dict], q: str = "") -> list:
    """Subscriptions whose user account no longer exists.

    Owner ask 2026-08-13: "in users I do not see some of those where only ID was shown". Those rows are NOT hidden users — their user_id is absent
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


def _row(u: dict, ub: dict) -> ui.ListItem:
    """One user: who, which plan and role, when money next moves. A click
    opens the profile; nothing is edited from the list."""
    uid = _uid(u)
    is_active = u.get("is_active", True)
    parts = [_name(u), uid, _plan(u, ub), str(u.get("role") or "no role")]
    # meta = when money next moves. Silence beats a guess: with no billing
    # row the slot stays empty rather than implying "never".
    if ub:
        _, rel, _ = _when(ub.get("due_at"))
        if ub.get("mode") == "card" and not ub.get("has_card"):
            meta = f"{rel} · NO CARD"
        elif ub.get("mode") in ("manual", "free"):
            meta = f"{rel} · {ub.get('mode')}"
        else:
            meta = f"{rel} · {_money(ub.get('amount_cents'))}"
    else:
        meta = ""
    return ui.ListItem(
        id=uid,
        title=str(u.get("email") or "(no email)"),
        subtitle=" · ".join(p for p in parts if p),
        meta=meta,
        badge=ui.Badge("active" if is_active else "inactive",
                       color="green" if is_active else "red"),
        on_click=ui.Call("__panel__tools", section="user_profile", user_id=uid),
    )


async def build_users(ctx, role_filter: str = "", status_filter: str = "",
                      q: str = "", sort: str = "", **kwargs):
    """The user list: search, filters, pages. Three gateway reads per render.

    ``q`` searches every identifying field (id, email, all name variants,
    company, tax id, phone, city, country, role) with the haystack of the
    find_users tool, so the panel and the chat answer the same. The gateway's
    own ``search`` covers email and id only (read 2026-11-23), which is why
    the match is made here over the whole list and not asked of the gateway.
    """
    (users, error), roles, billing_index = await asyncio.gather(
        _fetch_users_checked(), _fetch_roles(),
        fetch_user_billing_index(_panel_acting(ctx)),
    )
    if error:
        return ui.Stack(children=[
            ui.Header("Users", level=3),
            ui.Alert(
                title="The user list could not be read",
                message=f"The gateway answered: {error}. Nothing is shown "
                        "because nothing is known - this is not an empty tenant.",
                type="error",
            ),
        ])

    billing_known = isinstance(billing_index, dict) and "users" in billing_index
    billing_map = (billing_index or {}).get("users") or {}
    orphans = (billing_index or {}).get("orphaned_subscriptions") or []

    q = str(q or "")
    needle = q.strip().lower()
    role_filter, status_filter, sort = str(role_filter or ""), str(status_filter or ""), str(sort or "")

    # counts over ALL users, before any filter
    active_n = sum(1 for u in users if u.get("is_active", True))
    by_role: dict[str, int] = {}
    for u in users:
        by_role[str(u.get("role") or "")] = by_role.get(str(u.get("role") or ""), 0) + 1

    role_labels = {r.get("name", ""): r.get("display_name") or r.get("name", "") for r in roles}
    # a role that users hold but the role list does not name is still offered
    for name in by_role:
        role_labels.setdefault(name, name or "(no role)")
    role_options = [{"value": name, "label": f"{label} ({by_role.get(name, 0)})"}
                    for name, label in role_labels.items() if name]

    filtered = users
    if needle:
        # local import: panels never import handlers at module scope.
        from handlers_user_search import _identity_haystack
        filtered = [u for u in filtered if needle in _identity_haystack(u)]
    if role_filter:
        filtered = [u for u in filtered if u.get("role") == role_filter]
    if status_filter == "active":
        filtered = [u for u in filtered if u.get("is_active", True)]
    elif status_filter == "inactive":
        filtered = [u for u in filtered if not u.get("is_active", True)]
    filtered = _sorted(filtered, sort)

    total = len(filtered)
    try:
        offset = max(0, int(kwargs.get("user_offset", 0)))
    except (TypeError, ValueError):
        offset = 0
    # clamp to the list, not to a multiple of PAGE: a page may render fewer
    # rows than PAGE (the byte net below), and Next advances by what was shown
    offset = min(offset, max(0, total - 1)) if total else 0
    page_slice = filtered[offset:offset + PAGE]

    def _go(**over) -> ui.Call:
        """A re-render of this list with the current search, filters and
        order, changed only by *over*."""
        state = {"section": "management", "q": q, "role_filter": role_filter,
                 "status_filter": status_filter, "sort": sort, "user_offset": 0}
        state.update(over)
        return ui.Call("__panel__tools", **state)

    # Search box — a Form because ui.Input has no on_change; submitting
    # re-renders this section with the query applied.
    search_bar = ui.Form(
        action="__panel__tools",
        submit_label="Search",
        defaults={"section": "management", "role_filter": role_filter,
                  "status_filter": status_filter, "sort": sort, "user_offset": 0},
        children=[
            ui.Input(
                placeholder="Search by email, ID, name, company, phone, city…",
                param_name="q", value=q,
            ),
        ],
    )

    filter_bar = ui.Stack([
        ui.Select(
            options=[{"value": "", "label": f"All roles ({len(users)})"}] + role_options,
            value=role_filter, param_name="role_filter",
            on_change=ui.Call("__panel__tools", section="management", q=q,
                              status_filter=status_filter, sort=sort, user_offset=0),
        ),
        ui.Select(
            options=[
                {"value": "", "label": f"Any status ({len(users)})"},
                {"value": "active", "label": f"Active ({active_n})"},
                {"value": "inactive", "label": f"Inactive ({len(users) - active_n})"},
            ],
            value=status_filter, param_name="status_filter",
            on_change=ui.Call("__panel__tools", section="management", q=q,
                              role_filter=role_filter, sort=sort, user_offset=0),
        ),
        ui.Select(
            options=SORTS, value=sort, param_name="sort",
            on_change=ui.Call("__panel__tools", section="management", q=q,
                              role_filter=role_filter, status_filter=status_filter,
                              user_offset=0),
        ),
    ], direction="h", gap=2)

    # Byte net: rows are light now, but one page must never reach the
    # kernel's 256 KB reply cap whatever a row holds. See render_cap.py.
    user_items, shown, _ = build_capped_list(
        page_slice, lambda u: _row(u, billing_map.get(_uid(u)) or {}))
    page_short = shown < len(page_slice)

    if total:
        count = f"{offset + 1}–{offset + shown} of {total}"
        count += " users" if total == len(users) else f" matching, {len(users)} users in all"
    else:
        count = f"Nobody matches, {len(users)} users in all" if users else "This tenant has no users yet"
    if needle:
        count += f" · search “{q.strip()}”"

    pager = []
    if offset > 0:
        pager.append(ui.Button(label="← Previous", variant="ghost",
                               on_click=_go(user_offset=max(0, offset - PAGE))))
    # advance by what THIS page showed, so a page the byte net cut short
    # never hides its remainder
    if offset + shown < total:
        pager.append(ui.Button(label="Next →", variant="ghost",
                               on_click=_go(user_offset=offset + shown)))

    children: list = [
        ui.Header("Users", level=3),
        search_bar,
        filter_bar,
        ui.Text(count, variant="caption"),
    ]
    if not billing_known:
        children.append(ui.Alert(
            message="Billing data could not be read: plans come from the user "
                    "records and no due dates are shown.",
            type="warning",
        ))
    if page_short:
        children.append(ui.Alert(
            title="This page came in heavier than usual",
            message=(f"{shown} of this page's {len(page_slice)} users are shown "
                     "below. Next reaches the rest."),
            type="warning",
        ))
    children += _build_orphan_rows(orphans, q)
    children.append(ui.Accordion(sections=[{
        "id": "create",
        "title": "Create a user",
        "children": [
            ui.Form(action="create_user", submit_label="Create user", children=[
                ui.Input(placeholder="Email address", param_name="email"),
                ui.Input(placeholder="Password", param_name="password"),
                ui.Select(
                    options=[{"value": n, "label": l} for n, l in role_labels.items() if n],
                    value="user", param_name="role", placeholder="Select role"),
            ]),
        ],
    }]))
    if user_items:
        children.append(ui.List(items=user_items))
    if pager:
        children.append(ui.Stack(children=pager, direction="h", gap=2))
    return ui.Stack(children=children)
