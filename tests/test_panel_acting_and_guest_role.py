"""Two things the owner saw in the live panel on 2026-11-23.

1. Dashboard: "Actions this month: the viewing admin's id is not known to this
   panel". The kernel hands a panel ``ctx.user`` as an object with
   ``imperal_id``; the shared helper read ``ctx.user`` only when it was a dict.
2. Roles: no guest. The guest role is the platform's own and no row of the
   roles table, and the page listed rows only.
"""
from __future__ import annotations

import asyncio
import types

import panels_roles as PR
from app import _acting, _panel_acting


def _tree(x):
    x = x.to_dict() if hasattr(x, "to_dict") else x
    if isinstance(x, dict):
        yield x
        for v in x.values():
            yield from _tree(v)
    elif isinstance(x, (list, tuple)):
        for v in x:
            yield from _tree(v)


def test_the_viewing_admin_is_read_from_the_user_object_the_kernel_gives():
    ctx = types.SimpleNamespace(user=types.SimpleNamespace(imperal_id="imp_u_admin", role="admin"))
    assert _panel_acting(ctx) == "imp_u_admin" == _acting(ctx)


def test_the_older_shapes_still_answer():
    assert _panel_acting(types.SimpleNamespace(user={"imperal_id": "imp_u_d"})) == "imp_u_d"
    assert _panel_acting(types.SimpleNamespace(user=None, user_id="imp_u_flat")) == "imp_u_flat"
    assert _panel_acting(types.SimpleNamespace(user=None)) == ""
    assert _panel_acting(object()) == ""


POLICY = {
    "role": "guest", "scopes": ["guest"], "refresh_seconds": 30,
    "fields": [
        {"key": "chat_per_day", "label": "Messages a guest may send in a day", "unit": "messages",
         "min": 1, "max": 100000, "value": 20, "stored": True, "enforced_by": "gateway"},
        {"key": "pool_daily_cap", "label": "Credits all guests together may spend in a day", "unit": "credits",
         "min": 0, "max": 100000000, "value": 500, "stored": True, "enforced_by": "kernel"},
    ],
    "values": {"chat_per_day": 20, "pool_daily_cap": 500},
}


def _roles_page(monkeypatch, roles, policy=POLICY, why=""):
    async def _roles():
        return roles

    async def _users():
        return [{"imperal_id": "u1", "email": "a@b.c", "role": "user"}]

    async def _scopes():
        return ["mail:read"]

    async def _guest(ctx):
        return ({}, why) if why else (policy, "")
    monkeypatch.setattr(PR, "_fetch_roles", _roles)
    monkeypatch.setattr(PR, "_fetch_users", _users)
    monkeypatch.setattr(PR, "_fetch_scope_names", _scopes)
    monkeypatch.setattr(PR, "_fetch_guest_policy", _guest)
    return asyncio.run(PR.build_roles(None))


USER_ROLE = [{"id": "1", "name": "user", "display_name": "User", "is_system": True, "default_scopes": []}]


def _guest(page):
    items = [n["props"] for n in _tree(page) if n.get("type") == "ListItem"]
    assert [i["id"] for i in items] == ["user", "guest"]
    return items[1]


def test_guest_is_a_role_of_the_list_with_its_settings_as_a_form(monkeypatch):
    """Owner 2026-11-23: the guest role in full, its settings matter for the guest chat on the site."""
    guest = _guest(_roles_page(monkeypatch, USER_ROLE))
    assert guest["title"] == "Guest" and guest["subtitle"] == "guest" and "2 settings" in guest["meta"]
    form = next(n["props"] for n in _tree(guest["expanded_content"]) if n.get("type") == "Form")
    assert form["action"] == "save_guest_policy"
    assert form["defaults"] == {"chat_per_day": "20", "pool_daily_cap": "500"}
    inputs = {n["props"]["param_name"]: n["props"]["value"] for n in _tree(form) if n.get("type") == "Input"}
    assert inputs == {"chat_per_day": "20", "pool_daily_cap": "500"}
    text = " ".join(str(n["props"].get("content") or n["props"].get("text") or "")
                    for n in _tree(guest["expanded_content"]) if isinstance(n.get("props"), dict))
    assert "Messages a guest may send in a day (messages, 1 - 100000; held by the gateway)" in text
    assert "held by the kernel" in text and "Scopes: guest" in text


def test_the_form_holds_no_setting_of_its_own(monkeypatch):
    """The list of settings, their labels, bounds and values are the gateway's answer: another answer,
    another form, with no change of this extension."""
    other = {"role": "guest", "scopes": ["guest", "demo"], "fields": [
        {"key": "new_setting", "label": "A setting added later", "unit": "things", "min": 1, "max": 9, "value": 4,
         "stored": False, "enforced_by": "gateway"}]}
    guest = _guest(_roles_page(monkeypatch, USER_ROLE, policy=other))
    inputs = [n["props"]["param_name"] for n in _tree(guest["expanded_content"]) if n.get("type") == "Input"]
    assert inputs == ["new_setting"]
    import inspect
    src = inspect.getsource(PR._guest_item) + inspect.getsource(PR._fetch_guest_policy)
    for number in ("86400", "2000", "500", "300"):
        assert number not in src, number


def test_settings_that_could_not_be_read_are_said_so_not_drawn_as_blank(monkeypatch):
    guest = _guest(_roles_page(monkeypatch, USER_ROLE, why="HTTP 503: gateway away"))
    assert guest["meta"] == "settings unavailable"
    assert not [n for n in _tree(guest["expanded_content"]) if n.get("type") == "Form"]
    alerts = [n["props"] for n in _tree(guest["expanded_content"]) if n.get("type") == "Alert"]
    assert alerts and "HTTP 503" in alerts[0]["message"]


def test_a_guest_row_of_the_table_is_not_doubled(monkeypatch):
    page = _roles_page(monkeypatch, [{"id": "9", "name": "guest", "display_name": "Guest", "is_system": True,
                                      "default_scopes": ["guest"]}])
    assert [n["props"]["id"] for n in _tree(page) if n.get("type") == "ListItem"] == ["guest"]


# ── saving ────────────────────────────────────────────────────────────────

def _save(monkeypatch, answer, **fields):
    import handlers_roles as HR
    calls = []

    async def _gw(method, path, data=None, acting=None, ctx=None):
        calls.append((method, path, data, acting))
        return answer
    monkeypatch.setattr(HR, "_gw_request", _gw)
    ctx = types.SimpleNamespace(user=types.SimpleNamespace(imperal_id="imp_u_admin", role="admin"))
    return asyncio.run(HR.fn_save_guest_policy(ctx, HR.SaveGuestPolicyParams(**fields))), calls


def test_a_save_sends_the_filled_fields_as_the_acting_admin(monkeypatch):
    result, calls = _save(monkeypatch, {"values": {"chat_per_day": 40}}, chat_per_day=" 40 ", pool_daily_cap="")
    assert calls == [("PUT", "/v1/internal/guest/policy", {"values": {"chat_per_day": "40"}}, "imp_u_admin")]
    assert result.status == "success"


def test_the_gateways_refusal_is_the_answer(monkeypatch):
    result, _ = _save(monkeypatch, {"error": "chat_per_min: 0 is outside 1..600"}, chat_per_min="0")
    assert result.status == "error" and "outside 1..600" in str(result.error)


def test_a_blank_form_saves_nothing(monkeypatch):
    result, calls = _save(monkeypatch, {})
    assert result.status == "error" and calls == []


def test_the_action_knows_every_setting_the_gateway_has():
    import handlers_roles as HR
    assert set(HR.GUEST_POLICY_KEYS) == set(HR.SaveGuestPolicyParams.model_fields)
