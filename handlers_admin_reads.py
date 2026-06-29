# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors.
# Licensed under the AGPL-3.0 License.
"""Admin · READ tools — closing the Webbee visibility gaps so the admin can see
the FULL system: a user's payment history + saved cards + limits, the agencies,
and the review queues. All net-new (no prior tool covered these) and read-only.
Every endpoint is keyed by imperal_id where per-user (the canonical billing id)."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app import chat, ActionResult, EmptyParams, _gw_request
# Single source for imperal_id coercion (imp_u_* or email -> imp_u_*).
from handlers_billing import _normalize_to_imperal_id
from models_admin_reads import (
    PaymentsResponse, PaymentMethodsResponse, UserLimitsRecord,
    AgenciesResponse, PendingAppsResponse, PendingPayoutsResponse,
)


class _UserIdParam(BaseModel):
    user_id: str = Field(description="Canonical imperal_id (imp_u_XXXXXXXX) or the user's email.")


def _aslist(r) -> list:
    if isinstance(r, list):
        return r
    if isinstance(r, dict) and "error" not in r:
        return r.get("items") or []
    return []


@chat.function("get_user_payments", action_type="read", data_model=PaymentsResponse,
               description="A user's payment history (subscriptions + token top-ups): amount, status, type, date, and receipt link.")
async def fn_get_user_payments(ctx, params: _UserIdParam) -> ActionResult:
    uid, err = await _normalize_to_imperal_id(params.user_id)
    if err:
        return ActionResult.error(err)
    items = _aslist(await _gw_request("GET", f"/v1/billing/internal/payments/{uid}"))
    return ActionResult.success(data={"items": items, "total": len(items)},
                                summary=f"{len(items)} payment(s) for {uid}")


@chat.function("get_user_payment_methods", action_type="read", data_model=PaymentMethodsResponse,
               description="A user's saved payment methods (cards): brand, last4, expiry, default flag.")
async def fn_get_user_payment_methods(ctx, params: _UserIdParam) -> ActionResult:
    uid, err = await _normalize_to_imperal_id(params.user_id)
    if err:
        return ActionResult.error(err)
    items = _aslist(await _gw_request("GET", f"/v1/billing/internal/payment-methods/{uid}"))
    return ActionResult.success(data={"items": items, "total": len(items)},
                                summary=f"{len(items)} saved card(s) for {uid}")


@chat.function("get_user_limits", action_type="read", data_model=UserLimitsRecord,
               description="A user's effective subscription plan + usage limits.")
async def fn_get_user_limits(ctx, params: _UserIdParam) -> ActionResult:
    uid, err = await _normalize_to_imperal_id(params.user_id)
    if err:
        return ActionResult.error(err)
    r = await _gw_request("GET", f"/v1/billing/internal/user-limits/{uid}")
    d = r if isinstance(r, dict) and "error" not in r else {}
    return ActionResult.success(data={"plan": d.get("plan", "free"), "limits": d.get("limits", {})},
                                summary=f"{uid}: {d.get('plan', 'free')} plan limits")


@chat.function("list_agencies", action_type="read", data_model=AgenciesResponse,
               description="List all agencies (multi-tenant orgs): id, display name, domain.")
async def fn_list_agencies(ctx, params: EmptyParams) -> ActionResult:
    items = _aslist(await _gw_request("GET", "/v1/agencies"))
    return ActionResult.success(data={"items": items, "total": len(items)},
                                summary=f"{len(items)} agencies")


@chat.function("list_pending_apps", action_type="read", data_model=PendingAppsResponse,
               description="Marketplace apps awaiting admin review (status=pending_review) — the approve/reject queue.")
async def fn_list_pending_apps(ctx, params: EmptyParams) -> ActionResult:
    items = _aslist(await _gw_request("GET", "/v1/admin/apps/pending"))
    return ActionResult.success(data={"items": items, "total": len(items)},
                                summary=f"{len(items)} app(s) pending review")


@chat.function("list_pending_payouts", action_type="read", data_model=PendingPayoutsResponse,
               description="Developer payout requests awaiting admin action (status=pending).")
async def fn_list_pending_payouts(ctx, params: EmptyParams) -> ActionResult:
    items = _aslist(await _gw_request("GET", "/v1/admin/payouts/pending"))
    return ActionResult.success(data={"items": items, "total": len(items)},
                                summary=f"{len(items)} pending payout(s)")
