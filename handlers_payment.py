"""Admin · Payment provider configuration handlers (gateway-backed)."""
from __future__ import annotations
import logging
import httpx
from pydantic import BaseModel, Field
from app import chat, ActionResult, AUTH_GW, AUTH_SERVICE_TOKEN, _verify_write_reflected
from models_records import PaymentConfigRecord, PaymentTestResultRecord

log = logging.getLogger("admin")

def _acting(ctx) -> str:
    try:
        return str(getattr(getattr(ctx, "user", None), "imperal_id", "") or "")
    except Exception:
        return ""

class EmptyParams(BaseModel):
    pass

class SaveStripeKeysParams(BaseModel):
    secret_key: str = Field("", description="New Stripe secret key (sk_…). Blank = keep current.")
    publishable_key: str = Field("", description="New Stripe publishable key (pk_…). Blank = keep current.")
    webhook_secret: str = Field("", description="Optional whsec_…; blank = auto-manage the live webhook.")

@chat.function("payment_config_get", action_type="read", data_model=PaymentConfigRecord,
               description="Get the real Stripe configuration from the billing gateway.")
async def fn_payment_config_get(ctx, params: EmptyParams) -> ActionResult:
    if not AUTH_GW or not AUTH_SERVICE_TOKEN:
        return ActionResult.error("missing AUTH_GW or AUTH_SERVICE_TOKEN")
    url = f"{AUTH_GW.rstrip('/')}/v1/internal/billing/stripe-config"
    try:
        async with httpx.AsyncClient(timeout=8.0) as c:
            r = await c.get(url, headers={"X-Service-Token": AUTH_SERVICE_TOKEN, "X-Acting-User": _acting(ctx)})
    except Exception as e:
        return ActionResult.error(f"gateway unreachable: {type(e).__name__}")
    if r.status_code == 403:
        return ActionResult.error("admin role required")
    if r.status_code != 200:
        return ActionResult.error(f"gateway error: status={r.status_code}")
    d = r.json()
    return ActionResult.success(
        data={**d, "has_webhook_secret": d.get("webhook_secret_set")},
        summary=f"Stripe {d.get('mode')} mode (source={d.get('source')}) — "
                + ("enabled" if d.get('enabled') else "disabled"))

@chat.function("payment_test_connection", action_type="read", data_model=PaymentTestResultRecord,
               description="Test Stripe API connection via the billing gateway (real active key).")
async def fn_payment_test_connection(ctx, params: EmptyParams) -> ActionResult:
    if not AUTH_GW or not AUTH_SERVICE_TOKEN:
        return ActionResult.error("missing AUTH_GW or AUTH_SERVICE_TOKEN")
    url = f"{AUTH_GW.rstrip('/')}/v1/internal/billing/stripe-config"
    try:
        async with httpx.AsyncClient(timeout=8.0) as c:
            r = await c.get(url, headers={"X-Service-Token": AUTH_SERVICE_TOKEN, "X-Acting-User": _acting(ctx)})
    except Exception as e:
        return ActionResult.error(f"gateway unreachable: {type(e).__name__}")
    if r.status_code != 200:
        return ActionResult.error(f"gateway error: status={r.status_code}")
    d = r.json()
    acct = d.get("account") or {}
    bal = d.get("balance") or {}
    ok = bool(acct.get("id"))
    return ActionResult.success(
        data={"connected": ok, "currency": bal.get("currency", "?"), "amount": bal.get("amount", 0)},
        summary=(f"Connected! Account {acct.get('id')}, balance {bal.get('amount',0)} {bal.get('currency','?')}"
                 if ok else "Stripe did not authenticate with the current key."))

@chat.function("payment_config_save", action_type="write", event="payment_config_saved",
               data_model=PaymentConfigRecord,
               description="Update Stripe keys via the billing gateway (validates, auto-manages webhook, applies instantly).")
async def fn_payment_config_save(ctx, params: SaveStripeKeysParams) -> ActionResult:
    if not AUTH_GW or not AUTH_SERVICE_TOKEN:
        return ActionResult.error("missing AUTH_GW or AUTH_SERVICE_TOKEN")
    if not (params.secret_key or params.publishable_key or params.webhook_secret):
        return ActionResult.error("nothing to change — provide at least one key")
    url = f"{AUTH_GW.rstrip('/')}/v1/internal/billing/stripe-config"
    body = {k: v for k, v in {
        "secret_key": params.secret_key or None,
        "publishable_key": params.publishable_key or None,
        "webhook_secret": params.webhook_secret or None,
    }.items() if v}
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.put(url, json=body, headers={
                "X-Service-Token": AUTH_SERVICE_TOKEN, "X-Acting-User": _acting(ctx),
                "Content-Type": "application/json"})
    except Exception as e:
        return ActionResult.error(f"save HTTP error: {type(e).__name__}: {e}")
    if r.status_code == 403:
        return ActionResult.error("admin role required to change Stripe keys")
    if r.status_code != 200:
        return ActionResult.error(f"save failed: status={r.status_code} body={r.text[:200]}")
    d = r.json()
    return ActionResult.success(
        data={**d, "has_webhook_secret": d.get("webhook_secret_set")},
        summary=f"Saved. Stripe {d.get('mode')} mode (source={d.get('source')}).",
        refresh_panels=["payment"])
