"""Admin panel: Extensions tab.

Displays all platform extensions with expandable details, status badges,
access policy info, tools list, category/status filters, and action buttons.
"""
from __future__ import annotations

import asyncio
from typing import Any

from imperal_sdk import ui

from app import _gw_request, _registry_get, _tenant_id
from panels_sections import _cached, _fetch_extensions as _fetch_extensions_shared
from panels_sections import _fetch_users as _fetch_users_shared
from render_cap import build_capped_list


# ---------------------------------------------------------------------------
# Data fetchers
# ---------------------------------------------------------------------------

async def _fetch_extension_users_raw(app_id: str) -> list[dict]:
    try:
        result = await _gw_request("GET", f"/v1/extensions/{app_id}/users")
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return result.get("users", [])
    except Exception:
        pass
    return []


async def _fetch_extension_users(app_id: str) -> list[dict]:
    return await _cached(f"ext_users:{app_id}",
                         lambda: _fetch_extension_users_raw(app_id))


async def _fetch_access_policy_raw(app_id: str, tenant_id: str) -> dict:
    try:
        cfg = await _gw_request(
            "GET",
            f"/v1/internal/config/app/{app_id}?tenant_id={tenant_id}&app_id={app_id}",
        )
        return (cfg or {}).get("config", {}).get("access_policy", {"mode": "public"})
    except Exception:
        return {"mode": "public"}


async def _fetch_access_policy(app_id: str, tenant_id: str) -> dict:
    return await _cached(f"ext_policy:{tenant_id}:{app_id}",
                         lambda: _fetch_access_policy_raw(app_id, tenant_id))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _status_badge(app: dict) -> ui.Badge:
    status = str(app.get("status", "unknown"))
    color = ("green" if status == "active"
             else "red" if status == "suspended"
             else "orange" if status in ("draft", "pending_review")
             else "gray")
    return ui.Badge(label=status.replace("_", " ").title(), color=color)


def _build_tools_section(app: dict) -> list:
    tools = app.get("tools") or []
    if not tools:
        return []
    badges = [ui.Badge(label=t.get("name", "?"), color="gray") for t in tools[:5]]
    if len(tools) > 5:
        badges.append(ui.Text(f"+{len(tools) - 5} more", variant="caption"))
    return [
        ui.Text(f"Tools ({len(tools)})", variant="caption"),
        ui.Stack(badges, direction="h", gap=1, wrap=True),
    ]


def _build_policy_summary(app_id: str, policy: dict) -> list:
    mode = policy.get("mode", "public")
    exc = policy.get("exceptions", {})
    req = policy.get("required_scopes") or []
    dr, du = exc.get("denied_roles") or [], exc.get("denied_users") or []

    children: list = [ui.Badge(label=f"Mode: {mode.capitalize()}",
                               color="blue" if mode == "public" else "orange")]
    if req:
        sc_badges = [ui.Badge(s, color="blue") for s in req[:5]]
        if len(req) > 5:
            sc_badges.append(ui.Text(f"+{len(req) - 5}", variant="caption"))
        children.append(ui.Stack(sc_badges, direction="h", gap=1, wrap=True))
    if dr:
        children.append(ui.Stack([ui.Badge(f"deny: {r}", color="red") for r in dr],
                                 direction="h", gap=1, wrap=True))
    if du:
        children.append(ui.Text(f"{len(du)} denied user(s)", variant="caption"))
    children.append(ui.Button(
        label="Edit Policy", variant="ghost",
        on_click=ui.Call("__panel__tools", section="ext_access_policy", app_id=app_id),
    ))
    return children


def _build_expanded_content(app: dict, user_count: int | None, policy: dict,
                            author: str | None = None) -> list:
    app_id: str = app.get("app_id") or app.get("id", "")
    status: str = app.get("status", "unknown")
    description: str = app.get("description") or ""

    kv_items = [
        {"key": "Version", "value": str(app.get("version", "\u2014"))},
        {"key": "Category", "value": str(app.get("category") or "\u2014").capitalize()},
        {"key": "Status", "value": status.capitalize()},
        {"key": "Users", "value": str(user_count) if user_count is not None else "\u2014"},
        {"key": "Developer", "value": author or "\u2014 (system)"},
    ]

    is_active = status == "active"
    nodes: list = [ui.KeyValue(items=kv_items, columns=2)]
    if description:
        nodes.append(ui.Text(content=description, variant="caption"))

    req_scopes = app.get("required_scopes") or app.get("scopes") or []
    if req_scopes:
        nodes.append(ui.Text("Required scopes: " + ", ".join(req_scopes), variant="caption"))

    nodes.extend(_build_tools_section(app))
    nodes.append(ui.Section(title="Access Policy",
                            children=_build_policy_summary(app_id, policy)))

    nodes.append(ui.Stack(children=[
        ui.Button(
            label="Suspend" if is_active else "Restore",
            variant="danger" if is_active else "primary",
            on_click=ui.Call(
                "suspend_extension" if is_active else "activate_extension",
                app_id=app_id,
                **({"confirm": (f"Suspend '{app_id}'? It comes off the "
                                 "Marketplace and every current user loses "
                                 "access immediately. You can Restore it "
                                 "later.")} if is_active else {}),
            ),
        ),
        ui.Button(
            label="To draft", variant="ghost",
            on_click=ui.Call(
                "draft_extension", app_id=app_id,
                confirm=(f"Send '{app_id}' back to draft? It comes off the "
                         "Marketplace for rework; existing users keep using "
                         "it until you re-submit and it's approved again."),
            ),
        ),
        ui.Button(
            label="Settings", variant="primary",
            on_click=ui.Call("__panel__tools", section="ext_settings", app_id=app_id),
        ),
        ui.Button(
            label="Manage Users", variant="ghost",
            on_click=ui.Call("__panel__tools", section="ext_users", app_id=app_id),
        ),
        ui.Button(
            label="Purge", variant="danger",
            on_click=ui.Call("purge_app", app_id=app_id, confirm_name=app_id, force=True,
                             confirm=(f"Permanently purge '{app_id}' from the ENTIRE system "
                                      "(files, DB, Redis, Registry, marketplace). This CANNOT be undone.")),
        ),
    ], direction="h", gap=2))
    return nodes


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

async def build_extensions(ctx: Any, category_filter: str = "",
                           status_filter: str = "", **kwargs) -> ui.Stack:
    extensions, all_users = await asyncio.gather(
        _fetch_extensions_shared(), _fetch_users_shared())
    if not extensions:
        return ui.Stack(children=[
            ui.Header(text="Extensions", level=3),
            ui.Empty(message="No extensions registered", icon="Puzzle"),
        ], direction="v", gap=4)

    # Author lookup: developer_apps.developer_id -> the actual person, shown
    # right on the collapsed card (owner asked to see it without expanding).
    # Falls back to the raw id if the user record isn't found (e.g. the
    # developer account was since deleted) rather than hiding the field.
    _dev_by_id = {u.get("imperal_id", ""): u for u in all_users if u.get("imperal_id")}

    def _author_label(app: dict) -> str | None:
        did = app.get("developer_id")
        if not did:
            return None
        u = _dev_by_id.get(did)
        if not u:
            return did
        return u.get("email") or u.get("nickname") or did

    categories = sorted({e.get("category", "") for e in extensions if e.get("category")})
    cat_options = [{"value": "", "label": "All Categories"}] + [
        {"value": c, "label": c.capitalize()} for c in categories
    ]
    # Real status options built from whatever statuses actually occur in the
    # data (active/suspended/draft/pending_review/... or anything else the
    # gateway returns) -- not a hardcoded active/inactive guess. This is the
    # exact same status string _status_badge already renders, so the filter
    # always matches what the operator sees on each card.
    statuses = sorted({str(e.get("status", "unknown")) for e in extensions})
    status_options = [{"value": "", "label": "All Status"}] + [
        {"value": s, "label": s.replace("_", " ").title()} for s in statuses
    ]

    filtered = extensions
    if category_filter:
        filtered = [e for e in filtered if e.get("category") == category_filter]
    if status_filter:
        filtered = [e for e in filtered if str(e.get("status", "unknown")) == status_filter]

    filter_bar = ui.Stack([
        ui.Select(options=cat_options, value=category_filter, param_name="category_filter",
                  on_change=ui.Call("__panel__tools", section="extensions",
                                   status_filter=status_filter, ext_offset=0)),
        ui.Select(options=status_options, value=status_filter, param_name="status_filter",
                  on_change=ui.Call("__panel__tools", section="extensions",
                                   category_filter=category_filter, ext_offset=0)),
    ], direction="h", gap=2)

    # Real server-side pagination (2026-08-29): the owner wants to page
    # through EVERY extension, 100% of them, not have the rest silently
    # dropped after a fixed cap. total_filtered is the TRUE count across
    # the whole filtered set, computed BEFORE slicing, so paging all the
    # way through always reaches every last one. Each page is its own
    # server round-trip (Prev/Next below re-call __panel__tools with a new
    # offset) -- this replaces the earlier fixed 150-row fan-out cutoff,
    # which simply hid anything past row 150 with no way to reach it.
    _PAGE = 50
    total_filtered = len(filtered)
    try:
        offset = max(0, int(kwargs.get("ext_offset", 0)))
    except (TypeError, ValueError):
        offset = 0
    # Clamp to the real list bounds only -- NOT rounded down to a multiple
    # of _PAGE (see panels_users.py for why: a page can render fewer than
    # _PAGE rows under the byte-safety net, so rounding to a PAGE-multiple
    # made the last few extensions unreachable no matter how far you paged).
    offset = min(offset, max(0, total_filtered - 1)) if total_filtered else 0
    page_slice = filtered[offset:offset + _PAGE]

    _app_ids = [app.get("app_id") or app.get("id", "") for app in page_slice]
    fetch_users = len(page_slice) < 15

    _tid = _tenant_id(ctx)
    if fetch_users:
        _user_results, _policy_results = await asyncio.gather(
            asyncio.gather(*[_fetch_extension_users(aid) for aid in _app_ids]),
            asyncio.gather(*[_fetch_access_policy(aid, _tid) for aid in _app_ids]),
        )
        user_counts = {aid: len(ul) for aid, ul in zip(_app_ids, _user_results)}
    else:
        _policy_results = await asyncio.gather(
            *[_fetch_access_policy(aid, _tid) for aid in _app_ids])
        user_counts: dict[str, int] = {}

    policies = dict(zip(_app_ids, _policy_results))

    def _build_one(app: dict) -> ui.ListItem:
        app_id = app.get("app_id") or app.get("id", "")
        display_name = app.get("display_name") or app.get("name") or app_id
        uc = user_counts.get(app_id)
        parts: list[str] = []
        stores = app.get("stores") or []
        if stores:
            parts.append("+".join(stores))
        if uc is not None:
            parts.append(f"{uc} users")
        # Tools count from app registration (may be 0 — actual tools in Settings > Tools)
        tc = len(app.get("tools") or [])
        if tc > 0:
            parts.append(f"{tc} tools")
        cat = app.get("category")
        if cat:
            parts.append(cat.capitalize())

        # Author, right on the collapsed card (owner: "видеть автора приложения
        # сразу"). System apps (no developer_id, e.g. admin/billing) simply omit it.
        author = _author_label(app)
        subtitle = f"{app_id} · by {author}" if author else app_id

        return ui.ListItem(
            id=app_id, title=display_name, subtitle=subtitle,
            badge=_status_badge(app),
            meta=" \u00b7 ".join(parts) if parts else None,
            expandable=True,
            expanded_content=_build_expanded_content(
                app=app, user_count=uc,
                policy=policies.get(app_id, {"mode": "public"}),
                author=author),
        )

    # Byte-aware safety net (2026-08-29): a single 50-row PAGE should never
    # get near the kernel's hard 256KB reply cap, but if some unusually
    # heavy rows ever did, stop adding them rather than tripping the cap —
    # same measuring approach as before, just applied to one page instead
    # of the whole filtered set now that paging (not a cutoff) is how the
    # operator reaches every one of the total_filtered extensions. See
    # render_cap.py.
    list_items, rendered_in_page, _ = build_capped_list(page_slice, _build_one)

    range_start = offset + 1 if total_filtered else 0
    range_end = offset + rendered_in_page
    count = (f"{range_start}\u2013{range_end} of {total_filtered}"
             if category_filter or status_filter else f"{range_start}\u2013{range_end} of {len(extensions)}")

    def _pager():
        btns = []
        if offset > 0:
            btns.append(ui.Button(label="\u2190 Previous 50", variant="ghost",
                        on_click=ui.Call("__panel__tools", section="extensions",
                                         category_filter=category_filter, status_filter=status_filter,
                                         ext_offset=max(0, offset - _PAGE))))
        if offset + rendered_in_page < total_filtered:
            btns.append(ui.Button(label="Next 50 \u2192", variant="ghost",
                        on_click=ui.Call("__panel__tools", section="extensions",
                                         category_filter=category_filter, status_filter=status_filter,
                                         ext_offset=offset + rendered_in_page)))
        return ui.Stack(children=btns, direction="h", gap=2) if btns else None

    return ui.Stack(children=[
        ui.Header(text="Extensions", level=3, subtitle=f"{count} registered"),
        filter_bar,
        ui.List(items=list_items, searchable=True),
        *([_pager()] if _pager() else []),
    ], direction="v", gap=4)
