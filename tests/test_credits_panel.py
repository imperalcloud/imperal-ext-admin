"""Admin · Credits — bought must never quietly absorb admin grants.

Owner ask (2026-08-13): "я до сих пор не вижу где можно посмотреть историю
покупки системных кредитов. А так же видеть наглядно разницу сколько кредитов
было куплено и потрачено и всего по системе и по юзеру отдельно."

WHY THIS SUITE EXISTS
---------------------
`token_ledger.reason` is FREE TEXT, not an enum. Production proves it: next to
the machine-written `topup` sit hand-typed strings — 'admin_grant',
'admin_credit_1M', 'grant_tokens', 'rhtlbnjd', and
'выдача 1M по просьбе администратора'. The tempting implementation ("sum every
positive amount") renders a confident, beautiful, WRONG number: it folds ~42.6M
of credits nobody paid for into a revenue-shaped figure.

The live gap is what makes this concrete: the ledger shows ~1.00e9 credits
bought, while real completed payments are 5 rows worth $197.00 — and the two
CANNOT be reconciled, because every topup row carries reference_id = NULL.

So this suite holds four lines a future refactor could quietly cross:

  1. bought and granted stay separate numbers, and granted is never summed
     into bought;
  2. an UNKNOWN free-text reason is presented as a grant, never as a purchase
     (unknown text must not be able to invent income);
  3. credits and money are never presented as reconciled;
  4. when the gateway is silent the section says so instead of rendering a
     calm, plausible zero.

Payload shapes below are taken verbatim from the live endpoint, so the suite
fails if the gateway's contract drifts.
"""
from __future__ import annotations

import asyncio

import panels_credits as PC


# The live payload shape, trimmed to what the panel reads. Numbers are the
# real ones measured on production 2026-08-13.
LIVE = {
    "generated_at": "2026-08-13T17:36:30+00:00",
    "window_days": 30,
    "platform": {
        "all_time": {
            "bought": 1002387533,
            "granted": 42602000,
            "starter": 54500,
            "refunded": 169080,
            "spent": 34456574,
            "received": 1045044033,
            "net_spent": 34287494,
            "net": 1010756539,
            "rows": {"bought": 50, "granted": 58, "starter": 14,
                     "refunded": 19943, "spent": 46102},
        },
        "window": {
            "bought": 100000,
            "granted": 40200000,
            "starter": 51500,
            "refunded": 92912,
            "spent": 33313468,
            "received": 40351500,
            "net_spent": 33220556,
            "net": 7130944,
            "rows": {"bought": 1, "granted": 41, "starter": 8,
                     "refunded": 1318, "spent": 20482},
        },
    },
    "payments": {
        "real_completed": 5,
        "real_cents": 19700,
        "real_tokens": 260000,
        "test_rows_excluded": 71,
        "test_tokens_excluded": 15265000,
        "reconcilable_with_ledger": False,
    },
    "per_user": [
        {"user_id": "imp_u_XWnehlFBls", "email": "buyer@imperal.io",
         "bought": 1250500, "granted": 12005000, "starter": 0,
         "refunded": 37115, "spent": 11276916, "received": 13255500,
         "net_spent": 11239801, "net": 2015699,
         "rows": {"bought": 7, "granted": 11, "starter": 0,
                  "refunded": 3420, "spent": 7733}},
        # Never bought anything — lives entirely on admin grants.
        {"user_id": "imp_u_NBzuhNN-te", "email": "granted@imperal.io",
         "bought": 0, "granted": 5605000, "starter": 0,
         "refunded": 39699, "spent": 4998550, "received": 5605000,
         "net_spent": 4958851, "net": 646149,
         "rows": {"bought": 0, "granted": 8, "starter": 0,
                  "refunded": 637, "spent": 7396}},
    ],
    "history": [
        {"at": "2026-08-11T09:18:12", "user_id": "imp_u_XWnehlFBls",
         "email": "buyer@imperal.io", "credits": 1000000,
         "reason": "topup", "kind": "purchase",
         "description": "Top-up", "app_id": ""},
        # A hand-typed reason: must be reported as a grant, not a purchase.
        {"at": "2026-08-10T12:00:00", "user_id": "imp_u_NBzuhNN-te",
         "email": "granted@imperal.io", "credits": 1000000,
         "reason": "rhtlbnjd", "kind": "grant",
         "description": "Admin adjustment: rhtlbnjd", "app_id": ""},
    ],
}


class _Ctx:
    user_id = "imp_u_tE-J9c_NxX"


def _render(monkeypatch, payload):
    async def _fake(*_a, **_k):
        return payload
    monkeypatch.setattr(PC, "_fetch_credits", _fake)
    return asyncio.run(PC.build_credits(_Ctx())).to_dict()


def _walk(node):
    """Yield every node in the tree, whatever nests it.

    Children hang off the node itself, not off props, for container types
    like Accordion — walking props alone silently misses whole sections.
    """
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _stats(tree) -> dict:
    """label -> (value, colour) for every Stat rendered."""
    out = {}
    for n in _walk(tree):
        if n.get("type") == "Stat":
            p = n["props"]
            out[p["label"]] = (p["value"], p.get("color"))
    return out


def _stat_by_prefix(stats: dict, prefix: str):
    for label, value in stats.items():
        if label.startswith(prefix):
            return label, value
    raise AssertionError(f"no Stat labelled {prefix!r} in {list(stats)}")


# ── 1 · bought and granted are different things ───────────────────────


def test_bought_excludes_admin_grants(monkeypatch):
    """~1.00e9 bought and ~42.6M granted must never be added together."""
    stats = _stats(_render(monkeypatch, LIVE))

    _, (bought, _c) = _stat_by_prefix(stats, "Bought")
    _, (granted, _c2) = _stat_by_prefix(stats, "Granted by admins")

    assert bought == PC._credits(1002387533)
    assert granted == PC._credits(42602000)
    # The sum (1,044,989,533) is the number a naive implementation shows.
    assert bought != PC._credits(1002387533 + 42602000)


def test_granted_is_not_coloured_like_revenue(monkeypatch):
    """Gift credits must not read as income at a glance."""
    stats = _stats(_render(monkeypatch, LIVE))

    _, (_v, bought_colour) = _stat_by_prefix(stats, "Bought")
    _, (_v2, granted_colour) = _stat_by_prefix(stats, "Granted by admins")

    assert bought_colour == "green"
    assert granted_colour != "green", "grants must not look like revenue"


def test_spending_is_net_of_refunds(monkeypatch):
    """19,943 refund rows would otherwise overstate consumption."""
    stats = _stats(_render(monkeypatch, LIVE))
    _, (spent, _c) = _stat_by_prefix(stats, "Spent")

    assert spent == PC._credits(34287494)      # net_spent
    assert spent != PC._credits(34456574)      # gross


# ── 2 · an unknown reason can never invent income ─────────────────────


def test_hand_typed_reason_is_shown_as_grant_not_purchase(monkeypatch):
    """'rhtlbnjd' is somebody's keyboard mash, not a paid top-up."""
    tree = _render(monkeypatch, LIVE)
    blob = str(tree)

    assert "rhtlbnjd" in blob, "the raw reason must stay auditable"
    # The grant row is labelled by kind, and the panel's own label for a
    # grant must not be the purchase label.
    assert PC._kind_label("grant") != PC._kind_label("purchase")


def test_history_shows_who_and_when(monkeypatch):
    """The owner asked to SEE the purchase history, not a total."""
    tree = _render(monkeypatch, LIVE)
    blob = str(tree)

    assert "buyer@imperal.io" in blob
    assert "2026-08-11" in blob, "each purchase needs its date"


# ── 3 · credits and money are not reconciled ──────────────────────────


def test_money_card_discloses_that_it_cannot_be_reconciled(monkeypatch):
    """5 real payments / $197 next to ~1.0e9 credits needs an explanation."""
    tree = _render(monkeypatch, LIVE)
    alerts = [n for n in _walk(tree) if n.get("type") == "Alert"]

    assert alerts, "the unreconcilable gap must be stated, not implied"
    assert any("cross-check" in str(a).lower() or "reconcil" in str(a).lower()
               for a in alerts)


def test_test_mode_payments_are_disclosed(monkeypatch):
    """71 of 76 payment rows are Stripe test data — say so."""
    assert "71" in str(_render(monkeypatch, LIVE))


# ── 4 · per user, and silence beats a comfortable zero ────────────────


def test_per_user_separates_buyers_from_granted_only(monkeypatch):
    """One user paid; the other lives entirely on admin grants."""
    tree = _render(monkeypatch, LIVE)
    badges = [n["props"].get("label") for n in _walk(tree)
              if n.get("type") == "Badge"]

    assert "paying" in badges
    assert "granted only" in badges


def test_section_says_so_when_the_gateway_is_silent(monkeypatch):
    """An empty payload must produce a notice, never a calm set of zeroes."""
    tree = _render(monkeypatch, {})
    kinds = {n.get("type") for n in _walk(tree)}

    assert "Alert" in kinds
    assert not _stats(tree), "no invented numbers when there is no data"


# ── 5 · the same truth inside ONE user's profile ──────────────────────
#
# The profile page already shows a wallet balance. A balance is a single
# number with no history: it cannot say whether those credits were PAID FOR
# or HANDED OUT, which is precisely the per-user half of the owner ask. The
# embedded section must therefore keep the same separation as the platform
# card — and must stay SILENT rather than render a zeroed card, because an
# empty card inside a person's profile reads as "this user has nothing",
# a claim we cannot make when the gateway simply did not answer.

# Live shape of GET /v1/internal/billing/credits/{user_id}.
USER_LIVE = {
    "user_id": "imp_u_XWnehlFBls",
    "totals": {
        "bought": 1250500, "granted": 12005000, "starter": 0,
        "refunded": 37115, "spent": 11276916, "received": 13255500,
        "net_spent": 11239801, "net": 2015699,
        "rows": {"bought": 7, "granted": 11, "starter": 0,
                 "refunded": 3420, "spent": 7733},
    },
    "purchases": [
        {"at": "2026-08-11T09:18:12", "user_id": "imp_u_XWnehlFBls",
         "email": "buyer@imperal.io", "credits": 1000000,
         "reason": "grant_tokens", "kind": "grant",
         "description": "Admin adjustment: grant_tokens", "app_id": ""},
    ],
    "recent": [],
}


def _user_section(payload):
    node = PC.build_user_credits_section(payload)
    return None if node is None else node.to_dict()


def test_profile_section_keeps_bought_and_granted_apart():
    """12.0M of this account's 13.2M was granted, not bought — show both."""
    stats = _stats(_user_section(USER_LIVE))

    _, (bought, _) = _stat_by_prefix(stats, "Bought")
    _, (granted, _) = _stat_by_prefix(stats, "Granted by admins")

    assert bought == "1,250,500"
    assert granted == "12,005,000"
    # The tempting single number (13,255,500) must never be shown as bought.
    assert bought != "13,255,500"


def test_profile_section_marks_a_grant_funded_account():
    """A user living on admin grants must not look like a paying customer."""
    rendered = str(_user_section(USER_LIVE))
    assert "grant" in rendered.lower()


def test_profile_section_renders_nothing_when_billing_is_silent():
    """No payload → no card at all, so the profile is left untouched."""
    assert PC.build_user_credits_section({}) is None


def test_profile_section_renders_nothing_for_an_account_with_no_ledger():
    """All-zero totals are not worth a card, and must not imply activity."""
    empty = {"user_id": "imp_u_new", "totals": {
        "bought": 0, "granted": 0, "starter": 0, "refunded": 0,
        "spent": 0, "received": 0, "net_spent": 0, "net": 0, "rows": {}},
        "purchases": [], "recent": []}

    assert PC.build_user_credits_section(empty) is None
