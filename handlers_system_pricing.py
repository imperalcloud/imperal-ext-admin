# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors.
# Licensed under the AGPL-3.0 License.
"""Admin · System Pricing handlers — edit per-tier platform fee + $→credit rate.

Writes the platform/global unified_config via the admin-gated gateway endpoints:
  PUT /v1/internal/billing/platform-fees   (role=admin via X-Acting-User)
  PUT /v1/internal/billing/token-rate      (role=admin via X-Acting-User)
"""
from __future__ import annotations

import logging

import httpx
from pydantic import BaseModel, Field

from app import chat, ActionResult, AUTH_GW, AUTH_SERVICE_TOKEN, _verify_write_reflected
from models_records import PlatformFeeReceipt, TokenRateReceipt, CategoryDefaultsReceipt

log = logging.getLogger("admin")


def _acting(ctx) -> str:
    try:
        return str(getattr(getattr(ctx, "user", None), "imperal_id", "") or "")
    except Exception:
        return ""


class SavePlatformFeesParams(BaseModel):
    economy: int = Field(..., ge=0, le=100_000, description="Economy tier platform fee (credits)")
    standard: int = Field(..., ge=0, le=100_000, description="Standard tier platform fee (credits)")
    premium: int = Field(..., ge=0, le=100_000, description="Premium tier platform fee (credits)")


class SaveTokenRateParams(BaseModel):
    token_rate: int = Field(..., ge=1, le=1_000_000, description="Credits per $1 (e.g. 1000)")


@chat.function("save_platform_fees", action_type="write",
               event="platform_fees_saved", data_model=PlatformFeeReceipt,
               description="Save per-tier platform fees (economy/standard/premium) to the billing config.")
async def fn_save_platform_fees(ctx, params: SavePlatformFeesParams) -> ActionResult:
    if not AUTH_GW or not AUTH_SERVICE_TOKEN:
        return ActionResult.error("missing AUTH_GW or AUTH_SERVICE_TOKEN")
    url = f"{AUTH_GW.rstrip('/')}/v1/internal/billing/platform-fees"
    body = {"economy": params.economy, "standard": params.standard, "premium": params.premium}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.put(url, json=body, headers={
                "X-Service-Token": AUTH_SERVICE_TOKEN, "X-Acting-User": _acting(ctx),
            })
    except Exception as e:
        return ActionResult.error(f"save HTTP error: {type(e).__name__}: {e}")
    if resp.status_code == 403:
        return ActionResult.error("admin role required to change platform fees")
    if resp.status_code != 200:
        return ActionResult.error(f"save failed: status={resp.status_code} body={resp.text[:200]}")
    drift = _verify_write_reflected(resp.json(), body)
    if drift:
        return ActionResult.error(drift)
    return ActionResult.success(
        data={**body, "action": "saved"},
        summary=f"Platform fees saved (economy {params.economy} / standard {params.standard} / premium {params.premium} cr). Applies within ~1 min.",
        refresh_panels=["tools"],
    )


@chat.function("save_token_rate", action_type="write",
               event="token_rate_saved", data_model=TokenRateReceipt,
               description="Save the $-to-credit conversion rate (credits per $1) to the billing config.")
async def fn_save_token_rate(ctx, params: SaveTokenRateParams) -> ActionResult:
    if not AUTH_GW or not AUTH_SERVICE_TOKEN:
        return ActionResult.error("missing AUTH_GW or AUTH_SERVICE_TOKEN")
    url = f"{AUTH_GW.rstrip('/')}/v1/internal/billing/token-rate"
    body = {"token_rate": params.token_rate}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.put(url, json=body, headers={
                "X-Service-Token": AUTH_SERVICE_TOKEN, "X-Acting-User": _acting(ctx),
            })
    except Exception as e:
        return ActionResult.error(f"save HTTP error: {type(e).__name__}: {e}")
    if resp.status_code == 403:
        return ActionResult.error("admin role required to change the credit rate")
    if resp.status_code != 200:
        return ActionResult.error(f"save failed: status={resp.status_code} body={resp.text[:200]}")
    drift = _verify_write_reflected(resp.json(), body)
    if drift:
        return ActionResult.error(drift)
    return ActionResult.success(
        data={**body, "action": "saved"},
        summary=f"Credit rate saved: $1 = {params.token_rate} credits. Applies within ~1 min.",
        refresh_panels=["tools"],
    )


class SaveCategoryDefaultsParams(BaseModel):
    read: int = Field(..., ge=0, le=100_000, description="Default base price for READ actions (credits)")
    write: int = Field(..., ge=0, le=100_000, description="Default base price for WRITE actions (credits)")
    destructive: int = Field(..., ge=0, le=100_000, description="Default base price for DESTRUCTIVE actions (credits)")


@chat.function("save_category_defaults", action_type="write",
               event="category_defaults_saved", data_model=CategoryDefaultsReceipt,
               description="Save the default per-action base prices (read/write/destructive) charged when "
                           "an extension function has no explicit price, to the billing config.")
async def fn_save_category_defaults(ctx, params: SaveCategoryDefaultsParams) -> ActionResult:
    if not AUTH_GW or not AUTH_SERVICE_TOKEN:
        return ActionResult.error("missing AUTH_GW or AUTH_SERVICE_TOKEN")
    url = f"{AUTH_GW.rstrip('/')}/v1/internal/billing/category-defaults"
    body = {"read": params.read, "write": params.write, "destructive": params.destructive}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.put(url, json=body, headers={
                "X-Service-Token": AUTH_SERVICE_TOKEN, "X-Acting-User": _acting(ctx),
            })
    except Exception as e:
        return ActionResult.error(f"save HTTP error: {type(e).__name__}: {e}")
    if resp.status_code == 403:
        return ActionResult.error("admin role required to change default function prices")
    if resp.status_code != 200:
        return ActionResult.error(f"save failed: status={resp.status_code} body={resp.text[:200]}")
    drift = _verify_write_reflected(resp.json(), body)
    if drift:
        return ActionResult.error(drift)
    return ActionResult.success(
        data={**body, "action": "saved"},
        summary=f"Default function prices saved (read {params.read} / write {params.write} / "
                f"destructive {params.destructive} cr). Applies within ~1 min.",
        refresh_panels=["tools"],
    )
