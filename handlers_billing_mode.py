"""Admin · manual billing control — HOW and WHEN a customer pays.

Owner design 2026-08-13: "для enterprise я бы хотел иметь доступ выбора когда
и как я хочу чтобы человек платил ... может у нас расчет с компанией Enterprise
не через карту ... нужно какое-то ручное управление! И для enterprise карту НЕ
обязательно."

Until now this was not expressible at all: whether a subscription got charged
was DERIVED from `plans.price > 0`, so a price-0 enterprise plan could never be
billed, and a contract customer who settles by bank transfer was still nagged
for a card. These two tools expose the declared `billing_mode` contract
(auth-gw app/billing/billing_mode.py) so the owner states the intent instead of
the platform guessing it.

    card    — self-serve: the saved card is charged on renewal (the default)
    manual  — settled off-Stripe (invoice / bank transfer): never auto-charged,
              never auto-expired, no card ever required
    free    — comped access: never charged, no card

Plus `contract_amount_cents`, which is what finally makes a price-0 enterprise
CONTRACT chargeable at its real agreed value, and `extend_days` — the manual
equivalent of a renewal for an invoice-paying customer.

All writes go through the admin-only gateway endpoint
PUT /v1/internal/billing/subscription-billing (X-Acting-User must be an admin),
so the audit trail and RBAC are the platform's existing ones, not a side door.
"""
from __future__ import annotations

import logging

from imperal_sdk._shared_http import shared_http
from pydantic import BaseModel, Field

from app import (
    chat, ActionResult, AUTH_GW, AUTH_SERVICE_TOKEN, _admin_put,
)
from handlers_billing import _normalize_to_imperal_id

log = logging.getLogger("admin")

_MODES = ("card", "manual", "free")

_MODE_HUMAN = {
    "card": "pays by card (automatic renewal)",
    "manual": "pays manually / by invoice — no card needed, never auto-charged",
    "free": "free access — never charged",
}


def _acting(ctx) -> str:
    """The admin performing the change (mirrors handlers_billing._acting)."""
    try:
        return str(getattr(getattr(ctx, "user", None), "imperal_id", "") or "")
    except Exception:
        return ""


async def _admin_get(path: str, acting: str = "", timeout: float = 5.0):
    """GET against the gateway with the service token — mirror of app._admin_put.

    Defined here rather than reused from app.py because only the PUT helper
    exists there; keeping the shape identical means the auth/---header contract
    stays in one recognisable form.
    """
    headers = {"X-Service-Token": AUTH_SERVICE_TOKEN}
    if acting:
        headers["X-Acting-User"] = acting
    async with shared_http(timeout=timeout) as client:
        return await client.get(f"{AUTH_GW.rstrip('/')}{path}", headers=headers)


def _money(cents: int | None) -> str:
    if not cents:
        return "—"
    return f"${int(cents) / 100:,.2f}"


def _describe(payload: dict) -> str:
    """One human line describing how a subscription settles."""
    mode = str(payload.get("billing_mode") or "card")
    plan = payload.get("plan") or "—"
    bits = [f"plan {plan}", _MODE_HUMAN.get(mode, mode)]
    amount = payload.get("contract_amount_cents")
    if amount:
        bits.append(f"contract amount {_money(amount)}/period")
    if payload.get("card_required"):
        bits.append("card REQUIRED")
    else:
        bits.append("no card required")
    expires = payload.get("expires_at")
    bits.append(f"period ends {expires}" if expires else "never expires")
    note = payload.get("billing_note")
    if note:
        bits.append(f"note: {note}")
    return "; ".join(bits)


class GetUserBillingModeParams(BaseModel):
    """Read how one user's subscription settles."""
    user_id: str = Field(
        description="Who to look at — imperal_id (imp_u_*), email, or name.",
    )


@chat.function(
    "get_user_billing_mode",
    action_type="read",
    description=(
        "Show HOW a user's subscription settles: by card, manually/by invoice, "
        "or free — plus any contract amount, whether a card is required, and "
        "when the period ends. Use for: how does this customer pay, does this "
        "user need a card, enterprise billing arrangement."
    ),
)
async def fn_get_user_billing_mode(ctx, params: GetUserBillingModeParams) -> ActionResult:
    """Report the declared settlement mode for one user's active subscription."""
    if not AUTH_GW or not AUTH_SERVICE_TOKEN:
        return ActionResult.error("missing AUTH_GW or AUTH_SERVICE_TOKEN")

    uid, err = await _normalize_to_imperal_id(params.user_id)
    if err:
        return ActionResult.error(err)

    try:
        resp = await _admin_get(
            f"/v1/internal/billing/subscription-billing/{uid}", _acting(ctx),
        )
    except Exception as e:
        return ActionResult.error(f"read HTTP error: {type(e).__name__}: {e}")
    if resp.status_code == 403:
        return ActionResult.error("admin role required to read billing settlement")
    if resp.status_code == 404:
        return ActionResult.error(f"{uid} has no active subscription")
    if resp.status_code != 200:
        return ActionResult.error(
            f"read failed: status={resp.status_code} body={resp.text[:200]}"
        )
    try:
        payload = resp.json()
    except Exception:
        payload = {}

    return ActionResult.success(
        data={"user_id": uid, **(payload if isinstance(payload, dict) else {})},
        summary=f"{uid}: {_describe(payload if isinstance(payload, dict) else {})}",
    )


class SetUserBillingModeParams(BaseModel):
    """Declare how and when one user pays. Only what you pass is changed."""
    user_id: str = Field(
        description="Who to change — imperal_id (imp_u_*), email, or name.",
    )
    mode: str | None = Field(
        None,
        description=(
            "How they pay: 'card' (automatic card renewal), 'manual' (invoice / "
            "bank transfer — no card, never auto-charged), or 'free' (comped). "
            "Omit to leave the mode as it is."
        ),
    )
    contract_amount: float | None = Field(
        None, ge=0,
        description=(
            "Amount to charge per period, in DOLLARS, instead of the plan price "
            "— this is what makes a price-0 enterprise contract chargeable. "
            "Only meaningful together with mode='card'."
        ),
    )
    clear_contract_amount: bool = Field(
        False,
        description="Drop the custom amount and fall back to the plan's own price.",
    )
    note: str | None = Field(
        None, max_length=255,
        description="Why, for the record — e.g. 'pays by bank transfer, contract INV-2026-04'.",
    )
    extend_days: int | None = Field(
        None, ge=0,
        description=(
            "Extend the paid period by N days — the manual equivalent of a "
            "renewal, for a customer who just paid an invoice."
        ),
    )
    expires_at: str | None = Field(
        None,
        description=(
            "Set the period end explicitly (ISO date/time). Pass 'never' for a "
            "seat that never expires (contract or comped access)."
        ),
    )


@chat.function(
    "set_user_billing_mode",
    action_type="write",
    effects=["update:subscription_billing"],
    event="user_billing_mode_set",
    description=(
        "Choose HOW and WHEN a customer pays: by card, manually by invoice/bank "
        "transfer (no card required), or free. Optionally set a custom contract "
        "amount, extend the paid period after an invoice is settled, or make the "
        "seat never expire. Use for: this enterprise pays by invoice, let this "
        "company sit free, charge this enterprise $500/month, extend their period."
    ),
)
async def fn_set_user_billing_mode(ctx, params: SetUserBillingModeParams) -> ActionResult:
    """Declare a user's settlement mode (owner's manual billing control).

    Patch semantics — only the fields actually supplied are changed, so the
    mode can be flipped without disturbing the period and vice versa.
    """
    if not AUTH_GW or not AUTH_SERVICE_TOKEN:
        return ActionResult.error("missing AUTH_GW or AUTH_SERVICE_TOKEN")

    mode = (params.mode or "").strip().lower() or None
    if mode is not None and mode not in _MODES:
        return ActionResult.error(
            f"unknown mode {mode!r} — use one of: {', '.join(_MODES)}"
        )

    if not any([
        mode, params.contract_amount is not None, params.clear_contract_amount,
        params.note, params.extend_days, params.expires_at,
    ]):
        return ActionResult.error(
            "nothing to change — pass a mode, an amount, a note, extend_days or expires_at"
        )

    uid, err = await _normalize_to_imperal_id(params.user_id)
    if err:
        return ActionResult.error(err)

    body: dict = {"user_id": uid}
    if mode:
        body["mode"] = mode
    if params.contract_amount is not None:
        # Dollars at the human boundary, cents on the wire — money is only ever
        # stored and charged as an integer number of cents.
        body["contract_amount_cents"] = int(round(params.contract_amount * 100))
    if params.clear_contract_amount:
        body["clear_contract_amount"] = True
    if params.note:
        body["note"] = params.note
    if params.extend_days:
        body["extend_days"] = int(params.extend_days)
    if params.expires_at:
        raw = params.expires_at.strip()
        body["expires_at"] = "" if raw.lower() in ("never", "none", "-") else raw

    try:
        resp = await _admin_put(
            "/v1/internal/billing/subscription-billing", body, _acting(ctx),
        )
    except Exception as e:
        return ActionResult.error(f"save HTTP error: {type(e).__name__}: {e}")
    if resp.status_code == 403:
        return ActionResult.error("admin role required to change billing settlement")
    if resp.status_code == 404:
        return ActionResult.error(f"{uid} has no active subscription to configure")
    if resp.status_code == 400:
        return ActionResult.error(f"rejected: {resp.text[:200]}")
    if resp.status_code != 200:
        return ActionResult.error(
            f"save failed: status={resp.status_code} body={resp.text[:200]}"
        )
    try:
        payload = resp.json()
    except Exception:
        payload = {}

    log.info("billing settlement changed by=%s user=%s body=%s",
             _acting(ctx), uid, body)
    return ActionResult.success(
        data={"user_id": uid, **(payload if isinstance(payload, dict) else {}), "action": "saved"},
        summary=f"{uid}: {_describe(payload if isinstance(payload, dict) else {})}",
        refresh_panels=["tools"],
    )
