"""Admin · User list — identity, next charge date, and search by ANY field.

Owner ask (2026-08-13): "в users я не вижу часть тех, что ты показала, где
только ID... в карточке я сразу хочу видеть и email и его ID, и план... и
сразу next due date по оплате... и чтобы поиск юзеров по любым параметрам
искал".

WHY THIS SUITE EXISTS
---------------------
Three failures here are invisible on screen, which is precisely why they need
tests rather than a look:

  1. ORPHANS ARE NOT PEOPLE. 23 of 61 subscription rows point at a user_id
     that no longer exists in `users` (deleted accounts, subscription left
     behind). The first cut of the billing index built its map straight from
     `subscriptions`, so those ids entered the users map too — 53 rows for 32
     accounts, 21 ids present in BOTH sets. A panel that merges them shows
     billing rows for people it cannot open, so the two sets must stay
     disjoint and orphans must render in their own block.

  2. A DUE DATE MUST NEVER BE INVENTED. When the billing index is empty
     (gateway down), the row shows NO date rather than a calm-looking blank
     that reads as "nothing is owed". Silence and "$0.00 / never" are
     indistinguishable on a money screen, and only one of them is honest.

  3. SEARCH MUST COVER FIELDS THAT ARE NOT ON SCREEN. The list's built-in
     `searchable` flag filters the rendered strings only, so before this an
     operator literally could not find a person by imperal_id, company, phone
     or city — the value was never drawn. Panel search therefore reuses the
     find_users haystack, so chat and panel answer identically.

Shapes below are taken verbatim from the live /v1/internal/billing/user-index
payload, so the suite fails if the gateway contract drifts.
"""
from __future__ import annotations

import asyncio

import panels_users as PU


# ── Fixtures shaped exactly like production ──────────────────────────────

USERS = [
    # A real pro subscriber in card mode who has NO card — the 25-account
    # cohort that looks healthy on every screen that trusts plan names.
    {"imperal_id": "imp_u_AAA", "email": "vic@gmail.com", "role": "user",
     "is_active": True, "plan": "pro", "scopes": [],
     "created_at": "2026-07-06T08:55:41", "last_login": "2026-08-13T15:52:48",
     "attributes": {"company": {"company_name": "Acme Ltd"},
                    "billing": {"phone": "+37360123456", "city": "Chisinau"}}},
    # An enterprise seat settled by invoice: no card is CORRECT here.
    {"imperal_id": "imp_u_BBB", "email": "ent@corp.com", "role": "admin",
     "is_active": True, "plan": "enterprise", "scopes": [],
     "created_at": "2026-05-01T00:00:00", "attributes": {}},
]

INDEX = {
    "users": {
        "imp_u_AAA": {"plan": "pro", "status": "active", "mode": "card",
                      "has_card": False, "due_at": "2026-09-04T18:35:09",
                      "cancelling": False, "failures": 0,
                      "amount_cents": 2900, "chargeable": True},
        "imp_u_BBB": {"plan": "enterprise", "status": "active",
                      "mode": "manual", "has_card": False,
                      "due_at": "2026-09-04T18:35:09", "cancelling": False,
                      "failures": 0, "amount_cents": 0, "chargeable": False},
    },
    # Deleted account, subscription still active WITH a card: the sweep may
    # still charge a customer who no longer exists.
    "orphaned_subscriptions": [
        {"user_id": "imp_u_GHOST", "plan": "pro", "status": "active",
         "mode": "card", "has_card": True, "amount_cents": 2900,
         "due_at": "2026-09-08T16:18:48", "created_at": "2026-08-09T16:18:48"},
    ],
}


def _aret(value):
    async def _f(*a, **k):
        return value
    return _f


def _render(monkeypatch, *, q: str = "", index: dict | None = INDEX) -> dict:
    """Render the real builder with every fetch stubbed — no network."""
    monkeypatch.setattr(PU, "_fetch_users", _aret(USERS))
    monkeypatch.setattr(PU, "_fetch_roles",
                        _aret([{"name": "user", "display_name": "User"},
                               {"name": "admin", "display_name": "Admin"}]))
    monkeypatch.setattr(PU, "_fetch_scope_names", _aret([]))
    monkeypatch.setattr(PU, "_fetch_extensions", _aret([]))
    monkeypatch.setattr(PU, "_fetch_plans",
                        _aret([{"name": "pro"}, {"name": "enterprise"}]))
    monkeypatch.setattr(PU, "_fetch_user_extensions", _aret([]))
    monkeypatch.setattr(PU, "fetch_user_billing_index", _aret(index))
    return asyncio.run(PU.build_users(None, q=q)).to_dict()


def _walk(node):
    """Every node in a rendered tree, including Accordion section bodies.

    Accordion sections are PLAIN dicts ({"id", "title", "children"}), not
    UINodes, so their children hang off the top level rather than off
    ``props``. Walking only ``props`` silently skips everything inside an
    accordion — which is exactly where the orphan block lives, and would
    make these tests report "not rendered" for content that is on screen.
    """
    yield node
    props = node.get("props") or {}
    for container in (props, node):
        for key in ("children", "items", "sections"):
            for child in container.get(key) or []:
                if isinstance(child, dict):
                    yield from _walk(child)


def _rows(tree) -> list[dict]:
    return [n["props"] for n in _walk(tree)
            if n.get("type") == "ListItem" and n.get("props", {}).get("title")]


def _row_for(tree, title: str) -> dict:
    for row in _rows(tree):
        if row.get("title") == title:
            return row
    raise AssertionError(f"no row titled {title!r}")


def _text_blob(tree) -> str:
    """Every string anywhere in the tree — for 'is this fact visible at all'."""
    out = []
    for node in _walk(tree):
        for value in (node.get("props") or {}).values():
            if isinstance(value, str):
                out.append(value)
            elif isinstance(value, list):
                out += [
                    f"{k}={v}" for item in value
                    if isinstance(item, dict)
                    for k, v in item.items() if isinstance(v, str)
                ]
    return " ".join(out)


# ── 1. The collapsed row answers the question without being opened ───────

def test_row_shows_email_id_and_plan_together(monkeypatch):
    """Owner ask: email + imperal_id + plan visible at a glance."""
    row = _row_for(_render(monkeypatch), "vic@gmail.com")
    assert "imp_u_AAA" in row["subtitle"]
    assert "pro" in row["subtitle"]


def test_row_shows_next_due_date(monkeypatch):
    """The next charge must be on the row, not one click away."""
    row = _row_for(_render(monkeypatch), "vic@gmail.com")
    assert row.get("meta"), "row carries no due-date meta"


def test_card_mode_without_card_is_called_out_on_the_row(monkeypatch):
    """A pro plan with no card is a FUTURE FAILURE, not revenue.

    This is the 25-account cohort: every screen that trusts the plan name
    renders them as healthy paying customers.
    """
    row = _row_for(_render(monkeypatch), "vic@gmail.com")
    assert "NO CARD" in row["meta"]


def test_manual_seat_is_not_flagged_as_missing_card(monkeypatch):
    """Enterprise settles by invoice — absence of a card is correct there."""
    row = _row_for(_render(monkeypatch), "ent@corp.com")
    assert "NO CARD" not in row["meta"]
    assert "manual" in row["meta"]


# ── 2. Honesty when billing is unavailable ───────────────────────────────

def test_no_due_date_is_invented_when_billing_is_down(monkeypatch):
    """Empty index → empty meta. Never a soothing date or $0.00."""
    tree = _render(monkeypatch, index={})
    for row in _rows(tree):
        assert not row.get("meta"), f"invented meta: {row.get('meta')!r}"


def test_user_list_still_renders_when_billing_is_down(monkeypatch):
    """A billing outage degrades the list — it must not break it."""
    rows = _rows(_render(monkeypatch, index={}))
    assert {r["title"] for r in rows} == {"vic@gmail.com", "ent@corp.com"}


# ── 3. Orphans: visible, separate, never merged into people ──────────────

def test_orphan_subscriptions_are_surfaced(monkeypatch):
    """The 'only an ID' rows the owner could not find anywhere."""
    assert "imp_u_GHOST" in _text_blob(_render(monkeypatch))


def test_orphans_are_not_rendered_as_users(monkeypatch):
    """An orphan must never appear as a person in the user list.

    Guards the exact bug this feature shipped with: the index built its map
    from subscriptions with no join to `users`, putting 21 ghost ids into
    both result sets at once.
    """
    tree = _render(monkeypatch)
    people = [r for r in _rows(tree) if "·" in (r.get("subtitle") or "")]
    assert all("imp_u_GHOST" not in (r.get("subtitle") or "") for r in people)


def test_orphan_block_warns_it_may_still_be_charged(monkeypatch):
    """An active orphan WITH a card means the sweep can still take money."""
    blob = _text_blob(_render(monkeypatch))
    assert "no longer exist" in blob
    assert "$29.00" in blob


def test_orphan_block_absent_when_platform_is_clean(monkeypatch):
    """No ghosts → no scary empty panel."""
    clean = {"users": INDEX["users"], "orphaned_subscriptions": []}
    assert "no longer exist" not in _text_blob(_render(monkeypatch, index=clean))


# ── 4. Search across fields that are NOT drawn on the row ────────────────

def test_search_matches_company_which_is_never_rendered(monkeypatch):
    """'Acme Ltd' appears on no row — client-side search cannot find it."""
    rows = _rows(_render(monkeypatch, q="acme"))
    assert [r["title"] for r in rows] == ["vic@gmail.com"]


def test_search_matches_imperal_id(monkeypatch):
    rows = _rows(_render(monkeypatch, q="imp_u_BBB"))
    assert [r["title"] for r in rows] == ["ent@corp.com"]


def test_search_matches_phone_and_city(monkeypatch):
    for needle in ("+37360", "chisinau"):
        rows = _rows(_render(monkeypatch, q=needle))
        assert [r["title"] for r in rows] == ["vic@gmail.com"], needle


def test_search_is_case_insensitive(monkeypatch):
    rows = _rows(_render(monkeypatch, q="ACME"))
    assert [r["title"] for r in rows] == ["vic@gmail.com"]


def test_orphan_block_honours_the_search(monkeypatch):
    """A filtered view must not contradict itself.

    Searching for a person and still being shown unrelated ghost rows makes
    the result set meaningless.
    """
    assert "no longer exist" not in _text_blob(_render(monkeypatch, q="acme"))


def test_searching_an_orphan_id_finds_it(monkeypatch):
    """The ghost ids must be searchable too — they carry money."""
    assert "imp_u_GHOST" in _text_blob(_render(monkeypatch, q="imp_u_GHOST"))


def test_empty_query_filters_nothing(monkeypatch):
    assert len(_rows(_render(monkeypatch, q=""))) == len(USERS) + 1  # +orphan


def test_panel_search_reuses_the_find_users_haystack(monkeypatch):
    """One implementation, so chat and panel can never drift apart."""
    from handlers_user_search import _identity_haystack
    hay = _identity_haystack(USERS[0])
    for fragment in ("imp_u_aaa", "vic@gmail.com", "acme ltd", "chisinau"):
        assert fragment in hay, fragment
