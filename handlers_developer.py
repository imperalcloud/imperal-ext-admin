"""Admin · Developer portal handlers — app review + payout management."""
from __future__ import annotations

import logging

import httpx
from pydantic import BaseModel, Field

from app import ActionResult, REGISTRY_KEY, REGISTRY_URL, _gw_request, chat

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


# ── App review ───────────────────────────────────────────────────────────────

@chat.function("review_app", action_type="write", description="Approve or reject a developer app submission")
async def review_app(ctx, params: AppReviewParams) -> ActionResult:
    action = params.action.lower()
    app_id = params.app_id

    if action not in ("approve", "reject"):
        return ActionResult.error("action must be 'approve' or 'reject'", retryable=False)

    if action == "reject":
        if not params.reason:
            return ActionResult.error("reason is required when rejecting an app", retryable=False)
        result = await _gw_request("POST", f"/v1/admin/apps/{app_id}/reject", {"reason": params.reason})
        return ActionResult.success(result, summary=f"App {app_id} rejected: {params.reason}", refresh_panels=["tools"])

    # approve
    result = await _gw_request("POST", f"/v1/admin/apps/{app_id}/approve")

    # Non-critical: register approved app in Registry
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
            if resp.status_code not in (200, 201, 409):
                log.warning("Registry registration for %s returned %s", app_id, resp.status_code)
    except Exception as exc:
        log.warning("Registry registration failed for %s (non-critical): %s", app_id, exc)

    return ActionResult.success(result, summary=f"App {app_id} approved and registered")


# ── Payout review ────────────────────────────────────────────────────────────

@chat.function("review_payout", action_type="write", description="Approve or reject a developer payout request")
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
    return ActionResult.success(result, summary=f"Payout {payout_id} {action}d", refresh_panels=["tools"])
