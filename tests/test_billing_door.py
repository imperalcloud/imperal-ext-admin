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


@pytest.mark.asyncio
async def test_default_key_is_stable_for_a_repeated_request(ctx, user, monkeypatch):
    monkeypatch.setenv("MONEY_MODE", "mysql")
    spy = GatewaySpy({("POST", "/wallet/credit"): {"ok": True, "applied": True, "balance": 1}})
    monkeypatch.setattr(hb, "_gw_request", spy)
    p = hb.AdjustBalanceParams(user_id="x", amount=500, reason="compensation")
    await hb.fn_adjust_balance(ctx, p)
    await hb.fn_adjust_balance(ctx, p)                  # an LLM retry of the same adjustment
    k1, k2 = (c["data"]["key"] for c in spy.calls_to("/wallet/credit", "POST"))
    assert k1 == k2 and k1.startswith("admin:")


@pytest.mark.asyncio
async def test_redis_mode_adjusts_once_per_key(ctx, user, monkeypatch):
    import fakeredis.aioredis
    monkeypatch.setenv("MONEY_MODE", "redis")
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)

    async def _r():
        return r
    monkeypatch.setattr(hb, "_redis", _r)
    monkeypatch.setattr(r, "aclose", lambda: __import__("asyncio").sleep(0), raising=False)
    p = hb.AdjustBalanceParams(user_id="x", amount=500, reason="compensation", idempotency_key="t-9")
    await hb.fn_adjust_balance(ctx, p)
    res = await hb.fn_adjust_balance(ctx, p)
    assert int(await r.get("imperal:wallet:imp_u_target")) == 500
    assert "already" in (res.summary or res.error or "").lower()


@pytest.mark.asyncio
async def test_list_balances_mysql_reads_the_gateway(ctx, monkeypatch):
    monkeypatch.setenv("MONEY_MODE", "mysql")
    spy = GatewaySpy({("GET", "/wallet/list"): {"items": [{"user_id": "imp_u_a", "sub": 5, "purchased": 7, "balance": 12}], "total": 1}})
    monkeypatch.setattr(hb, "_gw_request", spy)

    async def _no_redis():
        raise AssertionError("mysql mode must not read the Redis wallets")
    monkeypatch.setattr(hb, "_redis", _no_redis)
    res = await hb.fn_list_user_balances(ctx, hb.EmptyParams())
    assert res.data["items"][0]["balance"] == 12


def test_mistyped_money_mode_is_an_error(monkeypatch):
    monkeypatch.setenv("MONEY_MODE", "shadow")
    with pytest.raises(ValueError):
        hb._money_mode()


@pytest.mark.asyncio
async def test_mysql_replay_is_reported_as_already_done(ctx, user, monkeypatch):
    monkeypatch.setenv("MONEY_MODE", "mysql")
    spy = GatewaySpy({("POST", "/wallet/credit"): {"ok": True, "applied": False, "balance": 1500}})
    monkeypatch.setattr(hb, "_gw_request", spy)
    res = await hb.fn_adjust_balance(ctx, hb.AdjustBalanceParams(user_id="x", amount=500, idempotency_key="t-1"))
    assert "already" in (res.summary or "").lower() and res.data.get("duplicate") is True


@pytest.mark.asyncio
async def test_redis_claim_released_when_the_wallet_write_fails(ctx, user, monkeypatch):
    import fakeredis.aioredis
    monkeypatch.setenv("MONEY_MODE", "redis")
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)

    async def _r():
        return r
    monkeypatch.setattr(hb, "_redis", _r)
    monkeypatch.setattr(r, "aclose", lambda: __import__("asyncio").sleep(0), raising=False)

    async def _boom(*a, **k):
        raise ConnectionError("redis blip")
    monkeypatch.setattr(r, "incrby", _boom)
    await hb.fn_adjust_balance(ctx, hb.AdjustBalanceParams(user_id="x", amount=500, idempotency_key="t-2"))
    assert await r.get("imperal:billing:idem:admin:t-2") is None
