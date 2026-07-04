"""Admin · Payment settings panel — real Stripe state + key management.

Uses the same admin gateway contract as the payment tools and renders the
current live/configured state plus key rotation form.
"""
from __future__ import annotations
import logging
from imperal_sdk import ui
from app import _gw_request

log = logging.getLogger("admin")

async def _get_config(acting: str) -> dict:
    try:
        result = await _gw_request("GET", "/v1/internal/billing/stripe-config", acting=acting)
        return result if isinstance(result, dict) else {}
    except Exception as e:
        log.warning("payment _get_config error: %s", e)
        return {}

async def build_payment(ctx, **kwargs):
    acting = str(getattr(getattr(ctx, "user", None), "imperal_id", "") or "")
    d = await _get_config(acting)
    mode = d.get("mode", "unset")
    acct = d.get("account") or {}
    bal = d.get("balance") or {}
    wh = d.get("webhook") or {}

    status_badge = (ui.Badge("Active", color="green") if d.get("enabled") and d.get("configured")
                    else ui.Badge("Keys Set (disabled)", color="yellow") if d.get("configured")
                    else ui.Badge("Not Configured", color="red"))

    children = [
        ui.Header("Payment Provider", level=3,
                  subtitle="Stripe configuration, health, and key rotation"),
        ui.Stack(direction="h", gap=2, children=[
            ui.Text("Provider: Stripe", variant="body"), status_badge,
            ui.Badge(f"Mode: {mode}", color="green" if mode == "live" else "blue"),
            ui.Badge(f"Source: {d.get('source','?')}", color="gray"),
        ]),
        ui.Divider(),
        ui.Header("Live status", level=4),
        ui.KeyValue(items=[
            {"key": "Account", "value": acct.get("id", "—")},
            {"key": "Charges enabled", "value": str(acct.get("charges_enabled", "—"))},
            {"key": "Payouts enabled", "value": str(acct.get("payouts_enabled", "—"))},
            {"key": "Balance", "value": f"{bal.get('amount','—')} {bal.get('currency','')}".strip()},
            {"key": "Webhook", "value": ("healthy" if wh.get("healthy") and wh.get("events_ok")
                                          else "needs attention") + f" ({wh.get('endpoint_id','—')})"},
        ]),
        ui.Divider(),
        ui.Header("Configuration (masked)", level=4),
        ui.KeyValue(items=[
            {"key": "Secret Key", "value": d.get("secret_key_masked") or "Missing"},
            {"key": "Publishable Key", "value": d.get("publishable_key_masked") or "Missing"},
            {"key": "Webhook Secret", "value": "Set" if d.get("webhook_secret_set") else "Missing"},
            {"key": "Webhook URL", "value": (wh.get("url") or "https://auth.imperal.io/v1/webhooks/stripe")},
        ]),
        ui.Button(label="Test Connection", icon="Zap", variant="secondary",
                  on_click=ui.Call("payment_test_connection")),
        ui.Divider(),
        ui.Header("Change keys", level=4),
        ui.Alert(title="How it works",
                 message="Paste new sk_/pk_ and Apply. The system validates the key, detects "
                         "test/live, auto-creates/verifies the live webhook, stores everything "
                         "encrypted in Vault, and applies instantly — no restart. Leave a field "
                         "blank to keep its current value.", type="info"),
        ui.Form(action="payment_config_save", submit_label="Apply", defaults={}, children=[
            ui.Section(title="Stripe keys", children=[
                ui.Text("Secret key (sk_…)", variant="caption"),
                ui.Password(param_name="secret_key", placeholder="sk_live_… (blank = keep)"),
                ui.Text("Publishable key (pk_…)", variant="caption"),
                ui.Password(param_name="publishable_key", placeholder="pk_live_… (blank = keep)"),
                ui.Text("Webhook secret (optional — blank = auto-manage)", variant="caption"),
                ui.Password(param_name="webhook_secret", placeholder="whsec_… (optional)"),
            ]),
        ]),
    ]
    return ui.Stack(children=children, gap=2)
