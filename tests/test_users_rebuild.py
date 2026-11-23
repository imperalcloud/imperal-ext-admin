"""Admin · Users rebuilt (2026-11-23): the list finds, the profile changes.

Owner report: "the users section is a mess: must be convenient, must not lag,
must show everything right". What the old screen did, each pinned here:

  * up to 57 gateway calls per render (one per row for that user's extensions);
  * a full edit card built for every row of the page;
  * the card's scope editor showed 10 scopes and saved the field whole, so an
    edit of a user with more than 10 scopes deleted the rest;
  * a gateway failure read as "No users found";
  * after a write the list showed the old picture for up to 10 seconds.
"""
from __future__ import annotations

import asyncio
import json

import app as admin_app
import panels_sections as PS
import panels_user_profile as PP
import panels_users as PU


def _aret(value):
    async def _f(*a, **k):
        return value
    return _f


def _nodes(x):
    """Every dict anywhere in a rendered tree."""
    if isinstance(x, dict):
        yield x
        for v in x.values():
            yield from _nodes(v)
    elif isinstance(x, (list, tuple)):
        for v in x:
            yield from _nodes(v)


def _typed(tree, kind):
    return [n.get("props") or {} for n in _nodes(tree) if n.get("type") == kind]


def _text(tree) -> str:
    return json.dumps(tree, default=str, ensure_ascii=False)


USERS = [
    {"imperal_id": "imp_u_A", "email": "a@x.io", "role": "user", "is_active": True,
     "plan": "starter", "attributes": {"full_name": "Ann Lee"}},
    {"imperal_id": "imp_u_B", "email": "b@x.io", "role": "admin", "is_active": False,
     "attributes": {}},
    {"imperal_id": "imp_u_C", "email": "c@x.io", "role": "user", "is_active": True,
     "attributes": {}},
]
ROLES = [{"name": "user", "display_name": "User"}, {"name": "admin", "display_name": "Admin"}]
INDEX = {"users": {"imp_u_A": {"plan": "pro", "status": "active", "mode": "card",
                               "has_card": True, "due_at": "2026-12-04T18:35:09",
                               "amount_cents": 2900}},
         "orphaned_subscriptions": []}


def _list(monkeypatch, users=USERS, error="", index=INDEX, **kw) -> dict:
    monkeypatch.setattr(PU, "_fetch_users_checked", _aret((users, error)))
    monkeypatch.setattr(PU, "_fetch_roles", _aret(ROLES))
    monkeypatch.setattr(PU, "fetch_user_billing_index", _aret(index))
    return asyncio.run(PU.build_users(None, **kw)).to_dict()


# ── the list ──────────────────────────────────────────────────────────────

def test_the_list_reads_three_things_and_nothing_per_row():
    """No per-user fetcher is even imported: the N+1 cannot come back unnoticed."""
    for gone in ("_fetch_user_extensions", "_fetch_extensions", "_fetch_scope_names", "_fetch_plans"):
        assert not hasattr(PU, gone), gone


def test_a_row_is_light_and_a_click_opens_the_profile(monkeypatch):
    rows = _typed(_list(monkeypatch), "ListItem")
    assert [r["title"] for r in rows] == ["a@x.io", "b@x.io", "c@x.io"]
    for r in rows:
        assert "expanded_content" not in r and "expandable" not in r
        assert "user_profile" in _text(r["on_click"]) and r["id"] in _text(r["on_click"])
    # 5000 users: one page stays small (the old page was about 6.5 KB per row)
    big = [{"imperal_id": f"imp_u_{i:05d}", "email": f"u{i}@x.io", "role": "user",
            "is_active": True} for i in range(5000)]
    assert len(_text(_list(monkeypatch, users=big, index={}))) < 40_000


def test_nothing_in_the_list_changes_a_user(monkeypatch):
    text = _text(_list(monkeypatch))
    for tool in ("update_user", "set_user_plan", "deactivate_user", "hard_delete_user",
                 "set_user_coding_access"):
        assert tool not in text, tool


def test_a_gateway_failure_is_shown_as_a_failure(monkeypatch):
    tree = _list(monkeypatch, users=[], error="HTTP 503: db down")
    alerts = _typed(tree, "Alert")
    assert alerts and alerts[0]["variant"] == "error" and "HTTP 503: db down" in alerts[0]["message"]
    assert "No users" not in _text(tree) and not _typed(tree, "ListItem")


def test_the_plan_has_one_rule_and_is_never_invented(monkeypatch):
    rows = {r["title"]: r for r in _typed(_list(monkeypatch), "ListItem")}
    assert "pro" in rows["a@x.io"]["subtitle"]            # the subscription wins over the record
    assert "starter" not in rows["a@x.io"]["subtitle"]
    assert "free" not in rows["c@x.io"]["subtitle"]       # nothing on record: nothing claimed
    assert "Ann Lee" in rows["a@x.io"]["subtitle"]


def test_billing_that_cannot_be_read_is_said(monkeypatch):
    tree = _list(monkeypatch, index={})
    assert any("Billing data could not be read" in a.get("message", "") for a in _typed(tree, "Alert"))
    rows = {r["title"]: r for r in _typed(tree, "ListItem")}
    assert "starter" in rows["a@x.io"]["subtitle"] and not rows["a@x.io"].get("meta")


def test_counts_are_over_all_users_not_the_page(monkeypatch):
    text = _text(_list(monkeypatch, status_filter="inactive"))
    assert "User (2)" in text and "Admin (1)" in text
    assert "Active (2)" in text and "Inactive (1)" in text
    assert "1 matching, 3 users in all" in text


def test_sort_and_filters_survive_paging(monkeypatch):
    big = [{"imperal_id": f"imp_u_{i:03d}", "email": f"u{i:03d}@x.io", "role": "user",
            "is_active": True} for i in range(120)]
    tree = _list(monkeypatch, users=big, index={}, sort="email", q="x.io", role_filter="user")
    nxt = [b for b in _typed(tree, "Button") if "Next" in b.get("label", "")]
    assert nxt, "no Next button"
    call = _text(nxt[0]["on_click"])
    for kept in ('"sort": "email"', '"q": "x.io"', '"role_filter": "user"', '"user_offset": 50'):
        assert kept in call, kept


# ── reading the users, and the cache ──────────────────────────────────────

def test_fetch_users_checked_tells_an_outage_from_an_empty_tenant(monkeypatch):
    PS._cache.clear()
    monkeypatch.setattr(PS, "_gw_users_all", _aret({"error": "HTTP 502: bad gateway"}))
    assert asyncio.run(PS._fetch_users_checked()) == ([], "HTTP 502: bad gateway")
    monkeypatch.setattr(PS, "_gw_users_all", _aret([]))
    assert asyncio.run(PS._fetch_users_checked()) == ([], "")
    PS._cache.clear()


def test_every_write_through_the_gateway_door_drops_the_panel_cache(monkeypatch):
    monkeypatch.setattr(admin_app, "_gw_request_raw", _aret({"ok": True}))
    PS._cache["users"] = (10**12, ["stale"])
    asyncio.run(admin_app._gw_request("GET", "/v1/users"))
    assert "users" in PS._cache                       # a read keeps it
    asyncio.run(admin_app._gw_request("PATCH", "/v1/users/imp_u_A", {"role": "admin"}))
    assert PS._cache == {}                            # a write drops it

    monkeypatch.setattr(admin_app, "_gw_request_raw", _aret({"error": "HTTP 500: no"}))
    PS._cache["users"] = (10**12, ["kept"])
    asyncio.run(admin_app._gw_request("PATCH", "/v1/users/imp_u_A", {"role": "admin"}))
    assert "users" in PS._cache                       # a refused write changed nothing
    PS._cache.clear()


# ── the profile ───────────────────────────────────────────────────────────

SCOPES = [f"ext:app{i}:read" for i in range(14)]


def _profile(monkeypatch, user=None, confirmation={"confirmation_enabled": True}, plans=None) -> dict:
    PS._cache.clear()
    user = user if user is not None else {
        "imperal_id": "imp_u_A", "email": "a@x.io", "role": "user", "is_active": True,
        "scopes": SCOPES, "attributes": {"coding_access": "deny"}, "plan": "pro"}
    monkeypatch.setattr(PP, "_gw_request", _aret(user))
    for name, value in (
        ("_fetch_roles", ROLES), ("_fetch_scope_names", SCOPES), ("_fetch_extensions", []),
        ("_fetch_user_extensions", []), ("_fetch_effective_scopes", []),
        ("_fetch_user_billing", ({}, {})), ("_fetch_developer_profile", {}),
        ("_fetch_billing_mode", {}), ("_fetch_credits", {}),
        ("_fetch_plans", [{"name": "pro"}, {"name": "starter"}] if plans is None else plans),
        ("_fetch_confirmation", confirmation),
    ):
        monkeypatch.setattr(PP, name, _aret(value))
    tree = asyncio.run(PP.build_user_profile(None, user_id="imp_u_A")).to_dict()
    PS._cache.clear()
    return tree


def test_the_profile_edits_every_scope_not_the_first_ten(monkeypatch):
    """The data loss: 14 scopes shown as 10, saved as 10."""
    tags = _typed(_profile(monkeypatch), "TagInput")
    assert tags and tags[0]["values"] == SCOPES


def test_everything_the_list_used_to_change_is_in_the_profile(monkeypatch):
    forms = {f.get("action"): f for f in _typed(_profile(monkeypatch), "Form")}
    for tool in ("update_user", "set_user_plan", "set_user_coding_access",
                 "set_user_connections_access", "set_user_file_reader_access",
                 "set_user_confirmation", "update_user_limits"):
        assert tool in forms, tool
    assert '"deny"' in _text(forms["set_user_coding_access"])     # the stored value is shown
    assert '"pro"' in _text(forms["set_user_plan"])


def test_an_inactive_user_can_be_activated_from_the_profile(monkeypatch):
    tree = _profile(monkeypatch, user={"imperal_id": "imp_u_A", "email": "a@x.io", "role": "user",
                                       "is_active": False, "scopes": [], "attributes": {}})
    labels = [b.get("label") or b.get("text") or "" for b in _typed(tree, "Button")]
    assert "Activate User" in _text(tree) and "Deactivate User" not in _text(tree), labels


def test_confirmation_that_cannot_be_read_offers_no_switch(monkeypatch):
    tree = _profile(monkeypatch, confirmation=None)
    assert "set_user_confirmation" not in _text(tree)
    assert "could not be read" in _text(tree)


def test_the_profile_says_why_a_user_could_not_be_read(monkeypatch):
    tree = _profile(monkeypatch, user={"error": "HTTP 503: db down"})
    assert "HTTP 503: db down" in _text(tree) and "not found" not in _text(tree)
    assert "Back to Users" in _text(tree)
