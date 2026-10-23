"""Billing stage E: an admin balance adjustment goes through the gateway money door
(purchased credits, idempotent by key) once MONEY_MODE leaves redis."""
import pytest

import handlers_billing as hb
from conftest import GatewaySpy


@pytest.fixture
def user(monkeypatch):
    async def _norm(value):
        return "imp_u_target", None
    monkeypatch.setattr(hb, "_normalize_to_imperal_id", _norm)


@pytest.mark.asyncio
async def test_credit_mysql_goes_through_the_door(ctx, user, monkeypatch):
    monkeypatch.setenv("MONEY_MODE", "mysql")
    spy = GatewaySpy({("POST", "/wallet/credit"): {"ok": True, "applied": True, "balance": 1500}})
    monkeypatch.setattr(hb, "_gw_request", spy)
    res = await hb.fn_adjust_balance(ctx, hb.AdjustBalanceParams(user_id="x", amount=500, reason="compensation",
                                                                 idempotency_key="t-1"))
    [call] = spy.calls_to("/v1/internal/billing/wallet/credit", "POST")
    assert call["data"]["bucket"] == "purchased"
    assert (call["data"]["key"], call["data"]["amount"], call["data"]["user_id"]) == ("admin:t-1", 500, "imp_u_target")
    assert res.data["balance"] == 1500


@pytest.mark.asyncio
async def test_deduct_mysql_refused_when_short(ctx, user, monkeypatch):
    monkeypatch.setenv("MONEY_MODE", "mysql")
    spy = GatewaySpy({("POST", "/wallet/charge"): {"ok": False, "applied": False, "balance": 100, "insufficient": True}})
    monkeypatch.setattr(hb, "_gw_request", spy)
    res = await hb.fn_adjust_balance(ctx, hb.AdjustBalanceParams(user_id="x", amount=-500))
    [call] = spy.calls_to("/v1/internal/billing/wallet/charge", "POST")
    assert call["data"]["allow_negative"] is False and call["data"]["key"].startswith("admin:")
    assert "Insufficient" in (res.error or "")


@pytest.mark.asyncio
async def test_get_balance_mysql_reads_the_gateway(ctx, user, monkeypatch):
    monkeypatch.setenv("MONEY_MODE", "mysql")
    spy = GatewaySpy({("GET", "/internal/balance/"): {"balance": 777, "sub": 700, "purchased": 77, "plan": "pro"},
                      ("GET", "/internal/subscription/"): {"plan": "pro", "status": "active"}})
    monkeypatch.setattr(hb, "_gw_request", spy)

    async def _no_redis():
        raise AssertionError("mysql mode must not read the Redis wallet")
    monkeypatch.setattr(hb, "_redis", _no_redis)
    res = await hb.fn_get_user_balance(ctx, hb.UserBalanceParams(user_id="x"))
    assert (res.data["balance"], res.data["sub"], res.data["purchased"]) == (777, 700, 77)
