# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors.
# Licensed under the AGPL-3.0 License.
"""SDL records for the admin READ tools (per-user billing detail + agencies +
review queues). Field names mirror the ACTUAL gateway endpoint payloads
(captured live 2026-06-30) — federal I-EXT-RECORD-FIELD-NAMING-SYMMETRIC."""
from __future__ import annotations

from typing import Optional, Any
from pydantic import model_validator

from imperal_sdk import sdl


class PaymentRecord(sdl.Entity):
    """One payment_transactions row — /v1/billing/internal/payments/{uid}."""
    payment_intent_id: Optional[str] = None
    amount_cents: Optional[int] = None
    currency: Optional[str] = None
    tokens: Optional[int] = None
    status: Optional[str] = None
    type: Optional[str] = None
    created_at: Optional[Any] = None
    completed_at: Optional[Any] = None
    receipt_url: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _c(cls, d):
        if isinstance(d, dict):
            d["id"] = d.get("payment_intent_id") or d.get("id") or ""
            cents = d.get("amount_cents") or 0
            d.setdefault("title", f"${cents/100:.2f} {(d.get('type') or '').strip()}".strip())
            d.setdefault("kind", "payment")
        return d


class PaymentsResponse(sdl.EntityList[PaymentRecord]):
    pass


class PaymentMethodRecord(sdl.Entity):
    """A saved card — /v1/billing/internal/payment-methods/{uid}."""
    id: Optional[str] = None
    type: Optional[str] = None
    brand: Optional[str] = None
    last4: Optional[str] = None
    exp_month: Optional[int] = None
    exp_year: Optional[int] = None
    is_default: Optional[bool] = None

    @model_validator(mode="before")
    @classmethod
    def _c(cls, d):
        if isinstance(d, dict):
            d["id"] = d.get("id") or ""
            d.setdefault("title", f"{d.get('brand') or d.get('type') or 'card'} ••{d.get('last4') or '????'}")
            d.setdefault("kind", "payment_method")
        return d


class PaymentMethodsResponse(sdl.EntityList[PaymentMethodRecord]):
    pass


class UserLimitsRecord(sdl.Entity):
    """Effective plan + limits — /v1/billing/internal/user-limits/{uid}."""
    plan: Optional[str] = None
    limits: Optional[dict] = None

    @model_validator(mode="before")
    @classmethod
    def _c(cls, d):
        if isinstance(d, dict):
            d.setdefault("id", d.get("plan") or "limits")
            d.setdefault("title", f"{d.get('plan') or 'free'} limits")
            d.setdefault("kind", "user_limits")
        return d


class AgencyRecord(sdl.Entity):
    """An agency (multi-tenant org) — /v1/agencies."""
    agency_id: Optional[str] = None
    display_name: Optional[str] = None
    domain: Optional[str] = None
    settings: Optional[Any] = None
    theme: Optional[Any] = None
    created_at: Optional[Any] = None

    @model_validator(mode="before")
    @classmethod
    def _c(cls, d):
        if isinstance(d, dict):
            d["id"] = d.get("agency_id") or d.get("id") or ""
            d.setdefault("title", d.get("display_name") or d.get("agency_id") or "")
            d.setdefault("kind", "agency")
        return d


class AgenciesResponse(sdl.EntityList[AgencyRecord]):
    pass


class PendingAppRecord(sdl.Entity):
    """A developer_apps row awaiting review — /v1/admin/apps/pending."""
    app_id: Optional[str] = None
    display_name: Optional[str] = None
    short_description: Optional[str] = None
    category: Optional[str] = None
    status: Optional[str] = None
    developer_id: Optional[str] = None
    pricing_model: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _c(cls, d):
        if isinstance(d, dict):
            d["id"] = d.get("app_id") or d.get("id") or ""
            d.setdefault("title", d.get("display_name") or d.get("app_id") or "")
            d.setdefault("kind", "app")
        return d


class PendingAppsResponse(sdl.EntityList[PendingAppRecord]):
    pass


class PendingPayoutRecord(sdl.Entity):
    """A developer_payouts row awaiting action — /v1/admin/payouts/pending."""
    developer_id: Optional[str] = None
    app_id: Optional[str] = None
    amount: Optional[Any] = None
    status: Optional[str] = None
    requested_at: Optional[Any] = None
    admin_note: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _c(cls, d):
        if isinstance(d, dict):
            d["id"] = str(d.get("id") or d.get("payout_id") or "")
            d.setdefault("title", f"payout {d.get('amount') or '?'} ({d.get('status') or '?'})")
            d.setdefault("kind", "payout")
        return d


class PendingPayoutsResponse(sdl.EntityList[PendingPayoutRecord]):
    pass
