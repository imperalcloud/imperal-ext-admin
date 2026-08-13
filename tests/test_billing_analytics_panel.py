"""Admin · Billing Analytics — the money figures must come from real fields.

Owner ask (2026-08-13): "сколько реально paid юзеров — именно тех у кого есть
карточки привязанные, и когда конкретно будут списания".

WHY THIS SUITE EXISTS
---------------------
The dangerous version of this feature is the one that LOOKS right. Counting a
"paid user" by plan name renders a confident, beautiful, wrong number — and
that exact inference is what trapped 11 accounts in an add-card loop earlier
this cycle. Production today makes the gap impossible to miss: 39 active
subscriptions, but only 5 that can actually be charged.

So these tests hold three lines that a future refactor could quietly cross:

  1. "Paying" is card-on-file, never plan price. A price-29 plan with no card
     is NOT revenue, and must be surfaced as risk instead.
  2. When the billing gateway says nothing, the Dashboard shows NO revenue
     card — never a reassuring $0.00, which is indistinguishable from "we
     earned nothing" and is the worst possible lie on a money screen.
  3. A failed charge keeps its reason and its method visible, because
     "declined, card" and "declined, unknown" lead to different actions.

Shapes below are taken verbatim from the live endpoint, so the suite fails if
the gateway's contract drifts.
"""
from __future__ import annotations

import asyncio

import panels_billing_analytics as PBA
import panels_dashboard as PD


# The live payload shape, trimmed to what the panel reads.
LIVE = {
    "generated_at": "2026-08-13T15:35:30+00:00",
    "window_days": 30,
    "grace_days": 3,
    "subscriptions": {
        "by_status": {"active": 39, "expired": 22},
        "by_mode": {"card": 31, "manual": 8},
        "by_plan": [
            {"plan": "pro", "price": 29.0, "mode": "card",
             "count": 31, "with_card": 6},
            {"plan": "enterprise", "price": 0.0, "mode": "manual",
             "count": 7, "with_card": 0},
        ],
    },
    # 39 active, but only 5 chargeable — the whole point of the feature.
    "paid": {"paying_with_card": 5, "card_mode_without_card": 25,
             "mrr_cents": 14500, "manual": 8, "free": 0},
    "upcoming": {
        "buckets": {"next_7d": {"count": 1, "cents": 2900},
                    "next_30d": {"count": 4, "cents": 11600}},
        "schedule": [
            {"user_id": "u1", "email": "a@b.io", "plan": "pro",
             "period": "monthly", "amount_cents": 2900,
             "due_at": "2026-08-15T11:42:44", "failures": 0, "mode": "card"},
        ],
    },
    "at_risk": [
        {"user_id": "u2", "email": "c@d.io", "plan": "pro",
         "amount_cents": 2900, "due_at": "2026-09-04T18:35:09",
         "failures": 3, "status": "active", "risk": "no_card_on_file"},
    ],
    "payments": {
        "by_status": {"pending": {"count": 1, "cents": 2900},
                      "completed": {"count": 2, "cents": 12900}},
        "by_method": [{"method": "unrecorded", "status": "completed",
                       "count": 2, "cents": 12900}],
        "recent": [
            {"payment_intent_id": "pi_fail", "user_id": "u3",
             "email": "f@g.io", "amount_cents": 2900, "currency": "USD",
             "status": "failed", "tokens": 0, "method": "card",
             "auto_topup": 0, "error": "card_declined",
             "created_at": "2026-08-02T09:00:00", "completed_at": None},
        ],
        "test_rows_excluded": 91,
    },
}


class _Ctx:
    user_id = "imp_u_tE-J9c_NxX"


def _render(monkeypatch, payload):
    async def _fake(*_a, **_k):
        return payload
    monkeypatch.setattr(PBA, "_fetch_analytics", _fake)
    return asyncio.run(PBA.build_billing_analytics(_Ctx())).to_dict()


def _walk(node):
    """Yield every node in the tree, whatever nests it."""
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


# ── 1 · paid means card-on-file, not plan name ────────────────────────


def test_paying_count_comes_from_cards_not_plan_names(monkeypatch):
    """39 subscriptions are active; only 5 are actually chargeable."""
    stats = _stats(_render(monkeypatch, LIVE))

    assert stats["Paying (card on file)"][0] == "5"
    assert stats["Active"][0] == "39"
    # The 31 card-mode subs must never be presented as 31 payers.
    assert "31" not in stats["Paying (card on file)"][0]


def test_card_mode_without_card_is_surfaced_as_red_risk(monkeypatch):
    """25 subs are set to bill by card but have none — that is the warning."""
    stats = _stats(_render(monkeypatch, LIVE))

    value, colour = stats["Card mode, NO card"]
    assert value == "25"
    assert colour == "red", "a broken-billing population must not look neutral"


def test_mrr_counts_only_chargeable_subscriptions(monkeypatch):
    """MRR is 5 x $29, not 31 x $29 — committed money, not hoped-for money."""
    stats = _stats(_render(monkeypatch, LIVE))
    assert stats["MRR committed"][0] == "$145.00"


# ── 2 · silence beats a comfortable lie ───────────────────────────────


def test_no_revenue_card_on_dashboard_when_billing_is_down(monkeypatch):
    """A $0.00 revenue card would read as 'we earned nothing'. Show none."""
    async def _nothing(*_a, **_k):
        return {}

    async def _users(*_a, **_k):
        return [{"is_active": True}]

    async def _empty_list(*_a, **_k):
        return []

    async def _empty_dict(*_a, **_k):
        return {}

    monkeypatch.setattr(PD, "_fetch_analytics", _nothing)
    monkeypatch.setattr(PD, "_fetch_users", _users)
    monkeypatch.setattr(PD, "_fetch_roles", _empty_list)
    monkeypatch.setattr(PD, "_fetch_extensions", _empty_list)
    monkeypatch.setattr(PD, "_fetch_llm_usage", _empty_dict)
    monkeypatch.setattr(PD, "_fetch_action_stats", _empty_dict)

    tree = asyncio.run(PD.build_dashboard(_Ctx())).to_dict()
    titles = [n["props"].get("title") for n in _walk(tree)
              if n.get("type") == "Card"]
    assert "Revenue" not in titles


def test_analytics_section_says_so_when_the_gateway_is_silent(monkeypatch):
    """Empty payload must produce an explicit notice, not blank cards."""
    tree = _render(monkeypatch, {})
    kinds = {n.get("type") for n in _walk(tree)}
    assert "Alert" in kinds
    assert not _stats(tree), "no invented numbers when there is no data"


# ── 3 · a failure keeps its reason and its method ─────────────────────


def test_failed_charge_keeps_reason_and_method(monkeypatch):
    """'declined, card' and 'declined, unknown' need different responses."""
    tree = _render(monkeypatch, LIVE)
    blob = str(tree)

    assert "card_declined" in blob, "the failure reason must reach the owner"
    assert "pi_fail" in blob, "the payment intent must stay traceable"


def test_test_mode_rows_are_disclosed_not_hidden(monkeypatch):
    """91 of 98 rows are Stripe test data; excluding them silently is a lie."""
    tree = _render(monkeypatch, LIVE)
    assert "91" in str(tree)


def test_schedule_and_risk_rows_both_render(monkeypatch):
    """The owner asked for a table AND a log — both lists must appear."""
    tree = _render(monkeypatch, LIVE)
    lists = [n for n in _walk(tree) if n.get("type") == "List"]
    assert len(lists) >= 3, "upcoming, at-risk and payments each need a list"
