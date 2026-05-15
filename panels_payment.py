"""Admin · Payment settings panel section."""
from __future__ import annotations

import logging
import os

from imperal_sdk import ui

log = logging.getLogger("admin")


def _test_stripe_connection() -> tuple[bool, str]:
    """Test Stripe API connection. Returns (success, message)."""
    try:
        import stripe
        stripe.api_key = await ctx.secrets.get("stripe_secret_key") or os.getenv("STRIPE_SECRET_KEY", "")
        if not stripe.api_key:
            return False, "STRIPE_SECRET_KEY not set"
        balance = stripe.Balance.retrieve()
        available = balance.available[0] if balance.available else None
        currency = getattr(available, "currency", "?") if available else "?"
        return True, f"Connected! Currency: {currency}"
    except Exception as e:
        return False, f"Failed: {type(e).__name__}: {e}"


async def build_payment(ctx, **kwargs):
    """Payment provider settings — Stripe keys, tiers, status."""
    stripe_enabled = os.getenv("STRIPE_ENABLED", "false").lower() == "true"
    sk = await ctx.secrets.get("stripe_secret_key")
    has_secret = bool(sk or os.getenv("STRIPE_SECRET_KEY", ""))
    has_pubkey = bool(os.getenv("STRIPE_PUBLISHABLE_KEY", ""))
    has_webhook = bool(os.getenv("STRIPE_WEBHOOK_SECRET", ""))

    # Status
    if stripe_enabled and has_secret:
        status_badge = ui.Badge("Active", color="green")
    elif has_secret:
        status_badge = ui.Badge("Keys Set (disabled)", color="yellow")
    else:
        status_badge = ui.Badge("Not Configured", color="red")

    mode = "test" if "test" in (sk or os.getenv("STRIPE_SECRET_KEY", "")) else "live"

    children = [
        ui.Header("Payment Provider", level=3),
        ui.Stack(direction="h", gap=2, children=[
            ui.Text("Provider: Stripe", variant="body"),
            status_badge,
            ui.Badge(f"Mode: {mode}", color="blue" if mode == "test" else "green"),
        ]),

        ui.Divider(),
        ui.Header("Configuration", level=4),
        ui.KeyValue(items=[
            {"key": "Stripe Enabled", "value": str(stripe_enabled)},
            {"key": "Secret Key", "value": "Set" if has_secret else "Missing"},
            {"key": "Publishable Key", "value": "Set" if has_pubkey else "Missing"},
            {"key": "Webhook Secret", "value": "Set" if has_webhook else "Missing"},
            {"key": "Webhook URL", "value": "https://auth.imperal.io/v1/webhooks/stripe"},
        ]),

        ui.Alert(
            title="Configuration",
            message="Stripe keys are configured via environment variables on Auth Gateway. "
                    "Use 'Test Connection' to verify keys work.",
            type="info",
        ),

        ui.Button(
            label="Test Connection", icon="Zap", variant="secondary",
            on_click=ui.Call("__panel__tools", section="payment", test="1"),
        ),
    ]

    # Show test result inline when test=1 param is passed
    if kwargs.get("test") == "1":
        ok, msg = _test_stripe_connection()
        children.append(ui.Alert(
            title="Connection Test",
            message=msg,
            type="success" if ok else "error",
        ))

    children.extend([
        ui.Divider(),
        ui.Header("Top-Up Tiers", level=4),
        ui.DataTable(
            columns=[
                ui.DataColumn(key="tokens", label="Tokens", width=100),
                ui.DataColumn(key="price", label="Price", width=100),
            ],
            rows=[
                {"tokens": "5,000", "price": "$5"},
                {"tokens": "20,000", "price": "$20"},
                {"tokens": "50,000", "price": "$50"},
            ],
        ),
        ui.Text(
            "Tiers are currently hardcoded. Admin-configurable tiers via unified_config coming soon.",
            variant="caption",
        ),
    ])

    return ui.Stack(children=children, gap=2)
