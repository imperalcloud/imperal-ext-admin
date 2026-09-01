"""Admin · Developer portal handlers — app review + payout management."""
from __future__ import annotations

import logging

from typing import Optional

import httpx
from imperal_sdk._shared_http import shared_http
from pydantic import BaseModel, Field

from app import (
    ActionResult, REGISTRY_KEY, REGISTRY_URL, _gw_request, chat,
    _resolve_user_by_email, _signal_session_refresh,
)
from models_records import (
    AppReviewReceipt, DeveloperProfileRecord, DeveloperTierReceipt,
    PayoutReviewReceipt, PendingAppRecord,
)

log = logging.getLogger("admin")


# ── Params ───────────────────────────────────────────────────────────────────

class AppReviewParams(BaseModel):
    app_id: str = Field(..., description="App to review")
    action: str = Field(..., description="approve or reject")
    reason: str = Field(default="", description="Rejection reason (required for reject)")


class BulkAppReviewParams(BaseModel):
    app_ids: list[str] = Field(default_factory=list, description="List of app IDs to review")
    message_ids: Optional[list[str]] = Field(default=None, description="Injected list of IDs from UI bulk actions")
    action: str = Field(..., description="approve or reject")
    reason: str = Field(default="", description="Rejection reason (required for reject)")


class GetAppDetailsParams(BaseModel):
    app_id: str = Field(..., description="App ID to fetch full details for")


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

@chat.function("review_app", action_type="write", event="admin.app_reviewed", effects=["update:app_review"], data_model=AppReviewReceipt, description="Approve or reject a developer app submission")
async def review_app(ctx, params: AppReviewParams) -> ActionResult:
    """Approve or reject a developer app submission"""
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
        async with shared_http(timeout=10) as c:
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
        summary=f"App {app_id} approved and registered",
        # Without this, ActionResult refreshes ALL panels by default (see
        # imperal_sdk ActionResult.success docstring) — that's what made the
        # sidebar spin AND the whole center reload on Approve, while Reject
        # (which already scoped this) only ever refreshed the App Review
        # table itself. Scoping approve identically fixes both symptoms.
        refresh_panels=["tools"])


@chat.function("bulk_review_apps", action_type="write", event="admin.bulk_apps_reviewed", effects=["update:app_review"], description="Bulk approve or reject multiple developer app submissions at once")
async def bulk_review_apps(ctx, params: BulkAppReviewParams) -> ActionResult:
    """Bulk approve or reject multiple developer app submissions at once."""
    action = params.action.lower()
    if action not in ("approve", "reject"):
        return ActionResult.error("action must be 'approve' or 'reject'", retryable=False)
    if action == "reject" and not params.reason:
        return ActionResult.error("reason is required when rejecting apps", retryable=False)

    results = []
    success_count = 0
    fail_count = 0

    target_ids = params.app_ids or params.message_ids or []
    if not target_ids:
        return ActionResult.error("No apps selected for bulk review", retryable=False)

    for app_id in target_ids:
        app_id = app_id.strip()
        if not app_id:
            continue
        try:
            if action == "reject":
                res = await _gw_request("POST", f"/v1/admin/apps/{app_id}/reject", {"reason": params.reason})
                results.append({"app_id": app_id, "status": "rejected", "ok": True})
                success_count += 1
            else:
                res = await _gw_request("POST", f"/v1/admin/apps/{app_id}/approve")
                # Non-critical registry sync
                try:
                    async with shared_http(timeout=5) as c:
                        await c.post(
                            f"{REGISTRY_URL}/v1/apps",
                            json={"app_id": app_id, "display_name": app_id},
                            headers={"x-api-key": REGISTRY_KEY, "Content-Type": "application/json"},
                        )
                except Exception:
                    pass
                results.append({"app_id": app_id, "status": "approved", "ok": True})
                success_count += 1
        except Exception as exc:
            results.append({"app_id": app_id, "status": "error", "error": str(exc), "ok": False})
            fail_count += 1

    return ActionResult.success(
        data={"action": action, "results": results, "total": len(target_ids),
              "succeeded": success_count, "failed": fail_count},
        summary=f"Bulk {action} completed: {success_count} succeeded, {fail_count} failed",
        refresh_panels=["tools"],
    )


@chat.function("get_app_review_details", action_type="read", data_model=PendingAppRecord, description="Get full details (manifest, tools, description, pricing, git_url) of any pending or reviewed app")
async def get_app_review_details(ctx, params: GetAppDetailsParams) -> ActionResult[PendingAppRecord]:
    """Get full details of a specific pending or reviewed app."""
    app_id = params.app_id.strip()
    if not app_id:
        return ActionResult.error("app_id is required")

    pending = await _gw_request("GET", "/v1/admin/apps/pending")
    items = pending if isinstance(pending, list) else pending.get("items", [])
    for entry in items:
        if entry.get("app_id") == app_id:
            return ActionResult.success(
                data=entry,
                summary=f"Details for pending app '{entry.get('display_name') or app_id}'",
            )

    # Fallback to general app details from gateway if available
    try:
        app_data = await _gw_request("GET", f"/v1/apps/{app_id}")
        if isinstance(app_data, dict) and "error" not in app_data:
            return ActionResult.success(data=app_data, summary=f"Details for app '{app_id}'")
    except Exception:
        pass

    return ActionResult.error(f"App '{app_id}' not found in pending review queue")


# ── Developer tier management ────────────────────────────────────────────────

@chat.function("developer_profile", action_type="read", data_model=DeveloperProfileRecord,
               description="Show a user's developer profile: tier, nickname, apps count, earnings, registration date. tier=None means not a registered developer.")
async def fn_developer_profile(ctx, params: DeveloperUserParams) -> ActionResult:
    """Show a user's developer profile: tier, nickname, apps count, earnings, registration date. tier=None means not a registered developer."""
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


@chat.function("set_developer_tier", action_type="write", effects=["update:developer_tier"], event="user_updated",
               data_model=DeveloperTierReceipt,
               description="Set or change a user's DEVELOPER tier (explorer|indie|studio|partner) without charging — audited admin comp. Grants developer status if the user has none. This is the developer 'group'; it is independent of the RBAC role/category.")
async def fn_set_developer_tier(ctx, params: SetDeveloperTierParams) -> ActionResult:
    """Set or change a user's DEVELOPER tier (explorer|indie|studio|partner) without charging — audited admin comp. Grants developer status if the user has none. This is the developer 'group'; it is independent of the RBAC role/category."""
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

@chat.function("review_payout", action_type="write", event="admin.payout_reviewed", effects=["update:payout_review"], data_model=PayoutReviewReceipt, description="Approve or reject a developer payout request")
async def review_payout(ctx, params: PayoutReviewParams) -> ActionResult:
    """Approve or reject a developer payout request"""
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
