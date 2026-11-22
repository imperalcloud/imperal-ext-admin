# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors.
# Licensed under the AGPL-3.0 License.
"""Admin · Voice handlers — the provider of each voice function, STT/TTS pricing,
global master-switch, and per-role
voice access (the ``voice:use`` scope on a role's default_scopes).

Pricing + master write the platform/global billing config via the admin-gated
gateway internal endpoints (mirrors System Pricing). Per-role access PATCHes the
role's default_scopes (cascades to existing members).
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from app import (
    chat, ActionResult, AUTH_GW, AUTH_SERVICE_TOKEN,
    _verify_write_reflected, _gw_request, _admin_put, _admin_put_checked,
    _acting,
)

log = logging.getLogger("admin")

VOICE_SCOPE = "voice:use"


class _Receipt(BaseModel):
    action: str = "saved"


# ── Voice pricing (STT + TTS) ─────────────────────────────────────────────

class SaveVoiceCostsParams(BaseModel):
    stt: int = Field(..., ge=0, le=1_000_000, description="Credits charged per voice transcription (STT)")
    speak: int = Field(..., ge=0, le=1_000_000, description="Credits charged per spoken reply synthesis (TTS)")


@chat.function("save_voice_costs", action_type="write", effects=["update:voice_costs"],
               event="voice_costs_saved", data_model=_Receipt,
               description="Save the per-action voice costs (STT transcription + TTS spoken reply) to the billing config.")
async def fn_save_voice_costs(ctx, params: SaveVoiceCostsParams) -> ActionResult:
    """Save the per-action voice costs (STT transcription + TTS spoken reply) to the billing config."""
    if not AUTH_GW or not AUTH_SERVICE_TOKEN:
        return ActionResult.error("missing AUTH_GW or AUTH_SERVICE_TOKEN")
    body = {"stt": params.stt, "speak": params.speak}
    payload, error = await _admin_put_checked(
        "/v1/internal/billing/voice-costs",
        body,
        acting=_acting(ctx),
        forbidden_message="admin role required to change voice pricing",
    )
    if error:
        return ActionResult.error(error)
    return ActionResult.success(
        data={**body, "action": "saved"},
        summary=f"Voice pricing saved (STT {params.stt} / TTS {params.speak} cr). Applies within ~1 min.",
        refresh_panels=["tools"],
    )


# ── Voice provider (per function: format, address, key, model, voices) ───

class SaveVoiceProviderParams(BaseModel):
    function: str = Field(..., pattern="^(stt|tts|speechify)$",
                          description="Voice function: 'stt' (speech to text), 'tts' (text to speech), 'speechify' (the model that rewrites an answer for speaking)")
    api: str = Field(default="openai", pattern="^(openai|gemini)$",
                     description="Provider format: 'openai' (any OpenAI-compatible API) or 'gemini' (the Gemini API)")
    base_url: str = Field(default="", description="Provider base URL (https). Blank = the format's own address")
    api_key: str = Field(default="", description="Provider API key (write-only, kept in Vault). Blank = keep the saved key")
    clear_key: bool = Field(default=False, description="Remove the saved key of this function")
    model: str = Field(default="", description="Model id for this function")
    custom_model: str = Field(default="", description="A model id typed by hand; overrides 'model' when given")
    voices: list[str] = Field(default_factory=list, description="tts only: the voices users may choose. Empty = the format's own list")
    default_voice: str = Field(default="", description="tts only: the voice used when a user has chosen none")
    style: str | None = Field(default=None, description="tts only: the speaking style sent to the provider")


@chat.function("save_voice_provider", action_type="write", effects=["update:voice_provider"],
               event="voice_provider_saved", data_model=_Receipt,
               description="Save the provider of one voice function (speech to text, text to speech, or the spoken-form model): "
                           "its format (OpenAI-compatible or Gemini), base URL, API key, model and - for text to speech - voices and style.")
async def fn_save_voice_provider(ctx, params: SaveVoiceProviderParams) -> ActionResult:
    """Save the provider of one voice function. The key goes to the gateway, which keeps it in Vault; it is never echoed."""
    if not AUTH_GW or not AUTH_SERVICE_TOKEN:
        return ActionResult.error("missing AUTH_GW or AUTH_SERVICE_TOKEN")
    fn = params.function
    section: dict = {
        "api": params.api,
        "base_url": params.base_url.strip(),
        "model": (params.custom_model or params.model).strip(),
    }
    if params.api_key.strip() and "\u2022" not in params.api_key:
        section["api_key"] = params.api_key.strip()
    if params.clear_key:
        section["clear_key"] = True
    if fn == "tts":
        section["voices"] = [v.strip() for v in params.voices if v and v.strip()]
        if params.default_voice.strip() in section["voices"] or not section["voices"]:
            section["default_voice"] = params.default_voice.strip()
        if params.style is not None:
            section["style"] = params.style
    try:
        resp = await _admin_put("/v1/internal/billing/voice-config", {fn: section}, _acting(ctx), timeout=15.0)
    except Exception as e:
        return ActionResult.error(f"save HTTP error: {type(e).__name__}: {e}")
    if resp.status_code == 403:
        return ActionResult.error("admin role required to change the voice provider")
    if resp.status_code == 503:
        return ActionResult.error("the key store (Vault) is unavailable - nothing was saved")
    if resp.status_code != 200:
        return ActionResult.error(f"save failed: status={resp.status_code} body={resp.text[:300]}")
    try:
        saved = (resp.json() or {}).get(fn) or {}
    except Exception as e:
        return ActionResult.error(f"save failed: non-JSON reply: {type(e).__name__}: {e}")
    if saved.get("api") != section["api"] or (section["model"] and saved.get("model") != section["model"]):
        return ActionResult.error(
            f"the gateway did not reflect the save: asked {section['api']}/{section['model']}, "
            f"got {saved.get('api')}/{saved.get('model')}")
    key_state = "key set" if saved.get("key_set") else "NO KEY - the function will not work until a key is saved"
    return ActionResult.success(
        data={"function": fn, "api": saved.get("api"), "model": saved.get("model"),
              "base_url": saved.get("base_url"), "key_set": bool(saved.get("key_set")), "action": "saved"},
        summary=f"Voice {fn} provider saved: {saved.get('api')} / {saved.get('model')} ({key_state}).",
        refresh_panels=["tools"],
    )


# ── Global voice master-switch ────────────────────────────────────────────

class SaveVoiceEnabledParams(BaseModel):
    enabled: bool = Field(..., description="Global voice master-switch (off = no voice anywhere; mic hidden)")


@chat.function("save_voice_enabled", action_type="write", effects=["update:voice_settings"],
               event="voice_enabled_saved", data_model=_Receipt,
               description="Turn the entire voice feature ON or OFF platform-wide (off hides the mic for everyone).")
async def fn_save_voice_enabled(ctx, params: SaveVoiceEnabledParams) -> ActionResult:
    """Turn the entire voice feature ON or OFF platform-wide (off hides the mic for everyone)."""
    if not AUTH_GW or not AUTH_SERVICE_TOKEN:
        return ActionResult.error("missing AUTH_GW or AUTH_SERVICE_TOKEN")
    body = {"enabled": bool(params.enabled)}
    try:
        resp = await _admin_put("/v1/internal/billing/voice-enabled", body, _acting(ctx))
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
CONNECTIONS_SCOPE = "connections:use"


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


@chat.function("set_role_voice", action_type="write", effects=["update:role_voice"],
               event="role_voice_set", data_model=_Receipt,
               description="Grant or revoke voice access (the voice:use scope) for an entire role/group.")
async def fn_set_role_voice(ctx, params: SetRoleVoiceParams) -> ActionResult:
    """Grant or revoke voice access (the voice:use scope) for an entire role/group."""
    return await _toggle_role_scope(params.role_id, VOICE_SCOPE, params.enabled, "Voice")


class SetRoleConnectorsParams(BaseModel):
    role_id: str = Field(..., description="Role id (UUID)")
    enabled: bool = Field(..., description="Grant (true) or revoke (false) connectors:use for this role")


@chat.function("set_role_connectors", action_type="write", effects=["update:role_connectors"],
               event="role_connectors_set", data_model=_Receipt,
               description="Grant or revoke messenger-connector access (the connectors:use scope) for an entire role/group.")
async def fn_set_role_connectors(ctx, params: SetRoleConnectorsParams) -> ActionResult:
    """Grant or revoke messenger-connector access (the connectors:use scope) for an entire role/group."""
    return await _toggle_role_scope(params.role_id, CONNECTORS_SCOPE, params.enabled, "Connector access")


class SetRoleConnectionsParams(BaseModel):
    role_id: str = Field(..., description="Role id (UUID)")
    enabled: bool = Field(..., description="Grant (true) or revoke (false) connections:use for this role")


@chat.function("set_role_connections", action_type="write", effects=["update:role_connections"],
               event="role_connections_set", data_model=_Receipt,
               description="Grant or revoke Connections access (the connections:use scope — a user's own SSH/MCP targets) for an entire role/group.")
async def fn_set_role_connections(ctx, params: SetRoleConnectionsParams) -> ActionResult:
    """Grant or revoke Connections access (the connections:use scope — a user's own SSH/MCP targets) for an entire role/group."""
    return await _toggle_role_scope(params.role_id, CONNECTIONS_SCOPE, params.enabled, "Connections access")


# ── Per-plan feature access (Plan.features voice/connectors) ──────────────

class SetPlanFeatureParams(BaseModel):
    plan_id: str = Field(..., description="Plan id")
    feature: str = Field(..., pattern="^(voice|connectors|coding|connections|file_reader)$",
                         description="Feature: 'voice', 'connectors', 'coding' (Webbee Code), 'connections' (external MCP/SSH targets), or 'file_reader' (document ingestion)")
    enabled: bool = Field(..., description="Enable (true) or disable (false) the feature for this plan")


@chat.function("set_plan_feature", action_type="write", effects=["update:plan_feature"],
               event="plan_feature_set", data_model=_Receipt,
               description="Enable or disable a feature (voice, connectors, coding/Webbee Code, or connections/external MCP+SSH) for an entire subscription plan.")
async def fn_set_plan_feature(ctx, params: SetPlanFeatureParams) -> ActionResult:
    """Enable or disable a feature (voice, connectors, coding/Webbee Code, or connections/external MCP+SSH) for an entire subscription plan."""
    if not AUTH_GW or not AUTH_SERVICE_TOKEN:
        return ActionResult.error("missing AUTH_GW or AUTH_SERVICE_TOKEN")
    body = {"plan_id": params.plan_id, "feature": params.feature, "enabled": bool(params.enabled)}
    try:
        resp = await _admin_put("/v1/internal/billing/plan-feature", body, _acting(ctx))
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
