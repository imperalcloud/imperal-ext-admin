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


def _roles_page(monkeypatch, roles):
    async def _roles():
        return roles

    async def _users():
        return [{"imperal_id": "u1", "email": "a@b.c", "role": "user"}]

    async def _scopes():
        return ["mail:read"]
    monkeypatch.setattr(PR, "_fetch_roles", _roles)
    monkeypatch.setattr(PR, "_fetch_users", _users)
    monkeypatch.setattr(PR, "_fetch_scope_names", _scopes)
    return asyncio.run(PR.build_roles(None))


def test_guest_is_in_the_roles_list_as_a_built_in_role(monkeypatch):
    page = _roles_page(monkeypatch, [{"id": "1", "name": "user", "display_name": "User", "is_system": True,
                                      "default_scopes": []}])
    items = [n["props"] for n in _tree(page) if n.get("type") == "ListItem"]
    assert [i["id"] for i in items] == ["user", "guest"]
    guest = items[1]
    assert guest["title"] == "Guest" and guest["subtitle"] == "guest"
    text = " ".join(str(n["props"].get("content") or n["props"].get("text") or "")
                    for n in _tree(guest["expanded_content"]) if isinstance(n.get("props"), dict))
    assert "no account" in text and "Scope: guest" in text
    # read-only: nothing in it saves or deletes
    assert not [n for n in _tree(guest["expanded_content"]) if n.get("type") == "Form"]


def test_a_guest_row_of_the_table_is_not_doubled(monkeypatch):
    page = _roles_page(monkeypatch, [{"id": "9", "name": "guest", "display_name": "Guest", "is_system": True,
                                      "default_scopes": ["guest"]}])
    assert [n["props"]["id"] for n in _tree(page) if n.get("type") == "ListItem"] == ["guest"]
