"""Admin · Extension settings save handlers (per-section).

Each handler saves one settings section to Registry via PUT /v1/apps/{aid}/settings.
Used by DUI Forms in panels_ext_settings*.py.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from app import (
    chat, ActionResult, _admin_put, _registry_get, _registry_put, _resolve_app_id,
    AUTH_GW, AUTH_SERVICE_TOKEN,
)
from models_records import ExtSettingsReceipt


# ── Models ─────────────────────────────────────────────────────────── #

class SaveGeneralParams(BaseModel):
    app_id: str = Field(description="Extension app_id")
    display_name: str = Field(default="", description="Display name")
    status: str = Field(default="active", description="active or suspended")


class SaveModelsParams(BaseModel):
    app_id: str = Field(description="Extension app_id")
    primary_model: str = Field(default="", description="Primary model")
    intake_model: str = Field(default="", description="Intake model")
    analysis_model: str = Field(default="", description="Analysis model")
    router_model: str = Field(default="", description="Router model")
    # Strings so blank = inherit, exactly like the sampling params below.
    # Typed floats/ints here USED to force a value on every save (0.7/2048/auto),
    # which silently pinned sampling config on every app that ever opened this
    # tab and overrode the platform cascade. Blank now genuinely inherits.
    temperature: str = Field(default="", description="Temperature 0-2; blank = inherit")
    max_tokens: str = Field(default="", description="Max tokens 256-8192; blank = inherit")
    thinking_mode: str = Field(default="", description="auto, off, or on; blank = inherit")
    # LCU-4 per-extension AI params (2026-04-30). Strings so blank = inherit.
    top_p: str = Field(default="", description="Top P 0.0-1.0; blank = inherit")
    presence_penalty: str = Field(default="", description="Presence penalty -2.0..2.0; blank = inherit")
    frequency_penalty: str = Field(default="", description="Frequency penalty -2.0..2.0; blank = inherit")


class SavePersonaParams(BaseModel):
    app_id: str = Field(description="Extension app_id")
    system_prompt_intake: str = Field(default="")
    system_prompt_intelligence: str = Field(default="")
    language: str = Field(default="auto")
    tone: str = Field(default="formal")
    use_emojis: str = Field(default="false", description="'true' or 'false'")
    cite_sources: str = Field(default="true", description="'true' or 'false'")


class SaveAlertsParams(BaseModel):
    app_id: str = Field(description="Extension app_id")
    enabled: str = Field(default="true", description="'true' or 'false'")
    cooldown_seconds: int = Field(default=60, ge=10)
    max_per_hour: int = Field(default=10, ge=1, le=100)


class SaveRouterParams(BaseModel):
    app_id: str = Field(description="Extension app_id")
    enabled: str = Field(default="true", description="'true' or 'false'")
    timeout_ms: int = Field(default=3000, ge=500, le=10000)
    fallback: str = Field(default="first_tool")


class SaveSessionParams(BaseModel):
    app_id: str = Field(description="Extension app_id")
    timeout_hours: int = Field(default=24, ge=1)
    max_history: int = Field(default=40, ge=10)
    compress_at: int = Field(default=30, ge=5)
    history_ttl_days: int = Field(default=7, ge=1, le=90)


class SaveContextParams(BaseModel):
    app_id: str = Field(description="Extension app_id")
    max_tool_rounds: str = Field(default="", description="Empty = inherit platform default")
    max_result_tokens: str = Field(default="", description="Empty = inherit platform default")
    keep_recent_verbatim: str = Field(default="", description="Empty = inherit platform default")


class SaveSkeletonParams(BaseModel):
    app_id: str = Field(description="Extension app_id")
    sections_json: str = Field(default="[]", description="JSON array of section configs")

    class Config:
        extra = "allow"


# ── Helpers ────────────────────────────────────────────────────────── #

def _bool_from_str(val: str) -> bool:
    return str(val).lower() in ("true", "1", "yes", "on")


async def _save_section(app_id: str, section: str, data: dict) -> ActionResult:
    """PUT one settings section to Registry.

    Returns an ExtSettingsReceipt-shaped entity (id=app_id, kind="extension"):
    data keys {app_id, updated} mirror the receipt fields (federal
    I-EXT-RECORD-FIELD-NAMING-SYMMETRIC); the section name stays in the summary
    string rather than as a non-symmetric data key.
    """
    aid = await _resolve_app_id(app_id)
    r = await _registry_put(f"/v1/apps/{aid}/settings", {section: data})
    if r.status_code == 200:
        return ActionResult.success(
            data={"app_id": aid, "updated": True},
            summary=f"{section} settings saved for {aid}",
            refresh_panels=["tools"],
        )
    return ActionResult.error(f"Save failed: HTTP {r.status_code}")


# ── Handlers ───────────────────────────────────────────────────────── #

@chat.function(
    "save_ext_general", action_type="write", effects=["update:extension_settings"],
    event="extension_configured",
    data_model=ExtSettingsReceipt,
    description="Save extension general settings.",
)
async def fn_save_ext_general(ctx, params: SaveGeneralParams) -> ActionResult:
    """Save extension general settings."""
    # Status is NOT written here — marketplace lifecycle (active/suspended/draft)
    # has a single source of truth: the gateway status mutator behind the app's
    # Suspend/Restore/To-draft buttons. (params.status kept for back-compat, ignored.)
    result = await _save_section(params.app_id, "general", {
        "display_name": params.display_name,
    })
    # SINGLE SOURCE OF TRUTH: mirror the rename into developer_apps — the table
    # BOTH the marketplace and the panel sidebar read — so renaming here changes
    # the name everywhere, not just in the Registry-backed sidebar. Best-effort:
    # the Registry write above stays authoritative for this handler's result.
    if params.display_name and AUTH_GW and AUTH_SERVICE_TOKEN:
        try:
            from imperal_sdk._shared_http import shared_http
            aid = await _resolve_app_id(params.app_id)
            async with shared_http(timeout=10.0) as c:
                await c.post(
                    f"{AUTH_GW}/v1/admin/apps/{aid}/metadata",
                    headers={
                        "X-Service-Token": AUTH_SERVICE_TOKEN,
                        "Content-Type": "application/json",
                    },
                    json={"display_name": params.display_name},
                )
        except Exception:
            pass
    return result


@chat.function(
    "save_ext_models", action_type="write", effects=["update:extension_settings"],
    event="extension_configured",
    data_model=ExtSettingsReceipt,
    description="Save extension AI model settings.",
)
async def fn_save_ext_models(ctx, params: SaveModelsParams) -> ActionResult:
    """Save extension model routing settings.

    Blank means INHERIT for every field here: the key is dropped from the
    payload so the platform cascade falls through, rather than being pinned to
    whatever the form happened to show.
    """
    payload: dict = {
        "primary_model": params.primary_model,
        "intake_model": params.intake_model,
        "analysis_model": params.analysis_model,
        "router_model": params.router_model,
    }
    # LCU-4 (2026-04-30) — optional per-extension AI param overrides.
    # Blank string means "inherit" (drop key so kernel cascade falls through).
    for _k in ("top_p", "presence_penalty", "frequency_penalty"):
        _raw = (getattr(params, _k, "") or "").strip()
        if not _raw:
            continue
        try:
            payload[_k] = float(_raw)
        except (TypeError, ValueError):
            pass  # silently drop garbage; admin form has placeholder

    # 2026-08-09 — temperature/max_tokens/thinking_mode are blank-able too, so
    # "inherit" is expressible for the whole section. Ranges are enforced here
    # because the fields are strings now (Pydantic ge/le no longer applies):
    # an out-of-range or unparsable value is REFUSED rather than silently
    # coerced, since silently storing a wrong number is what this fix removes.
    _errors: list[str] = []

    _temp = (params.temperature or "").strip()
    if _temp:
        try:
            _val = float(_temp)
        except (TypeError, ValueError):
            _errors.append(f"temperature must be a number between 0 and 2 (got {_temp!r})")
        else:
            if 0 <= _val <= 2:
                payload["temperature"] = _val
            else:
                _errors.append(f"temperature must be between 0 and 2 (got {_val})")

    _max = (params.max_tokens or "").strip()
    if _max:
        try:
            _ival = int(float(_max))
        except (TypeError, ValueError):
            _errors.append(f"max_tokens must be a whole number 256-8192 (got {_max!r})")
        else:
            if 256 <= _ival <= 8192:
                payload["max_tokens"] = _ival
            else:
                _errors.append(f"max_tokens must be between 256 and 8192 (got {_ival})")

    _think = (params.thinking_mode or "").strip()
    if _think:
        if _think in ("auto", "off", "on"):
            payload["thinking_mode"] = _think
        else:
            _errors.append(f"thinking_mode must be auto, off or on (got {_think!r})")

    if _errors:
        return ActionResult.error("; ".join(_errors))

    result = await _save_section(params.app_id, "models", payload)

    # Blank = inherit only works if the omitted key actually LEAVES the store.
    # Both Registry and the Gateway deep-merge a settings section, so an
    # omitted key keeps its previous value and the admin can never un-pin
    # anything. The Gateway supports pruning explicitly (I-PANEL-SLOT-PRUNE):
    # replace_paths rewrites that subtree wholesale instead of merging.
    # Best-effort and deliberately AFTER the authoritative write: the save has
    # already succeeded, so a prune failure must not report the save as failed.
    if result.status == "success" and AUTH_GW and AUTH_SERVICE_TOKEN:
        try:
            aid = await _resolve_app_id(params.app_id)
            await _admin_put(
                f"/v1/internal/config/app/{aid}?tenant_id=default&app_id={aid}",
                {
                    "config": {"models": payload},
                    "replace_paths": ["models"],
                    "updated_by": "admin-ext-settings",
                },
            )
        except Exception:
            pass  # Registry write stands; the cascade self-heals on next save

    return result


@chat.function(
    "save_ext_persona", action_type="write", effects=["update:extension_settings"],
    event="extension_configured",
    data_model=ExtSettingsReceipt,
    description="Save extension persona settings.",
)
async def fn_save_ext_persona(ctx, params: SavePersonaParams) -> ActionResult:
    """Save extension persona settings."""
    return await _save_section(params.app_id, "persona", {
        "system_prompt_intake": params.system_prompt_intake,
        "system_prompt_intelligence": params.system_prompt_intelligence,
        "language": params.language,
        "tone": params.tone,
        "use_emojis": _bool_from_str(params.use_emojis),
        "cite_sources": _bool_from_str(params.cite_sources),
    })


@chat.function(
    "save_ext_alerts", action_type="write", effects=["update:extension_settings"],
    event="extension_configured",
    data_model=ExtSettingsReceipt,
    description="Save extension alert settings.",
)
async def fn_save_ext_alerts(ctx, params: SaveAlertsParams) -> ActionResult:
    """Save extension alert settings."""
    return await _save_section(params.app_id, "alerts", {
        "enabled": _bool_from_str(params.enabled),
        "cooldown_seconds": params.cooldown_seconds,
        "max_per_hour": params.max_per_hour,
    })


@chat.function(
    "save_ext_router", action_type="write", effects=["update:extension_settings"],
    event="extension_configured",
    data_model=ExtSettingsReceipt,
    description="Save extension router settings.",
)
async def fn_save_ext_router(ctx, params: SaveRouterParams) -> ActionResult:
    """Save extension router settings."""
    return await _save_section(params.app_id, "router", {
        "enabled": _bool_from_str(params.enabled),
        "timeout_ms": params.timeout_ms,
        "fallback": params.fallback,
    })


@chat.function(
    "save_ext_session", action_type="write", effects=["update:extension_settings"],
    event="extension_configured",
    data_model=ExtSettingsReceipt,
    description="Save extension session settings.",
)
async def fn_save_ext_session(ctx, params: SaveSessionParams) -> ActionResult:
    """Save extension session settings."""
    return await _save_section(params.app_id, "session", {
        "timeout_hours": params.timeout_hours,
        "max_history": params.max_history,
        "compress_at": params.compress_at,
        "history_ttl_days": params.history_ttl_days,
    })


@chat.function(
    "save_ext_context", action_type="write", effects=["update:extension_settings"],
    event="extension_configured",
    data_model=ExtSettingsReceipt,
    description="Save extension context settings.",
)
async def fn_save_ext_context(ctx, params: SaveContextParams) -> ActionResult:
    """Save extension context-window settings."""
    data: dict = {}
    if params.max_tool_rounds:
        data["max_tool_rounds"] = int(params.max_tool_rounds)
    if params.max_result_tokens:
        data["max_result_tokens"] = int(params.max_result_tokens)
    if params.keep_recent_verbatim:
        data["keep_recent_verbatim"] = int(params.keep_recent_verbatim)
    return await _save_section(params.app_id, "context", data)


@chat.function(
    "save_ext_skeleton", action_type="write", effects=["update:extension_settings"],
    event="skeleton_updated",
    data_model=ExtSettingsReceipt,
    description="Save extension skeleton section settings.",
)
async def fn_save_ext_skeleton(ctx, params: SaveSkeletonParams) -> ActionResult:
    """Save extension skeleton (panel context-refresh) settings."""
    import json
    extra = params.model_extra or {}

    # Reconstruct sections from per-field params (skel_ttl_X, skel_alert_X)
    section_names = set()
    for key in extra:
        if key.startswith("skel_ttl_"):
            section_names.add(key[9:])
        elif key.startswith("skel_alert_"):
            section_names.add(key[11:])

    if section_names:
        clean = [
            {
                "section_name": name,
                "ttl": int(extra.get(f"skel_ttl_{name}", 60)),
                "alert_on_change": _bool_from_str(str(extra.get(f"skel_alert_{name}", "false"))),
            }
            for name in sorted(section_names)
        ]
    else:
        # Fallback to legacy sections_json
        try:
            sections = json.loads(params.sections_json)
        except (json.JSONDecodeError, TypeError):
            return ActionResult.error("No skeleton settings to save")
        if not isinstance(sections, list):
            return ActionResult.error("sections must be a JSON array")
        clean = [
            {
                "section_name": s.get("section_name", ""),
                "ttl": int(s.get("ttl", 60)),
                "alert_on_change": _bool_from_str(str(s.get("alert_on_change", False))),
            }
            for s in sections if s.get("section_name")
        ]
    return await _save_section(params.app_id, "skeleton", {"sections": clean})
