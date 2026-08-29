"""Admin · Users & Extensions panels must not try to render EVERYTHING.

Owner report (2026-08-29): "uers and extensions pages в админском плагине
тупо не загружают юзеров и плагины. Их слишком много и страница грузит
10 минут и ничего не показывает все равно" -- a large tenant (thousands of
accounts, or a marketplace with hundreds of extensions) had no server-side
cap at all: build_users/build_extensions built one ui.ListItem PER ROW with
no limit, so a big enough result set meant minutes of work building +
serializing a payload that size, and the panel never finished rendering.

The gateway's own /v1/users is already paginated fine (see users/router.py);
the bug was entirely in what THIS panel turned into UI nodes per response.
Fix: a hard render cap + an explicit ui.Alert telling the operator to narrow
the search/filter instead of silently truncating or hanging.
"""
from __future__ import annotations

import asyncio

import panels_users as PU
import panels_extensions as PE


def _aret(value):
    async def _f(*a, **k):
        return value
    return _f


def _walk(node):
    yield node
    props = node.get("props") or {}
    for container in (props, node):
        for key in ("children", "items", "sections"):
            for child in container.get(key) or []:
                if isinstance(child, dict):
                    yield from _walk(child)


def _list_items(tree) -> list[dict]:
    return [n["props"] for n in _walk(tree)
            if n.get("type") == "ListItem" and n.get("props", {}).get("title")]


def _alerts(tree) -> list[dict]:
    return [n["props"] for n in _walk(tree) if n.get("type") == "Alert"]


def _many_users(n: int) -> list[dict]:
    return [
        {"imperal_id": f"imp_u_{i:06d}", "email": f"user{i}@example.com",
         "role": "user", "is_active": True, "plan": "free", "scopes": [],
         "created_at": "2026-01-01T00:00:00", "attributes": {}}
        for i in range(n)
    ]


def _many_extensions(n: int) -> list[dict]:
    return [
        {"app_id": f"ext-{i:04d}", "display_name": f"Extension {i}",
         "status": "active", "stores": ["Registry"], "tools": []}
        for i in range(n)
    ]


def test_build_users_caps_render_for_a_large_tenant(monkeypatch):
    """5000 users must render as a capped page + a visible warning, fast."""
    users = _many_users(5000)
    monkeypatch.setattr(PU, "_fetch_users", _aret(users))
    monkeypatch.setattr(PU, "_fetch_roles",
                        _aret([{"name": "user", "display_name": "User"}]))
    monkeypatch.setattr(PU, "_fetch_scope_names", _aret([]))
    monkeypatch.setattr(PU, "_fetch_extensions", _aret([]))
    monkeypatch.setattr(PU, "_fetch_plans", _aret([{"name": "free"}]))
    monkeypatch.setattr(PU, "_fetch_user_extensions", _aret([]))
    monkeypatch.setattr(PU, "fetch_user_billing_index", _aret({}))

    tree = asyncio.run(PU.build_users(None, q="")).to_dict()

    items = _list_items(tree)
    # Rendered rows must be capped, never one-per-account for a huge tenant.
    assert len(items) <= 200
    assert len(items) < len(users)

    # An explicit, honest warning must tell the operator the list was cut,
    # not a silent truncation that reads as "that's everyone".
    alerts = _alerts(tree)
    assert any("5000" in (a.get("message") or "") for a in alerts)


def test_build_users_no_cap_banner_under_the_limit(monkeypatch):
    """A normal-sized tenant must render exactly as before -- no banner."""
    users = _many_users(10)
    monkeypatch.setattr(PU, "_fetch_users", _aret(users))
    monkeypatch.setattr(PU, "_fetch_roles",
                        _aret([{"name": "user", "display_name": "User"}]))
    monkeypatch.setattr(PU, "_fetch_scope_names", _aret([]))
    monkeypatch.setattr(PU, "_fetch_extensions", _aret([]))
    monkeypatch.setattr(PU, "_fetch_plans", _aret([{"name": "free"}]))
    monkeypatch.setattr(PU, "_fetch_user_extensions", _aret([]))
    monkeypatch.setattr(PU, "fetch_user_billing_index", _aret({}))

    tree = asyncio.run(PU.build_users(None, q="")).to_dict()

    assert len(_list_items(tree)) == 10
    assert _alerts(tree) == []


def test_build_extensions_caps_render_for_a_large_marketplace(monkeypatch):
    """500 extensions must render as a capped page + a visible warning."""
    exts = _many_extensions(500)
    monkeypatch.setattr(PE, "_fetch_extensions_shared", _aret(exts))
    monkeypatch.setattr(PE, "_fetch_extension_users", _aret([]))
    monkeypatch.setattr(PE, "_fetch_access_policy",
                        _aret({"mode": "public"}))

    tree = asyncio.run(PE.build_extensions(None)).to_dict()

    items = _list_items(tree)
    assert len(items) <= 150
    assert len(items) < len(exts)

    alerts = _alerts(tree)
    assert any("500" in (a.get("message") or "") for a in alerts)


def test_build_extensions_no_cap_banner_under_the_limit(monkeypatch):
    """A normal-sized marketplace must render exactly as before -- no banner."""
    exts = _many_extensions(20)
    monkeypatch.setattr(PE, "_fetch_extensions_shared", _aret(exts))
    monkeypatch.setattr(PE, "_fetch_extension_users", _aret([]))
    monkeypatch.setattr(PE, "_fetch_access_policy",
                        _aret({"mode": "public"}))

    tree = asyncio.run(PE.build_extensions(None)).to_dict()

    assert len(_list_items(tree)) == 20
    assert _alerts(tree) == []
