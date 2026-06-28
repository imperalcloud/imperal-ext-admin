# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors.
# Licensed under the AGPL-3.0 License.
"""SDL entity records — BILLING (admin-side) domain.

Federal I-EXT-RECORD-FIELD-NAMING-SYMMETRIC: field names mirror the ACTUAL
runtime dict keys (verified against handlers_billing.py). 100% SDL — list
returns are real ``sdl.EntityList[T]``; billing_health is a real ``sdl.Entity``.

User wallet records (UserBalanceRecord / UserBalancesResponse) live in
models_users.py with the rest of the user-keyed entities.
"""
from __future__ import annotations

from typing import Optional, Any
from pydantic import model_validator

from imperal_sdk import sdl


# --- billing plans ---

class PlanRecord(sdl.Entity):
    """A single billing plan as a canonical SDL entity (kind='plan').

    billing_overview builds each plan item with EXACTLY these keys (verified vs
    handlers_billing.fn_billing_overview ``plan_summary``):
    {name, price, interval, ai_tokens, tool_calls}. id=title=name."""
    name: Optional[str] = None
    price: Optional[Any] = None
    interval: Optional[str] = None
    ai_tokens: Optional[Any] = None
    tool_calls: Optional[Any] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data["id"] = data.get("id") or data.get("name") or ""
            data.setdefault("title", data.get("name") or "")
            data.setdefault("kind", "plan")
        return data


class BillingOverviewResponse(sdl.EntityList[PlanRecord]):
    """billing_overview return shape — a REAL sdl.EntityList[PlanRecord] whose
    items are the plans, PLUS the platform scalar summary carried as extra typed
    fields (EntityList is a pydantic BaseModel, so additive fields are allowed).

    The handler must return:
        data={"items": [...plan dicts...], "total": <plans_count>,
              "plans_count": <int>, "wallets_active": <int>,
              "stream_events_total": <int>}
    NO legacy {plans:[dict],...} wrapper. (``plans_count`` and ``total`` are the
    same count; keep both for backward field-name continuity.)"""
    plans_count: int = 0
    wallets_active: int = 0
    stream_events_total: int = 0


# --- billing health ---

class BillingHealthRecord(sdl.Entity):
    """billing_health return shape — a single billing-health entity
    (kind='billinghealth').

    Field names match the REAL runtime keys (verified vs
    handlers_billing.fn_billing_health): {stream_length, first_entry_id,
    last_entry_id, consumer_groups, pending_total, consumers, healthy}. The old
    BillingHealthResponse keys (redis / lua_scripts / wallets / holds / issues)
    were PHANTOM and are removed."""
    stream_length: Optional[int] = None
    first_entry_id: Optional[Any] = None
    last_entry_id: Optional[Any] = None
    consumer_groups: Optional[list] = None
    pending_total: Optional[int] = None
    consumers: Optional[list] = None
    healthy: Optional[bool] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data.setdefault("id", "billing_health")
            data.setdefault("title", "Billing health")
            data.setdefault("kind", "billinghealth")
            if data.get("healthy") is not None:
                data.setdefault("status", "healthy" if data["healthy"] else "degraded")
        return data


# Backward-compatible alias: handlers/import sites referencing the old name keep
# working, now resolving to the SDL entity. 100% SDL — no plain BaseModel.
BillingHealthResponse = BillingHealthRecord


# --- payment provider config ---

class PaymentConfigRecord(sdl.Entity):
    """payment_config_get return shape — a single payment-config entity
    (kind='paymentconfig').

    Field names match the REAL runtime keys verbatim (verified vs
    handlers_payment.fn_payment_config_get). id = title = 'payment_config'."""
    configured: Optional[Any] = None
    enabled: Optional[Any] = None
    mode: Optional[Any] = None
    source: Optional[Any] = None
    secret_key_masked: Optional[Any] = None
    publishable_key_masked: Optional[Any] = None
    has_webhook_secret: Optional[Any] = None
    account: Optional[Any] = None
    balance: Optional[Any] = None
    webhook: Optional[Any] = None
    recent_payments: Optional[Any] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data.setdefault("id", "payment_config")
            data.setdefault("title", "payment_config")
            data.setdefault("kind", "paymentconfig")
        return data


class PaymentTestResultRecord(sdl.Entity):
    """payment_test_connection return shape — a single connection-test entity
    (kind='paymenttest').

    Field names match the REAL runtime keys verbatim (verified vs
    handlers_payment.fn_payment_test_connection): {connected, currency, amount}.
    id = title = 'payment_test'."""
    connected: Optional[Any] = None
    currency: Optional[str] = None
    amount: Optional[Any] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data.setdefault("id", "payment_test")
            data.setdefault("title", "payment_test")
            data.setdefault("kind", "paymenttest")
        return data
