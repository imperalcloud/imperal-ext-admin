# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors.
# Licensed under the AGPL-3.0 License.
"""Admin · Voice handlers — STT/TTS pricing, global master-switch, and per-role
voice access (the ``voice:use`` scope on a role's default_scopes).

Pricing + master write the platform/global billing config via the admin-gated
gateway internal endpoints (mirrors System Pricing). Per-role access PATCHes the
role's default_scopes (cascades to existing members).
"""
from __future__ import annotations

import logging

import httpx
from pydantic import BaseModel, Field

from app import (
    chat, ActionResult, AUTH_GW, AUTH_SERVICE_TOKEN,
    _verify_write_reflected, _gw_request,
)

log = logging.getLogger("admin")

VOICE_SCOPE = "voice:use"


def _acting(ctx) -> str:
    try:
        return str(getattr(getattr(ctx, "user", None), "imperal_id", "") or "")
    except Exception:
        return ""


async def _put_billing(path: str, body: dict, acting: str):
    url = f"{AUTH_GW.rstrip('/')}{path}"
    async with httpx.AsyncClient(timeout=5.0) as client:
        return await client.put(url, json=body, headers={
            "X-Service-Token": AUTH_SERVICE_TOKEN, "X-Acting-User": acting,
        })


class _Receipt(BaseModel):
    action: str = "saved"


# ── Voice pricing (STT + TTS) ─────────────────────────────────────────────

class SaveVoiceCostsParams(BaseModel):
    stt: int = Field(..., ge=0, le=1_000_000, description="Credits charged per voice transcription (STT)")
    speak: int = Field(..., ge=0, le=1_000_000, description="Credits charged per spoken reply synthesis (TTS)")


@chat.function("save_voice_costs", action_type="write",
               event="voice_costs_saved", data_model=_Receipt,
               description="Save the per-action voice costs (STT transcription + TTS spoken reply) to the billing config.")
async def fn_save_voice_costs(ctx, params: SaveVoiceCostsParams) -> ActionResult:
    if not AUTH_GW or not AUTH_SERVICE_TOKEN:
        return ActionResult.error("missing AUTH_GW or AUTH_SERVICE_TOKEN")
    body = {"stt": params.stt, "speak": params.speak}
    try:
        resp = await _put_billing("/v1/internal/billing/voice-costs", body, _acting(ctx))
    except Exception as e:
        return ActionResult.error(f"save HTTP error: {type(e).__name__}: {e}")
    if resp.status_code == 403:
        return ActionResult.error("admin role required to change voice pricing")
    if resp.status_code != 200:
        return ActionResult.error(f"save failed: status={resp.status_code} body={resp.text[:200]}")
    drift = _verify_write_reflected(resp.json(), body)
    if drift:
        return ActionResult.error(drift)
    return ActionResult.success(
        data={**body, "action": "saved"},
        summary=f"Voice pricing saved (STT {params.stt} / TTS {params.speak} cr). Applies within ~1 min.",
        refresh_panels=["tools"],
    )


# ── Global voice master-switch ────────────────────────────────────────────

class SaveVoiceEnabledParams(BaseModel):
    enabled: bool = Field(..., description="Global voice master-switch (off = no voice anywhere; mic hidden)")


@chat.function("save_voice_enabled", action_type="write",
               event="voice_enabled_saved", data_model=_Receipt,
               description="Turn the entire voice feature ON or OFF platform-wide (off hides the mic for everyone).")
async def fn_save_voice_enabled(ctx, params: SaveVoiceEnabledParams) -> ActionResult:
    if not AUTH_GW or not AUTH_SERVICE_TOKEN:
        return ActionResult.error("missing AUTH_GW or AUTH_SERVICE_TOKEN")
    body = {"enabled": bool(params.enabled)}
    try:
        resp = await _put_billing("/v1/internal/billing/voice-enabled", body, _acting(ctx))
    except Exception as e:
        return ActionResult.error(f"save HTTP error: {type(e).__name__}: {e}")
    if resp.status_code == 403:
        return ActionResult.error("admin role required to toggle voice")
    if resp.status_code != 200:
        return ActionResult.error(f"save failed: status={resp.status_code} body={resp.text[:200]}")
    return ActionResult.success(
        data={**body, "action": "saved"},
        summary=("Voice turned ON platform-wide."
                 if params.enabled else
                 "Voice turned OFF platform-wide (mic hidden for everyone)."),
        refresh_panels=["tools"],
    )


# ── Per-role voice access (voice:use scope on default_scopes) ─────────────

CONNECTORS_SCOPE = "connectors:use"


async def _toggle_role_scope(role_id: str, scope: str, enabled: bool, label: str) -> ActionResult:
    """Grant/revoke a feature scope on a role's default_scopes (cascades to members)."""
    roles = await _gw_request("GET", "/v1/roles")
    if not isinstance(roles, list):
        return ActionResult.error("Failed to fetch roles")
    role = next((r for r in roles if r.get("id") == role_id), None)
    if not role:
        return ActionResult.error(f"Role {role_id} not found")
    scopes = set(role.get("default_scopes", []) or [])
    if enabled:
        scopes.add(scope)
    else:
        scopes.discard(scope)
    result = await _gw_request("PATCH", f"/v1/roles/{role_id}?cascade=true",
                               {"default_scopes": sorted(scopes)})
    if isinstance(result, dict) and "error" in result:
        return ActionResult.error(result["error"])
    rname = role.get("display_name") or role.get("name") or role_id
    return ActionResult.success(
        data={"role_id": role_id, "scope": scope, "enabled": enabled, "action": "saved"},
        summary=f"{label} {'enabled' if enabled else 'disabled'} for role '{rname}'.",
        refresh_panels=["tools"],
    )


class SetRoleVoiceParams(BaseModel):
    role_id: str = Field(..., description="Role id (UUID)")
    enabled: bool = Field(..., description="Grant (true) or revoke (false) voice:use for this role")


@chat.function("set_role_voice", action_type="write",
               event="role_voice_set", data_model=_Receipt,
               description="Grant or revoke voice access (the voice:use scope) for an entire role/group.")
async def fn_set_role_voice(ctx, params: SetRoleVoiceParams) -> ActionResult:
    return await _toggle_role_scope(params.role_id, VOICE_SCOPE, params.enabled, "Voice")


class SetRoleConnectorsParams(BaseModel):
    role_id: str = Field(..., description="Role id (UUID)")
    enabled: bool = Field(..., description="Grant (true) or revoke (false) connectors:use for this role")


@chat.function("set_role_connectors", action_type="write",
               event="role_connectors_set", data_model=_Receipt,
               description="Grant or revoke messenger-connector access (the connectors:use scope) for an entire role/group.")
async def fn_set_role_connectors(ctx, params: SetRoleConnectorsParams) -> ActionResult:
    return await _toggle_role_scope(params.role_id, CONNECTORS_SCOPE, params.enabled, "Connector access")


# ── Per-plan feature access (Plan.features voice/connectors) ──────────────

class SetPlanFeatureParams(BaseModel):
    plan_id: str = Field(..., description="Plan id")
    feature: str = Field(..., pattern="^(voice|connectors)$", description="Feature: 'voice' or 'connectors'")
    enabled: bool = Field(..., description="Enable (true) or disable (false) the feature for this plan")


@chat.function("set_plan_feature", action_type="write",
               event="plan_feature_set", data_model=_Receipt,
               description="Enable or disable a feature (voice or connectors) for an entire subscription plan.")
async def fn_set_plan_feature(ctx, params: SetPlanFeatureParams) -> ActionResult:
    if not AUTH_GW or not AUTH_SERVICE_TOKEN:
        return ActionResult.error("missing AUTH_GW or AUTH_SERVICE_TOKEN")
    body = {"plan_id": params.plan_id, "feature": params.feature, "enabled": bool(params.enabled)}
    try:
        resp = await _put_billing("/v1/internal/billing/plan-feature", body, _acting(ctx))
    except Exception as e:
        return ActionResult.error(f"save HTTP error: {type(e).__name__}: {e}")
    if resp.status_code == 403:
        return ActionResult.error("admin role required to change plan features")
    if resp.status_code == 404:
        return ActionResult.error("plan not found")
    if resp.status_code != 200:
        return ActionResult.error(f"save failed: status={resp.status_code} body={resp.text[:200]}")
    return ActionResult.success(
        data={**body, "action": "saved"},
        summary=f"{params.feature} {'enabled' if params.enabled else 'disabled'} for the plan. Applies within ~1 min.",
        refresh_panels=["tools"],
    )
