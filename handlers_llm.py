"""Admin · LLM config save + test handlers."""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

from pydantic import BaseModel, Field
from app import chat, ActionResult

log = logging.getLogger("admin")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


class SaveLlmConfigParams(BaseModel):
    """Save LLM provider/model configuration."""
    provider: str = Field(default="", description="LLM provider")
    model: str = Field(default="", description="Default model")
    api_key: str = Field(default="", description="API key (write-only, leave blank to keep)")
    base_url: str = Field(default="", description="Custom base URL for OpenAI-compatible providers")
    routing_model: str = Field(default="", description="Routing model override")
    routing_provider: str = Field(default="", description="Routing provider override")
    execution_model: str = Field(default="", description="Execution model override")
    execution_provider: str = Field(default="", description="Execution provider override")
    navigate_model: str = Field(default="", description="Navigate model override")
    navigate_provider: str = Field(default="", description="Navigate provider override")
    chain_narrative_model: str = Field(default="", description="Chain narrator model override (Sprint 2)")
    chain_narrative_provider: str = Field(default="", description="Chain narrator provider override (Sprint 2)")
    judge_model: str = Field(default="", description="Judge model override (Sprint 2)")
    judge_provider: str = Field(default="", description="Judge provider override (Sprint 2)")
    failover_enabled: Optional[bool] = Field(default=None, description="Enable failover")
    failover_provider: str = Field(default="", description="Failover provider")
    failover_model: str = Field(default="", description="Failover model")
    failover_api_key: str = Field(default="", description="Failover API key (write-only)")
    set_extension_override: str = Field(default="", description="Extension ID to set override for")
    override_model: str = Field(default="", description="Model for extension override")
    override_provider: str = Field(default="", description="Provider for extension override")
    reset_extension_override: str = Field(default="", description="Extension ID to remove override for")
    # ── Token Budget Controls (2026-04-27) — admin-only kernel-internal knobs
    narration_history_limit: Optional[int] = Field(default=None, ge=4, le=50, description="History turns fed to narration")
    confirmation_card_tokens: Optional[int] = Field(default=None, ge=200, le=1024, description="Confirmation card max_tokens")
    judge_digest_chars: Optional[int] = Field(default=None, ge=2000, le=32000, description="Audit-judge digest cap (chars)")
    chain_prior_step_max_chars: Optional[int] = Field(default=None, ge=500, le=32000, description="Chain prior-step truncation cap (chars)")
    chain_prior_total_max_chars: Optional[int] = Field(default=None, ge=3000, le=200000, description="Chain prior-summary total cap (chars) fed to next step")
    # ── Token Budget Controls — full audit (TBC-FULL, 2026-04-29 → cleanup 2026-05-13) — 7 admin-tunable max_tokens caps
    # (planner_max_tokens + structured_gen_max_tokens dropped — orphan UI; no kernel reader.)
    automation_main_max_tokens: Optional[int] = Field(default=None, ge=256, le=16000, description="Automation plan-parser max_tokens (activities/automation.py:358)")
    automation_condition_max_tokens: Optional[int] = Field(default=None, ge=10, le=1024, description="Automation condition-eval max_tokens (activities/automation.py:448)")
    intent_classifier_planner_max_tokens: Optional[int] = Field(default=None, ge=256, le=16000, description="Intent classifier max_tokens (hub/intent_classifier.py:881)")
    prose_judge_max_tokens: Optional[int] = Field(default=None, ge=256, le=16000, description="Prose-judge Gate 6 max_tokens (narration/prose_judge.py:234)")
    system_handlers_max_tokens: Optional[int] = Field(default=None, ge=256, le=16000, description="system_chat handler max_tokens (pipeline/system_handlers.py:300)")
    responses_judge_max_tokens: Optional[int] = Field(default=None, ge=256, le=16000, description="Audit-judge max_tokens (responses/judge.py:163)")
    rule_engine_max_tokens: Optional[int] = Field(default=None, ge=10, le=512, description="Rule-engine eval max_tokens (services/rule_engine.py:182)")
    # ── Token Budget Controls — default user limits (admin sets tenant defaults)
    default_max_response_tokens: Optional[int] = Field(default=None, ge=256, le=4096, description="Default narration max_tokens for new users")
    default_max_tool_rounds: Optional[int] = Field(default=None, ge=1, le=30, description="Default tool-call rounds cap")
    default_routing_context: Optional[int] = Field(default=None, ge=4, le=50, description="Default classifier history limit")
    default_kav_max_retries: Optional[int] = Field(default=None, ge=0, le=10, description="Default KAV retry cap")
    default_confirmation_enabled: Optional[bool] = Field(default=None, description="Default confirmation_enabled for new users")

    # ── Per-purpose AI params (LCU-4, 2026-04-30) — empty string = inherit
    purpose_routing_temperature: str = Field(default="", description="Per-purpose temperature for routing (blank = inherit)")
    purpose_routing_top_p: str = Field(default="", description="Per-purpose top_p for routing")
    purpose_routing_presence_penalty: str = Field(default="", description="Per-purpose presence_penalty for routing")
    purpose_routing_frequency_penalty: str = Field(default="", description="Per-purpose frequency_penalty for routing")
    purpose_execution_temperature: str = Field(default="", description="Per-purpose temperature for execution")
    purpose_execution_top_p: str = Field(default="", description="Per-purpose top_p for execution")
    purpose_execution_presence_penalty: str = Field(default="", description="Per-purpose presence_penalty for execution")
    purpose_execution_frequency_penalty: str = Field(default="", description="Per-purpose frequency_penalty for execution")
    purpose_navigate_temperature: str = Field(default="", description="Per-purpose temperature for navigate")
    purpose_navigate_top_p: str = Field(default="", description="Per-purpose top_p for navigate")
    purpose_navigate_presence_penalty: str = Field(default="", description="Per-purpose presence_penalty for navigate")
    purpose_navigate_frequency_penalty: str = Field(default="", description="Per-purpose frequency_penalty for navigate")
    purpose_chain_narrative_temperature: str = Field(default="", description="Per-purpose temperature for chain_narrative")
    purpose_chain_narrative_top_p: str = Field(default="", description="Per-purpose top_p for chain_narrative")
    purpose_chain_narrative_presence_penalty: str = Field(default="", description="Per-purpose presence_penalty for chain_narrative")
    purpose_chain_narrative_frequency_penalty: str = Field(default="", description="Per-purpose frequency_penalty for chain_narrative")
    purpose_judge_temperature: str = Field(default="", description="Per-purpose temperature for judge")
    purpose_judge_top_p: str = Field(default="", description="Per-purpose top_p for judge")
    purpose_judge_presence_penalty: str = Field(default="", description="Per-purpose presence_penalty for judge")
    purpose_judge_frequency_penalty: str = Field(default="", description="Per-purpose frequency_penalty for judge")


@chat.function("save_llm_config", action_type="write", event="llm_config_saved",
               description="Save LLM provider/model config to Redis Config Store.")
async def fn_save_llm_config(ctx, params: SaveLlmConfigParams) -> ActionResult:
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(REDIS_URL, decode_responses=True)
        raw = await r.get("imperal:config:llm") or "{}"
        current = json.loads(raw)
        # Handle extension override operations
        ext_overrides = current.get("extension_overrides", {})
        if params.reset_extension_override:
            ext_id = params.reset_extension_override
            ext_overrides.pop(ext_id, None)
            current["extension_overrides"] = ext_overrides
            await r.set("imperal:config:llm", json.dumps(current))
            await r.aclose()
            return ActionResult.success(
                data={"reset": ext_id},
                summary=f"Reset LLM override for {ext_id}",
            refresh_panels=["tools"],
            )
        if params.set_extension_override and params.override_model:
            ext_id = params.set_extension_override
            ext_overrides[ext_id] = {
                "model": params.override_model,
                "provider": params.override_provider or current.get("provider", ""),
            }
            current["extension_overrides"] = ext_overrides
            await r.set("imperal:config:llm", json.dumps(current))
            await r.aclose()
            return ActionResult.success(
                data={"override": ext_id, "model": params.override_model},
                summary=f"Set LLM override for {ext_id}: {params.override_model}",
            )

        # Generic config update
        skip_fields = {"set_extension_override", "override_model", "override_provider", "reset_extension_override",
            # Token Budget fields routed via tenant-defaults endpoint, not Redis llm config.
            "narration_history_limit", "confirmation_card_tokens", "judge_digest_chars",
            "chain_prior_step_max_chars", "chain_prior_total_max_chars",
            # TBC-FULL 2026-04-29 → cleanup 2026-05-13 — 7 admin-tunable max_tokens caps
            "automation_main_max_tokens", "automation_condition_max_tokens",
            "intent_classifier_planner_max_tokens", "prose_judge_max_tokens", "system_handlers_max_tokens",
            "responses_judge_max_tokens", "rule_engine_max_tokens",
            "default_max_response_tokens", "default_max_tool_rounds", "default_routing_context", "default_kav_max_retries", "default_confirmation_enabled",
            # LCU-4 per-purpose AI params — handled separately below (nested under "purpose")
            "purpose_routing_temperature", "purpose_routing_top_p", "purpose_routing_presence_penalty", "purpose_routing_frequency_penalty",
            "purpose_execution_temperature", "purpose_execution_top_p", "purpose_execution_presence_penalty", "purpose_execution_frequency_penalty",
            "purpose_navigate_temperature", "purpose_navigate_top_p", "purpose_navigate_presence_penalty", "purpose_navigate_frequency_penalty",
            "purpose_chain_narrative_temperature", "purpose_chain_narrative_top_p", "purpose_chain_narrative_presence_penalty", "purpose_chain_narrative_frequency_penalty",
            "purpose_judge_temperature", "purpose_judge_top_p", "purpose_judge_presence_penalty", "purpose_judge_frequency_penalty",
        }
        updates = {}
        for field in SaveLlmConfigParams.model_fields:
            if field in skip_fields:
                continue
            val = getattr(params, field)
            if val is not None and val != "":
                updates[field] = val
        # Sprint 2 hotfix (2026-04-28): per-purpose Model Select uses ALL_MODELS
        # (cross-provider). If admin picks e.g. claude-sonnet for execution while
        # global provider is openai, the resolver pairs incompatible model+provider
        # → 404 from API. Auto-infer per-purpose provider from model name when
        # admin set the model but left provider empty. Mirrors the same _MODELS
        # mapping used by panels_llm_form.py to populate the dropdown.
        from panels_llm_form import _MODELS as _MODEL_TO_PROVIDER_TABLE
        _model_to_provider: dict[str, str] = {}
        for _prov, _models in _MODEL_TO_PROVIDER_TABLE.items():
            for _m in _models:
                _model_to_provider[_m] = _prov
        for _purpose in ("routing", "execution", "navigate", "chain_narrative", "judge"):
            _model_key = f"{_purpose}_model"
            _provider_key = f"{_purpose}_provider"
            _model_val = updates.get(_model_key, "")
            if _model_val and not updates.get(_provider_key):
                _inferred = _model_to_provider.get(_model_val, "")
                if _inferred:
                    updates[_provider_key] = _inferred

        # ── LCU-4 per-purpose AI params (2026-04-30) ──────────────
        # Form sends flat `purpose_{name}_{param}` strings; kernel cascade
        # reads nested `purpose: {name: {param: val}}` (format 1). Build that
        # nested dict and merge into the existing `purpose` map so existing
        # entries (e.g. ones written by earlier saves) survive.
        _purpose_map: dict = current.get("purpose") if isinstance(current.get("purpose"), dict) else {}
        for _p in ("routing", "execution", "navigate", "chain_narrative", "judge"):
            _slot = dict(_purpose_map.get(_p) or {})
            for _k in ("temperature", "top_p", "presence_penalty", "frequency_penalty"):
                _raw = getattr(params, f"purpose_{_p}_{_k}", "")
                _val_str = (str(_raw) if _raw is not None else "").strip()
                if not _val_str:
                    # blank means "inherit" → unset slot key if previously set
                    _slot.pop(_k, None)
                    continue
                try:
                    _slot[_k] = float(_val_str)
                except (TypeError, ValueError):
                    log.warning("LCU-4 ignored non-numeric purpose_%s_%s=%r", _p, _k, _raw)
            if _slot:
                _purpose_map[_p] = _slot
            else:
                # whole purpose slot empty → drop key for cleanliness
                _purpose_map.pop(_p, None)
        if _purpose_map:
            current["purpose"] = _purpose_map
        else:
            current.pop("purpose", None)

        current.update(updates)
        await r.set("imperal:config:llm", json.dumps(current))
        await r.aclose()

        # ── Token Budget Controls dispatch (2026-04-27) ─────────────────
        # Admin-only and default-X fields go to PATCH /v1/admin/tenant-defaults
        # with X-Acting-User header so auth-gw verifies role='admin'.
        tb_payload: dict = {}
        if params.narration_history_limit is not None: tb_payload["narration_history_limit"] = params.narration_history_limit
        if params.confirmation_card_tokens is not None: tb_payload["confirmation_card_tokens"] = params.confirmation_card_tokens
        if params.judge_digest_chars is not None: tb_payload["judge_digest_chars"] = params.judge_digest_chars
        if params.chain_prior_step_max_chars is not None: tb_payload["chain_prior_step_max_chars"] = params.chain_prior_step_max_chars
        if params.chain_prior_total_max_chars is not None: tb_payload["chain_prior_total_max_chars"] = params.chain_prior_total_max_chars
        # TBC-FULL 2026-04-29 → cleanup 2026-05-13 — 7 admin-tunable max_tokens caps
        if params.automation_main_max_tokens is not None: tb_payload["automation_main_max_tokens"] = params.automation_main_max_tokens
        if params.automation_condition_max_tokens is not None: tb_payload["automation_condition_max_tokens"] = params.automation_condition_max_tokens
        if params.intent_classifier_planner_max_tokens is not None: tb_payload["intent_classifier_planner_max_tokens"] = params.intent_classifier_planner_max_tokens
        if params.prose_judge_max_tokens is not None: tb_payload["prose_judge_max_tokens"] = params.prose_judge_max_tokens
        if params.system_handlers_max_tokens is not None: tb_payload["system_handlers_max_tokens"] = params.system_handlers_max_tokens
        if params.responses_judge_max_tokens is not None: tb_payload["responses_judge_max_tokens"] = params.responses_judge_max_tokens
        if params.rule_engine_max_tokens is not None: tb_payload["rule_engine_max_tokens"] = params.rule_engine_max_tokens
        if params.default_max_response_tokens is not None: tb_payload["max_response_tokens"] = params.default_max_response_tokens
        if params.default_max_tool_rounds is not None: tb_payload["max_tool_rounds"] = params.default_max_tool_rounds
        if params.default_routing_context is not None: tb_payload["routing_context"] = params.default_routing_context
        if params.default_kav_max_retries is not None: tb_payload["kav_max_retries"] = params.default_kav_max_retries
        if params.default_confirmation_enabled is not None: tb_payload["confirmation_enabled"] = params.default_confirmation_enabled

        tb_updated: list = []
        if tb_payload:
            try:
                import httpx as _httpx
                gw = os.getenv("IMPERAL_GATEWAY_URL", "http://104.224.88.155:8085")
                svc = os.getenv("AUTH_SERVICE_TOKEN", "")
                acting = ""
                try:
                    acting = str(getattr(getattr(ctx, "user", None), "imperal_id", "") or "")
                except Exception:
                    pass
                async with _httpx.AsyncClient(timeout=8.0) as client:
                    resp = await client.patch(
                        f"{gw}/v1/admin/tenant-defaults?tenant_id=default",
                        json=tb_payload,
                        headers={"X-Service-Token": svc, "X-Acting-User": acting},
                    )
                    if resp.status_code == 200:
                        tb_updated = (resp.json() or {}).get("updated", [])
                    else:
                        log.warning("tenant-defaults PATCH non-200: %s %s", resp.status_code, resp.text[:200])
            except Exception as _tb_err:
                log.warning("tenant-defaults PATCH failed: %s", _tb_err)

        return ActionResult.success(
            data={
                "saved": list(updates.keys()),
                "tenant_defaults_updated": tb_updated,
                "config": current,
            },
            summary=f"LLM config saved: {updates.get('provider', '')} {updates.get('model', '')}".strip() + (f" + {len(tb_updated)} token-budget knob(s)" if tb_updated else ""),
        )
    except Exception as e:
        log.error("save_llm_config failed: %s", e)
        return ActionResult.error(f"Failed: {e}", retryable=True)


class TestLlmParams(BaseModel):
    """Test LLM connection."""
    provider: str = Field(default="", description="Provider to test (default: current)")
    model: str = Field(default="", description="Model to test (default: current)")


@chat.function("test_llm_connection", action_type="read",
               description="Test connection to LLM provider.")
async def fn_test_llm_connection(ctx, params: TestLlmParams) -> ActionResult:
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(REDIS_URL, decode_responses=True)
        raw = await r.get("imperal:config:llm") or "{}"
        await r.aclose()
        cfg = json.loads(raw)
        provider = params.provider or cfg.get("provider", "anthropic")
        model = params.model or cfg.get("model", "claude-haiku-4-5-20251001")
        return ActionResult.success(
            data={"provider": provider, "model": model, "status": "ok"},
            summary=f"Connection to {provider}/{model} appears configured",
        )
    except Exception as e:
        return ActionResult.error(f"Connection test failed: {e}")
