"""Admin · Payment provider configuration handlers."""
from __future__ import annotations

import logging

from pydantic import BaseModel

from app import chat, ActionResult
from models_records import PaymentConfigRecord, PaymentTestResultRecord

log = logging.getLogger("admin")


class EmptyParams(BaseModel):
    pass


@chat.function(
    "payment_config_get",
    action_type="read",
    data_model=PaymentConfigRecord,
    description="Get current payment provider configuration.",
)
async def fn_payment_config_get(ctx, params: EmptyParams) -> ActionResult:
    try:
        import os
        stripe_enabled = os.getenv("STRIPE_ENABLED", "false").lower() == "true"
        has_secret = bool(os.getenv("STRIPE_SECRET_KEY", ""))
        has_pubkey = bool(os.getenv("STRIPE_PUBLISHABLE_KEY", ""))
        has_webhook = bool(os.getenv("STRIPE_WEBHOOK_SECRET", ""))
        mode = "test" if "test" in os.getenv("STRIPE_SECRET_KEY", "") else "live"

        return ActionResult.success(
            data={
                "configured": has_secret,
                "enabled": stripe_enabled,
                "mode": mode,
                "has_publishable_key": has_pubkey,
                "has_webhook_secret": has_webhook,
            },
            summary=(
                f"Stripe {mode} mode — "
                + ("enabled" if stripe_enabled else "disabled")
                + f". Keys: {'set' if has_secret else 'missing'}."
            ),
        )
    except Exception as e:
        return ActionResult.error(f"Failed: {e}")


@chat.function(
    "payment_test_connection",
    action_type="read",
    data_model=PaymentTestResultRecord,
    description="Test Stripe API connection with current keys.",
)
async def fn_payment_test_connection(ctx, params: EmptyParams) -> ActionResult:
    try:
        import stripe
        import os
        stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
        if not stripe.api_key:
            return ActionResult.error("STRIPE_SECRET_KEY not set")
        balance = stripe.Balance.retrieve()
        available = balance.available[0] if balance.available else None
        currency = getattr(available, "currency", "?") if available else "?"
        amount = getattr(available, "amount", 0) if available else 0
        return ActionResult.success(
            data={"connected": True, "currency": currency, "amount": amount},
            summary=f"Stripe connected! Currency: {currency}, balance: {amount}",
        )
    except Exception as e:
        return ActionResult.error(f"Stripe connection failed: {type(e).__name__}: {e}")
