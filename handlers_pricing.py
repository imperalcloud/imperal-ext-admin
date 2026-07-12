"""Admin · LLM model rate CRUD handlers (Sprint 4).

Calls into auth-gw internal billing endpoints:
  - GET    /v1/internal/billing/model-rates           (list)
  - GET    /v1/internal/billing/model-rate/{model}    (single, used by kernel)
  - PUT    /v1/internal/billing/model-rates/{model}   (upsert)
  - DELETE /v1/internal/billing/model-rates/{model}   (soft-delete)

Service-token auth via app.AUTH_GW + AUTH_SERVICE_TOKEN.
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx
from pydantic import BaseModel, Field

from app import chat, ActionResult, AUTH_GW, AUTH_SERVICE_TOKEN
from models_records import LLMModelRateReceipt

log = logging.getLogger("admin")

VALID_TIERS = ("economy", "standard", "premium")


class SaveLlmModelRateParams(BaseModel):
    """Save (upsert) a single LLM model rate row."""
    model_id: str = Field(
        ..., min_length=1, max_length=50,
        description="Model identifier (e.g. claude-sonnet-4-20250514)",
    )
    tier: str = Field(..., description="economy | standard | premium")
    input_cost_per_1k: float = Field(
        ..., ge=0, le=1000,
        description="Input cost per 1k tokens, USD",
    )
    output_cost_per_1k: float = Field(
        ..., ge=0, le=1000,
        description="Output cost per 1k tokens, USD",
    )
    # VESTIGIAL: nothing in the billing path reads this column — the real
    # per-action platform fee is PER TIER in System Pricing (unified_config
    # billing.platform_fee). Optional + no upper bound: the old le=100 400'd
    # against rows already holding tier-fee-sized values (60/250/2200), which
    # is how the "Input should be less than or equal to 100" add-model error
    # surfaced live (2026-07-12). Omitted from the panel form entirely.
    platform_fee_default: Optional[int] = Field(
        default=None, ge=0,
        description="Deprecated/unused — per-action fees are per-tier in System Pricing.",
    )
    is_available: bool = Field(default=True)


class DeleteLlmModelRateParams(BaseModel):
    """Soft-delete (set is_available=false) a model rate row."""
    model_id: str = Field(..., min_length=1)


# SDL: save/delete_llm_model_rate return a receipt whose runtime keys are
# {model_id, action}. LLMModelRateReceipt mirrors those keys verbatim
# (I-EXT-RECORD-FIELD-NAMING-SYMMETRIC).
@chat.function("save_llm_model_rate", action_type="write",
               event="llm_model_rate_saved",
               data_model=LLMModelRateReceipt,
               description="Save (upsert) an LLM model rate row in llm_model_rates.")
async def fn_save_llm_model_rate(ctx, params: SaveLlmModelRateParams) -> ActionResult:
    if params.tier not in VALID_TIERS:
        return ActionResult.error(
            f"tier must be one of {VALID_TIERS}, got {params.tier!r}"
        )
    if not AUTH_GW or not AUTH_SERVICE_TOKEN:
        return ActionResult.error("missing AUTH_GW or AUTH_SERVICE_TOKEN")

    url = f"{AUTH_GW.rstrip('/')}/v1/internal/billing/model-rates/{params.model_id}"
    body = {
        "tier": params.tier,
        "input_cost_per_1k": params.input_cost_per_1k,
        "output_cost_per_1k": params.output_cost_per_1k,
        "is_available": params.is_available,
    }
    if params.platform_fee_default is not None:
        body["platform_fee_default"] = params.platform_fee_default
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.put(
                url,
                headers={"X-Service-Token": AUTH_SERVICE_TOKEN},
                json=body,
            )
    except Exception as e:
        return ActionResult.error(f"upsert HTTP error: {type(e).__name__}: {e}")

    if resp.status_code != 200:
        return ActionResult.error(
            f"upsert failed: status={resp.status_code} body={resp.text[:200]}"
        )

    action = "saved"
    try:
        action = resp.json().get("action", "saved")
    except Exception:
        pass

    return ActionResult.success(
        data={"model_id": params.model_id, "action": action},
        summary=f"Rate saved for {params.model_id} (tier={params.tier})",
    )


@chat.function("delete_llm_model_rate", action_type="destructive",
               event="llm_model_rate_deleted",
               data_model=LLMModelRateReceipt,
               description="Soft-delete (mark unavailable) an LLM model rate row.")
async def fn_delete_llm_model_rate(ctx, params: DeleteLlmModelRateParams) -> ActionResult:
    if not AUTH_GW or not AUTH_SERVICE_TOKEN:
        return ActionResult.error("missing AUTH_GW or AUTH_SERVICE_TOKEN")

    url = f"{AUTH_GW.rstrip('/')}/v1/internal/billing/model-rates/{params.model_id}"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.delete(
                url, headers={"X-Service-Token": AUTH_SERVICE_TOKEN},
            )
    except Exception as e:
        return ActionResult.error(f"delete HTTP error: {type(e).__name__}: {e}")

    if resp.status_code == 404:
        return ActionResult.error(f"model {params.model_id} not found")
    if resp.status_code != 200:
        return ActionResult.error(
            f"delete failed: status={resp.status_code} body={resp.text[:200]}"
        )

    return ActionResult.success(
        data={"model_id": params.model_id, "action": "softdeleted"},
        summary=f"Rate disabled for {params.model_id}",
    )
