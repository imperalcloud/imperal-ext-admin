"""Admin · Developer portal handlers — app review + payout management."""
from __future__ import annotations

import logging

import httpx
from pydantic import BaseModel, Field

from app import (
    ActionResult, REGISTRY_KEY, REGISTRY_URL, _gw_request, chat,
    _resolve_user_by_email, _signal_session_refresh,
)
from models_records import (
    AppReviewReceipt, DeveloperProfileRecord, DeveloperTierReceipt,
    PayoutReviewReceipt,
)

log = logging.getLogger("admin")


# ── Params ───────────────────────────────────────────────────────────────────

class AppReviewParams(BaseModel):
    app_id: str = Field(..., description="App to review")
    action: str = Field(..., description="approve or reject")
    reason: str = Field(default="", description="Rejection reason (required for reject)")


class PayoutReviewParams(BaseModel):
    payout_id: int = Field(..., description="Payout request ID")
    action: str = Field(..., description="approve or reject")
    note: str = Field(default="", description="Admin note")


DEVELOPER_TIERS = ("explorer", "indie", "studio", "partner")


class DeveloperUserParams(BaseModel):
    """Target a user by email or imperal_id."""
    user: str = Field(..., description="Target user: email or imperal_id")


class SetDeveloperTierParams(BaseModel):
    """Set a user's developer tier (admin comp, no charge)."""
    user: str = Field(..., description="Target user: email or imperal_id")
    tier: str = Field(..., description="Developer tier: explorer | indie | studio | partner")


async def _resolve_uid(user: str) -> str | None:
    if "@" in user:
        return await _resolve_user_by_email(user)
    return user


# ── App review ───────────────────────────────────────────────────────────────

@chat.function("review_app", action_type="write", data_model=AppReviewReceipt, description="Approve or reject a developer app submission")
async def review_app(ctx, params: AppReviewParams) -> ActionResult:
    action = params.action.lower()
    app_id = params.app_id

    if action not in ("approve", "reject"):
        return ActionResult.error("action must be 'approve' or 'reject'", retryable=False)

    if action == "reject":
        if not params.reason:
            return ActionResult.error("reason is required when rejecting an app", retryable=False)
        result = await _gw_request("POST", f"/v1/admin/apps/{app_id}/reject", {"reason": params.reason})
        # SDL-symmetric receipt (I-EXT-RECORD-FIELD-NAMING-SYMMETRIC) — mirrors
        # AppReviewReceipt {app_id, action, status, reason, registered}.
        return ActionResult.success(
            data={"app_id": app_id, "action": "reject", "status": result,
                  "reason": params.reason, "registered": False},
            summary=f"App {app_id} rejected: {params.reason}", refresh_panels=["tools"])

    # approve
    result = await _gw_request("POST", f"/v1/admin/apps/{app_id}/approve")

    # Non-critical: register approved app in Registry
    registered = False
    try:
        pending = await _gw_request("GET", "/v1/admin/apps/pending")
        display_name = app_id
        if isinstance(pending, list):
            for entry in pending:
                if entry.get("app_id") == app_id:
                    display_name = entry.get("name", app_id)
                    break
        async with httpx.AsyncClient(timeout=10) as c:
            resp = await c.post(
                f"{REGISTRY_URL}/v1/apps",
                json={"app_id": app_id, "display_name": display_name},
                headers={"x-api-key": REGISTRY_KEY, "Content-Type": "application/json"},
            )
            if resp.status_code in (200, 201, 409):
                registered = True
            else:
                log.warning("Registry registration for %s returned %s", app_id, resp.status_code)
    except Exception as exc:
        log.warning("Registry registration failed for %s (non-critical): %s", app_id, exc)

    return ActionResult.success(
        data={"app_id": app_id, "action": "approve", "status": result,
              "reason": params.reason, "registered": registered},
        summary=f"App {app_id} approved and registered")


# ── Developer tier management ────────────────────────────────────────────────

@chat.function("developer_profile", action_type="read", data_model=DeveloperProfileRecord,
               description="Show a user's developer profile: tier, nickname, apps count, earnings, registration date. tier=None means not a registered developer.")
async def fn_developer_profile(ctx, params: DeveloperUserParams) -> ActionResult:
    uid = await _resolve_uid(params.user)
    if not uid:
        return ActionResult.error(f"User '{params.user}' not found")
    result = await _gw_request("GET", f"/v1/developer/profile?user_id={uid}")
    if isinstance(result, dict) and "error" in result:
        # Gateway 403 = not a registered developer — that is a FACT about the
        # user, not a tool failure; return it as an entity with tier=None.
        if "403" in str(result.get("error", "")):
            return ActionResult.success(
                data={"imperal_id": uid, "tier": None},
                summary=f"{params.user} is not registered as a developer",
            )
        return ActionResult.error(result["error"])
    return ActionResult.success(
        data=result,
        summary=(f"Developer {result.get('nickname') or params.user}: "
                 f"tier {result.get('tier')}, {result.get('apps_count', 0)} apps"),
    )


@chat.function("set_developer_tier", action_type="write", event="user_updated",
               data_model=DeveloperTierReceipt,
               description="Set or change a user's DEVELOPER tier (explorer|indie|studio|partner) without charging — audited admin comp. Grants developer status if the user has none. This is the developer 'group'; it is independent of the RBAC role/category.")
async def fn_set_developer_tier(ctx, params: SetDeveloperTierParams) -> ActionResult:
    tier = params.tier.strip().lower()
    if tier not in DEVELOPER_TIERS:
        return ActionResult.error(
            f"tier must be one of: {', '.join(DEVELOPER_TIERS)}", retryable=False)
    uid = await _resolve_uid(params.user)
    if not uid:
        return ActionResult.error(f"User '{params.user}' not found")
    # ONE machinery: the gateway's audited admin-comp endpoint (writes the
    # tier + UTC cycle dates into user attributes, records WHO comped WHOM in
    # token_ledger, busts the identity cache). No parallel write path here.
    result = await _gw_request("POST", "/v1/admin/developer/tier",
                               {"user_id": uid, "tier": tier})
    if isinstance(result, dict) and "error" in result:
        return ActionResult.error(result["error"])
    await _signal_session_refresh(uid)
    return ActionResult.success(
        data={"imperal_id": uid, "tier": result.get("tier", tier),
              "comped_by": result.get("comped_by", "")},
        summary=f"Developer tier for {params.user} set to {tier}",
        refresh_panels=["tools"],
    )


# ── Payout review ────────────────────────────────────────────────────────────

@chat.function("review_payout", action_type="write", data_model=PayoutReviewReceipt, description="Approve or reject a developer payout request")
async def review_payout(ctx, params: PayoutReviewParams) -> ActionResult:
    action = params.action.lower()
    payout_id = params.payout_id

    if action not in ("approve", "reject"):
        return ActionResult.error("action must be 'approve' or 'reject'", retryable=False)

    result = await _gw_request(
        "POST",
        f"/v1/admin/payouts/{payout_id}/{action}",
        {"note": params.note},
    )
    # SDL-symmetric receipt (I-EXT-RECORD-FIELD-NAMING-SYMMETRIC) — mirrors
    # PayoutReviewReceipt {payout_id, action, note, status}.
    return ActionResult.success(
        data={"payout_id": payout_id, "action": action, "note": params.note,
              "status": result},
        summary=f"Payout {payout_id} {action}d", refresh_panels=["tools"])
