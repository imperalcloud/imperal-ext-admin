"""Admin · Users & Extensions panels page through 100% of a large tenant.

Owner report #1 (2026-08-29): "uers and extensions pages в админском плагине
тупо не загружают юзеров и плагины. Их слишком много и страница грузит
10 минут и ничего не показывает все равно" -- a large tenant (thousands of
accounts, or a marketplace with hundreds of extensions) had no server-side
cap at all: build_users/build_extensions built one ui.ListItem PER ROW with
no limit, so a big enough result set meant minutes of work building +
serializing a payload that size, and the panel never finished rendering.
First fix: a fixed item-count cap (200 users / 150 extensions) + a banner.

Owner report #2, same day: the fixed item count was itself never safe. The
kernel's fast_rpc reply pipe has a HARD 256KB cap on any panel response --
over that, the WHOLE reply is replaced with a typed truncation error, not a
partial render. At this tenant's real size, 41 real users alone already
serialize past 256KB and 169 real extensions past 256KB -- both UNDER their
"safe" fixed caps of 200/150. Second fix: render_cap.build_capped_list, a
byte-aware stop condition instead of a guessed row count.

Owner report #3, same day: "я должен page selector использовать чтобы
видеть ВЕСЬ список, все 100% без исключения... за 1 раз на 1 страницу все
не выкидывать, а по страничке подгружать" -- capping (dropping) rows past
N, even byte-safely, still made the tail of a large tenant PERMANENTLY
UNREACHABLE. Third and final fix: real server-side pagination (offset
param + Prev/Next buttons that re-call __panel__tools with a new offset),
same pattern panels_email.py already used. Each page is capped to exactly
50 rows so a single response can never approach the kernel's byte limit,
and the byte-aware safety net from fix #2 still guards one page in case
some unusually heavy rows ever got close -- but nothing is ever dropped
from the walkable set: paging all the way through reaches every row.
"""
from __future__ import annotations

import asyncio
import json

import panels_users as PU
import panels_extensions as PE

# The kernel's actual hard reply cap (imperal_kernel/rpc/stream_consumer.py
# REPLY_PAYLOAD_MAX_BYTES). No single page response may ever approach this.
KERNEL_HARD_CAP_BYTES = 262144

PAGE = 50


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
            if n.get("type") == "ListItem" and n.get("props", {}).get("id")]


def _buttons(tree) -> list[dict]:
    return [n["props"] for n in _walk(tree) if n.get("type") == "Button"]


def _alerts(tree) -> list[dict]:
    return [n["props"] for n in _walk(tree) if n.get("type") == "Alert"]


def _many_users(n: int, *, heavy: bool = False) -> list[dict]:
    extra = {"bio": "x" * 400} if heavy else {}
    return [
        {"imperal_id": f"imp_u_{i:05d}", "email": f"user{i}@example.com",
         "role": "user", "is_active": True, "plan": "free", **extra}
        for i in range(n)
    ]


def _many_extensions(n: int, *, heavy: bool = False) -> list[dict]:
    desc = {"description": "x" * 400} if heavy else {}
    return [
        {"app_id": f"ext-{i:04d}", "display_name": f"Extension {i}",
         "status": "active", "stores": ["Registry"], "tools": [], **desc}
        for i in range(n)
    ]


def _mock_users(monkeypatch, users):
    monkeypatch.setattr(PU, "_fetch_users", _aret(users))
    monkeypatch.setattr(PU, "_fetch_roles",
                        _aret([{"name": "user", "display_name": "User"}]))
    monkeypatch.setattr(PU, "_fetch_scope_names", _aret([]))
    monkeypatch.setattr(PU, "_fetch_extensions", _aret([]))
    monkeypatch.setattr(PU, "_fetch_plans", _aret([{"name": "free"}]))
    monkeypatch.setattr(PU, "_fetch_user_extensions", _aret([]))
    monkeypatch.setattr(PU, "fetch_user_billing_index", _aret({}))


def _mock_extensions(monkeypatch, exts):
    monkeypatch.setattr(PE, "_fetch_extensions_shared", _aret(exts))
    monkeypatch.setattr(PE, "_fetch_extension_users", _aret([]))
    monkeypatch.setattr(PE, "_fetch_access_policy", _aret({"mode": "public"}))


# ── Users ─────────────────────────────────────────────────────────────


def test_build_users_first_page_is_at_most_50_with_a_next_button(monkeypatch):
    users = _many_users(5000)
    _mock_users(monkeypatch, users)

    tree = asyncio.run(PU.build_users(None, q="")).to_dict()

    n = len(_list_items(tree))
    assert 0 < n <= PAGE
    labels = [b.get("label", "") for b in _buttons(tree)]
    assert any("Next" in l for l in labels)
    assert not any("Previous" in l for l in labels)  # page 1: nothing before it


def test_build_users_paging_through_reaches_every_one_of_5000(monkeypatch):
    """The owner's core ask: page selector must reach 100%, nothing dropped."""
    users = _many_users(5000)
    _mock_users(monkeypatch, users)

    seen_ids: set[str] = set()
    offset = 0
    guard = 0
    while True:
        guard += 1
        assert guard <= 200, "pagination looped without terminating"
        tree = asyncio.run(PU.build_users(None, q="", user_offset=offset)).to_dict()
        page_items = _list_items(tree)
        seen_ids.update(i["id"] for i in page_items)
        labels = [b.get("label", "") for b in _buttons(tree)]
        if not any("Next" in l for l in labels):
            break
        # Advance by what THIS page actually rendered, exactly mirroring the
        # panel's own Next button (offset + rendered_in_page) -- not a fixed
        # PAGE, which would desync from the byte-safety net's real page size
        # and either skip rows or loop forever.
        offset += len(page_items)

    assert seen_ids == {u["imperal_id"] for u in users}


def test_build_users_heavy_rows_still_stay_under_the_kernel_cap(monkeypatch):
    """A single 50-row page must stay byte-safe even with unusually heavy rows."""
    users = _many_users(200, heavy=True)
    _mock_users(monkeypatch, users)

    tree = asyncio.run(PU.build_users(None, q="")).to_dict()

    assert len(json.dumps(tree, default=str)) < KERNEL_HARD_CAP_BYTES


def test_build_users_no_pager_under_one_page(monkeypatch):
    """A tenant smaller than one page renders exactly as before -- no pager."""
    users = _many_users(10)
    _mock_users(monkeypatch, users)

    tree = asyncio.run(PU.build_users(None, q="")).to_dict()

    assert len(_list_items(tree)) == 10
    assert _buttons(tree) == []


# ── Extensions ────────────────────────────────────────────────────────


def test_build_extensions_first_page_is_exactly_50_with_a_next_button(monkeypatch):
    exts = _many_extensions(500)
    _mock_extensions(monkeypatch, exts)

    tree = asyncio.run(PE.build_extensions(None)).to_dict()

    assert len(_list_items(tree)) == PAGE
    labels = [b.get("label", "") for b in _buttons(tree)]
    assert any("Next" in l for l in labels)
    assert not any("Previous" in l for l in labels)


def test_build_extensions_paging_through_reaches_every_one_of_500(monkeypatch):
    exts = _many_extensions(500)
    _mock_extensions(monkeypatch, exts)

    seen_ids: set[str] = set()
    offset = 0
    guard = 0
    while True:
        guard += 1
        assert guard <= 200, "pagination looped without terminating"
        tree = asyncio.run(PE.build_extensions(None, ext_offset=offset)).to_dict()
        page_items = _list_items(tree)
        seen_ids.update(i["id"] for i in page_items)
        labels = [b.get("label", "") for b in _buttons(tree)]
        if not any("Next" in l for l in labels):
            break
        # Advance by what THIS page actually rendered, exactly mirroring the
        # panel's own Next button (offset + rendered_in_page) -- not a fixed
        # PAGE, which would desync from the byte-safety net's real page size
        # and either skip rows or loop forever.
        offset += len(page_items)

    assert seen_ids == {e["app_id"] for e in exts}


def test_build_extensions_heavy_rows_still_stay_under_the_kernel_cap(monkeypatch):
    exts = _many_extensions(200, heavy=True)
    _mock_extensions(monkeypatch, exts)

    tree = asyncio.run(PE.build_extensions(None)).to_dict()

    assert len(json.dumps(tree, default=str)) < KERNEL_HARD_CAP_BYTES


def test_build_extensions_no_pager_under_one_page(monkeypatch):
    exts = _many_extensions(20)
    _mock_extensions(monkeypatch, exts)

    tree = asyncio.run(PE.build_extensions(None)).to_dict()

    assert len(_list_items(tree)) == 20
    assert _buttons(tree) == []
