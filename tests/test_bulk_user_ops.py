"""Functional tests for admin bulk user operations.

Admin work is plural by nature. These tests pin the three properties that
make a bulk tool trustworthy rather than merely present:

  * it acts on EVERY named target (not just the first),
  * one bad identifier does NOT cancel the rest, and the caller is told
    exactly which targets failed,
  * duplicates collapse on the RESOLVED imperal_id, so naming one person
    twice (by email and by id) never double-charges or double-acts.

The last one matters most for bulk_adjust_balance: acting twice there means
crediting real money twice.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import handlers_bulk as hb  # noqa: E402
from app import ActionResult  # noqa: E402

from conftest import GatewaySpy  # noqa: E402


ALICE = "imp_u_AAAAAAAAAA"
BOB = "imp_u_BBBBBBBBBB"
CAROL = "imp_u_CCCCCCCCCC"

_DIRECTORY = {
    "alice@example.com": ALICE,
    "Alice": ALICE,
    ALICE: ALICE,
    "bob@example.com": BOB,
    BOB: BOB,
    "carol@example.com": CAROL,
    CAROL: CAROL,
}


def _fake_resolver(monkeypatch, directory=None, ambiguous=()):
    """Patch the flexible user resolver ON THE HANDLER MODULE.

    Per the repo's conftest note: the handler imported the name, so patching
    `app` would leave the real resolver running and hit the live gateway.
    """
    table = _DIRECTORY if directory is None else directory

    async def _resolve(value):
        if value in ambiguous:
            return None, f"'{value}' matches several users"
        hit = table.get(value)
        if hit:
            return hit, None
        return None, f"No user matches '{value}'"

    monkeypatch.setattr(hb, "_resolve_user_flexible", _resolve)


def _patch_gw(monkeypatch, spy):
    monkeypatch.setattr(hb, "_gw_request", spy)


class _AdjustSpy:
    """Records each single-user balance adjustment the bulk handler delegates to.

    bulk_adjust_balance deliberately reuses fn_adjust_balance so wallet keying
    and ledger writes live in ONE place; the spy therefore sits on that seam.
    """

    def __init__(self, failing: set[str] | None = None):
        self.failing = failing or set()
        self.calls: list[tuple[str, int]] = []

    async def __call__(self, ctx, params):
        self.calls.append((params.user_id, params.amount))
        if params.user_id in self.failing:
            return ActionResult.error("wallet locked")
        return ActionResult.success(data={"balance": 1}, summary="ok")

    @property
    def users(self) -> list[str]:
        return [u for u, _ in self.calls]


def _patch_adjust(monkeypatch, spy):
    import handlers_billing
    monkeypatch.setattr(handlers_billing, "fn_adjust_balance", spy)


# ─── deactivate / activate ────────────────────────────────────────────── #

@pytest.mark.asyncio
async def test_bulk_deactivate_acts_on_every_named_user(ctx, monkeypatch):
    _fake_resolver(monkeypatch)
    spy = GatewaySpy(default={"ok": True})
    _patch_gw(monkeypatch, spy)

    res = await hb.fn_bulk_set_user_active(
        ctx,
        hb.BulkSetActiveParams(
            user_ids=["alice@example.com", BOB, "carol@example.com"],
            is_active=False,
        ),
    )

    assert res.data["success_count"] == 3, res.summary
    # every target must have been hit individually
    for uid in (ALICE, BOB, CAROL):
        assert spy.hit(f"/v1/users/{uid}"), f"{uid} never touched — {spy.summary}"


@pytest.mark.asyncio
async def test_bulk_reactivate_uses_a_different_call_than_deactivate(ctx, monkeypatch):
    """Reactivating must not silently reuse the DELETE (deactivate) path."""
    _fake_resolver(monkeypatch)
    spy = GatewaySpy(default={"ok": True})
    _patch_gw(monkeypatch, spy)

    await hb.fn_bulk_set_user_active(
        ctx, hb.BulkSetActiveParams(user_ids=[ALICE], is_active=True),
    )

    assert not spy.calls_to("/v1/users/", method="DELETE"), (
        "reactivate must never issue the deactivate call — " + spy.summary
    )


# ─── partial success ──────────────────────────────────────────────────── #

@pytest.mark.asyncio
async def test_one_unknown_identifier_does_not_cancel_the_rest(ctx, monkeypatch):
    _fake_resolver(monkeypatch)
    spy = GatewaySpy(default={"ok": True})
    _patch_gw(monkeypatch, spy)

    res = await hb.fn_bulk_set_user_active(
        ctx,
        hb.BulkSetActiveParams(
            user_ids=["alice@example.com", "ghost@nowhere.io", BOB],
            is_active=False,
        ),
    )

    assert res.data["success_count"] == 2
    assert res.data["failure_count"] == 1
    assert any("ghost@nowhere.io" in f for f in res.data["failed"])
    # the good targets still went through
    assert spy.hit(f"/v1/users/{ALICE}") and spy.hit(f"/v1/users/{BOB}")


@pytest.mark.asyncio
async def test_partial_success_is_reported_as_success_not_error(ctx, monkeypatch):
    """A half-done bulk must not surface as a bare error that hides the work."""
    _fake_resolver(monkeypatch)
    _patch_gw(monkeypatch, GatewaySpy(default={"ok": True}))

    res = await hb.fn_bulk_set_user_active(
        ctx,
        hb.BulkSetActiveParams(user_ids=[ALICE, "ghost@nowhere.io"], is_active=False),
    )

    assert res.status == "success", "partial success must remain a success result"
    assert "ghost@nowhere.io" in res.summary or res.data["failure_count"] == 1


@pytest.mark.asyncio
async def test_an_ambiguous_name_is_reported_not_guessed(ctx, monkeypatch):
    _fake_resolver(monkeypatch, ambiguous={"Al"})
    _patch_gw(monkeypatch, GatewaySpy(default={"ok": True}))

    res = await hb.fn_bulk_set_user_active(
        ctx, hb.BulkSetActiveParams(user_ids=["Al", BOB], is_active=False),
    )

    assert res.data["failure_count"] == 1
    assert any("Al" in f for f in res.data["failed"])


# ─── de-duplication (money safety) ────────────────────────────────────── #

@pytest.mark.asyncio
async def test_naming_one_person_twice_credits_them_once(ctx, monkeypatch):
    """Email + id for the SAME human must not double-credit a wallet."""
    _fake_resolver(monkeypatch)
    adjust = _AdjustSpy()
    _patch_adjust(monkeypatch, adjust)

    res = await hb.fn_bulk_adjust_balance(
        ctx,
        hb.BulkAdjustBalanceParams(
            user_ids=["alice@example.com", ALICE, "Alice"],
            amount=5000,
            reason="incident goodwill",
        ),
    )

    assert res.data["success_count"] == 1, (
        "the same user named three ways must be credited ONCE"
    )
    assert adjust.users == [ALICE], (
        "crediting the same wallet more than once is real money lost: "
        f"{adjust.users}"
    )


@pytest.mark.asyncio
async def test_bulk_credit_hits_every_distinct_wallet(ctx, monkeypatch):
    _fake_resolver(monkeypatch)
    adjust = _AdjustSpy()
    _patch_adjust(monkeypatch, adjust)

    res = await hb.fn_bulk_adjust_balance(
        ctx,
        hb.BulkAdjustBalanceParams(
            user_ids=[ALICE, BOB, CAROL], amount=1000, reason="promo",
        ),
    )

    assert res.data["success_count"] == 3
    assert adjust.users == [ALICE, BOB, CAROL]
    assert {amt for _, amt in adjust.calls} == {1000}, (
        "every user in the batch must get the SAME amount"
    )


@pytest.mark.asyncio
async def test_bulk_credit_refuses_a_zero_amount(ctx, monkeypatch):
    """A no-op credit is almost always a mistake — say so instead of 'done'."""
    _fake_resolver(monkeypatch)
    spy = GatewaySpy(default={"ok": True})
    _patch_gw(monkeypatch, spy)

    res = await hb.fn_bulk_adjust_balance(
        ctx, hb.BulkAdjustBalanceParams(user_ids=[ALICE], amount=0),
    )

    assert res.status == "error"
    assert not spy.calls, "a zero adjustment must not touch any wallet"


# ─── reset conversations ──────────────────────────────────────────────── #

@pytest.mark.asyncio
async def test_bulk_reset_conversation_resets_each_user(ctx, monkeypatch):
    _fake_resolver(monkeypatch)
    spy = GatewaySpy(default={"ok": True})
    _patch_gw(monkeypatch, spy)

    res = await hb.fn_bulk_reset_conversation(
        ctx, hb.BulkUsersParams(user_ids=[ALICE, BOB]),
    )

    assert res.data["success_count"] == 2
    assert len(spy.calls) == 2, spy.summary


@pytest.mark.asyncio
async def test_gateway_failure_on_one_user_is_reported_per_user(ctx, monkeypatch):
    """A server-side error for ONE target must not be attributed to all."""
    _fake_resolver(monkeypatch)
    spy = GatewaySpy(
        responses={("DELETE", ALICE): {"error": "wallet locked"}},
        default={"ok": True},
    )
    _patch_gw(monkeypatch, spy)

    res = await hb.fn_bulk_set_user_active(
        ctx, hb.BulkSetActiveParams(user_ids=[ALICE, BOB], is_active=False),
    )

    assert res.data["failure_count"] == 1
    assert res.data["success_count"] == 1
    assert any("wallet locked" in f or ALICE in f for f in res.data["failed"])
