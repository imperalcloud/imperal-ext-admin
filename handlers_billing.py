"""Admin · Billing handlers — plans, balances, token adjustments, health (Auth-GW + Redis)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid

import httpx
import redis.asyncio as aioredis
from pydantic import BaseModel, Field

from app import chat, ActionResult, AUTH_GW, EmptyParams, _resolve_user_by_email
from models_records import (
    BillingHealthResponse, BillingOverviewResponse, UserBalanceRecord, UserBalancesResponse,
)

log = logging.getLogger("admin")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Key patterns (must match imperal_kernel.billing.wallet)
WALLET_PREFIX = "imperal:wallet:"
HOLD_PREFIX = "imperal:wallet:hold:"
STREAM_KEY = "imperal:billing:events"


async def _redis() -> aioredis.Redis:
    return aioredis.from_url(REDIS_URL, decode_responses=True)


async def _normalize_to_imperal_id(value: str) -> tuple[str | None, str | None]:
    """Coerce a user identifier to a canonical `imp_u_*` imperal_id.

    Returns ``(imperal_id, None)`` on success or ``(None, error_message)`` on failure.

    Rationale: every wallet operation MUST key by ``imp_u_*`` — passing an email
    builds an orphan Redis key ``imperal:wallet:<email>`` that no other service
    reads, silently corrupting the wallet namespace. LLM wrappers regularly
    confuse the two when the user types an email in chat, so the handler
    normalizes before touching Redis.

    * Starts with ``imp_u_`` -> returned as-is (trusted shape).
    * Contains ``@`` -> looked up via auth-gw ``/v1/users?search=`` and resolved
      to the matching account's imperal_id; case-insensitive email match.
    * Anything else -> rejected.
    """
    if not value:
        return None, "user_id is empty"
    v = value.strip()
    if v.startswith("imp_u_"):
        return v, None
    if "@" in v:
        try:
            resolved = await _resolve_user_by_email(v)
        except Exception as e:
            return None, f"email lookup failed for {v!r}: {e}"
        if not resolved:
            return None, (
                f"no user found for email {v!r}. Either the address is wrong "
                f"or the user hasn't been created yet. Run list_users or "
                f"get_user_by_email to confirm the imperal_id, then retry "
                f"adjust_balance with that imp_u_* value."
            )
        return resolved, None
    return None, (
        f"user_id {v!r} is neither an imperal_id (imp_u_*) nor an email. "
        f"Provide the imp_u_* value from list_users or get_user_by_email."
    )


async def _scan_keys(r: aioredis.Redis, pattern: str) -> list[str]:
    """Collect all keys matching pattern via SCAN."""
    keys: list[str] = []
    cursor = "0"
    while True:
        cursor, batch = await r.scan(cursor=cursor, match=pattern, count=200)
        keys.extend(batch)
        if cursor == 0 or cursor == "0":
            break
    return keys


# ─── Models ───────────────────────────────────────────────────────────── #

class UserBalanceParams(BaseModel):
    """Look up a specific user's token balance."""
    user_id: str = Field(description="Canonical imperal_id of the user — format `imp_u_XXXXXXXX`. NOT an email. If you only have an email, call get_user_by_email or list_users first to resolve the imperal_id, then pass that value here. Passing an email creates an orphan wallet key that no other service reads.")


class AdjustBalanceParams(BaseModel):
    """Credit or deduct tokens from a user wallet."""
    user_id: str = Field(description="Canonical imperal_id of the target user — format `imp_u_XXXXXXXX`. NOT an email. If you only have an email, call get_user_by_email or list_users first to resolve the imperal_id, then pass that value here. Passing an email creates an orphan wallet key that no other service reads.")
    amount: int = Field(description="Token amount (positive=credit, negative=deduct)")
    reason: str = Field(default="admin_adjustment", description="Reason for adjustment")


# ─── Handlers ─────────────────────────────────────────────────────────── #

@chat.function("billing_overview", action_type="read",
               data_model=BillingOverviewResponse,
               description="Show billing plans, pricing tiers, and platform summary.")
async def fn_billing_overview(ctx, params: EmptyParams) -> ActionResult:
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            resp = await c.get(f"{AUTH_GW}/v1/billing/plans")
        plans = resp.json() if resp.status_code == 200 else []

        r = await _redis()
        try:
            all_keys = await _scan_keys(r, f"{WALLET_PREFIX}*")
            wallet_count = sum(1 for k in all_keys if k.count(":") == 2)
            stream_len = await r.xlen(STREAM_KEY)
        finally:
            await r.aclose()

        plan_summary = [{
            "name": p.get("name", "?"), "price": p.get("price", 0),
            "interval": p.get("interval", "monthly"),
            "ai_tokens": (p.get("limits") or {}).get("ai_tokens"),
            "tool_calls": (p.get("limits") or {}).get("tool_calls"),
        } for p in plans]

        return ActionResult.success(
            data={"items": plan_summary, "total": len(plans),
                  "plans_count": len(plans), "wallets_active": wallet_count,
                  "stream_events_total": stream_len},
            summary=f"{len(plans)} plans, {wallet_count} wallets, {stream_len} stream events",
        )
    except Exception as e:
        log.error("billing_overview failed: %s", e)
        return ActionResult.error(f"Failed: {e}", retryable=True)


@chat.function("list_user_balances", action_type="read",
               data_model=UserBalancesResponse,
               description="List all user wallet balances with totals.")
async def fn_list_user_balances(ctx, params: EmptyParams) -> ActionResult:
    try:
        r = await _redis()
        try:
            all_keys = await _scan_keys(r, f"{WALLET_PREFIX}*")
            wallets, total = [], 0
            for key in all_keys:
                uid = key.removeprefix(WALLET_PREFIX)
                if ":" in uid:
                    continue
                bal = int(await r.get(key) or 0)
                wallets.append({"user_id": uid, "balance": bal})
                total += bal
        finally:
            await r.aclose()

        wallets.sort(key=lambda w: w["balance"], reverse=True)
        return ActionResult.success(
            data={"items": wallets, "total": len(wallets),
                  "total_users": len(wallets),
                  "total_tokens_in_circulation": total},
            summary=f"{len(wallets)} wallets, {total} total tokens",
        )
    except Exception as e:
        log.error("list_user_balances failed: %s", e)
        return ActionResult.error(f"Failed: {e}", retryable=True)


@chat.function("get_user_balance", action_type="read",
               data_model=UserBalanceRecord,
               description="Get token balance for a specific user including active holds.")
async def fn_get_user_balance(ctx, params: UserBalanceParams) -> ActionResult:
    target_id, err = await _normalize_to_imperal_id(params.user_id)
    if err:
        return ActionResult.error(err)
    try:
        r = await _redis()
        try:
            bal = int(await r.get(f"{WALLET_PREFIX}{target_id}") or 0)
            hold_keys = await _scan_keys(r, f"{HOLD_PREFIX}{target_id}:*")
            holds = []
            for key in hold_keys:
                held = int(await r.get(key) or 0)
                trace = key.split(":")[-1]
                holds.append({"trace_id": trace, "held": held})
        finally:
            await r.aclose()

        total_held = sum(h["held"] for h in holds)
        return ActionResult.success(
            data={"user_id": target_id, "balance": bal,
                  "available": bal - total_held, "holds": holds, "holds_total": total_held},
            summary=f"Balance: {bal} tokens ({len(holds)} holds, {total_held} held)",
        )
    except Exception as e:
        log.error("get_user_balance failed: %s", e)
        return ActionResult.error(f"Failed: {e}", retryable=True)


@chat.function("adjust_balance", action_type="write", event="billing_adjusted",
               data_model=UserBalanceRecord,
               description="Credit or deduct tokens. Positive=credit, negative=deduct.")
async def fn_adjust_balance(ctx, params: AdjustBalanceParams) -> ActionResult:
    if params.amount == 0:
        return ActionResult.error("Amount must be non-zero")
    target_id, err = await _normalize_to_imperal_id(params.user_id)
    if err:
        return ActionResult.error(err)
    try:
        r = await _redis()
        try:
            wallet_key = f"{WALLET_PREFIX}{target_id}"
            if params.amount > 0:
                new_bal = await r.incrby(wallet_key, params.amount)
            else:
                current = int(await r.get(wallet_key) or 0)
                if current + params.amount < 0:
                    return ActionResult.error(
                        f"Insufficient: {current} tokens, cannot deduct {abs(params.amount)}")
                new_bal = await r.decrby(wallet_key, abs(params.amount))

            admin_id = ctx.user.imperal_id if hasattr(ctx, "user") and ctx.user else "system"
            ev_type = "credit" if params.amount > 0 else "deduct"
            await r.xadd(STREAM_KEY, {
                "event_id": str(uuid.uuid4()), "type": ev_type,
                "data": json.dumps({
                    "user_id": target_id, "amount": abs(params.amount),
                    "reason": params.reason, "admin_id": admin_id,
                    "description": f"Admin adjustment: {params.reason}",
                }),
            })
        finally:
            await r.aclose()

        verb = "credited" if params.amount > 0 else "deducted"
        return ActionResult.success(
            data={"user_id": target_id, "balance": int(new_bal),
                  "adjustment": params.amount, "reason": params.reason},
            summary=f"{verb} {abs(params.amount)} tokens -> balance: {new_bal}",
            refresh_panels=["tools"],
        )
    except Exception as e:
        log.error("adjust_balance failed: %s", e)
        return ActionResult.error(f"Failed: {e}", retryable=True)


@chat.function("billing_health", action_type="read",
               data_model=BillingHealthResponse,
               description="Check billing system health: stream, consumers, pending lag.")
async def fn_billing_health(ctx, params: EmptyParams) -> ActionResult:
    try:
        r = await _redis()
        try:
            stream_len, first_id, last_id = 0, None, None
            try:
                info = await r.xinfo_stream(STREAM_KEY)
                stream_len = info.get("length", 0)
                first_id = (info.get("first-entry") or [None])[0]
                last_id = (info.get("last-entry") or [None])[0]
            except Exception:
                pass

            groups = []
            try:
                for g in await r.xinfo_groups(STREAM_KEY):
                    groups.append({
                        "name": g.get("name", "?"),
                        "consumers": g.get("consumers", 0),
                        "pending": g.get("pending", 0),
                        "lag": g.get("lag", "n/a"),
                    })
            except Exception:
                groups = [{"error": "Could not read consumer groups"}]
        finally:
            await r.aclose()

        # Systemd service checks
        consumer_ok, statuses = True, []
        for i in (1, 2):
            unit = f"imperal-billing-consumer@{i}"
            try:
                proc = await asyncio.create_subprocess_exec(
                    "systemctl", "is-active", f"{unit}.service",
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                out, _ = await proc.communicate()
                status = out.decode().strip() if out else "unknown"
            except Exception:
                status = "unknown"
            statuses.append({"unit": unit, "status": status})
            if status != "active":
                consumer_ok = False

        pending = sum(g.get("pending", 0) for g in groups if isinstance(g.get("pending"), int))
        return ActionResult.success(
            data={"stream_length": stream_len, "first_entry_id": first_id,
                  "last_entry_id": last_id, "consumer_groups": groups,
                  "pending_total": pending, "consumers": statuses,
                  "healthy": consumer_ok and pending < 100},
            summary=f"Stream: {stream_len}, pending: {pending}, consumers: {'OK' if consumer_ok else 'DEGRADED'}",
        )
    except Exception as e:
        log.error("billing_health failed: %s", e)
        return ActionResult.error(f"Failed: {e}", retryable=True)
