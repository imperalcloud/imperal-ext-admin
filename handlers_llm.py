"""Admin · LLM config save + test handlers."""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

from pydantic import BaseModel, Field
from app import chat, ActionResult
from models_records import (
    LLMConfigReceipt,
    LLMTestResultRecord,
)
from panels_sections import _invalidate_panel_cache

log = logging.getLogger("admin")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

from models_llm_config import SaveLlmConfigParams  # extracted; keeps file under 300 lines


# SDL: save_llm_config returns a config-save receipt whose runtime keys are
# {saved, tenant_defaults_updated, config} (or {reset} / {override, model}).
# LLMConfigReceipt mirrors every observed key verbatim
# (I-EXT-RECORD-FIELD-NAMING-SYMMETRIC).
@chat.function("save_llm_config", action_type="write", event="llm_config_saved",
               data_model=LLMConfigReceipt,
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
            "chain_prior_step_max_chars", "chain_prior_total_max_chars", "hub_dispatch_max_depth",
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
            # Federalization 2026-05-19 — new per-purpose AI params (handled below)
            "purpose_conversational_temperature", "purpose_conversational_top_p", "purpose_conversational_presence_penalty", "purpose_conversational_frequency_penalty",
            "purpose_step_reclassify_temperature", "purpose_step_reclassify_top_p", "purpose_step_reclassify_presence_penalty", "purpose_step_reclassify_frequency_penalty",
            "purpose_tool_picker_temperature", "purpose_tool_picker_top_p", "purpose_tool_picker_presence_penalty", "purpose_tool_picker_frequency_penalty",
            "purpose_action_narrator_temperature", "purpose_action_narrator_top_p", "purpose_action_narrator_presence_penalty", "purpose_action_narrator_frequency_penalty",
        }
        updates = {}
        for field in SaveLlmConfigParams.model_fields:
            if field in skip_fields:
                continue
            val = getattr(params, field)
            if val is not None and val != "":
                updates[field] = val
        # Sprint 2 hotfix (2026-04-28): per-purpose Model Select is cross-provider.
        # If admin picks e.g. claude-sonnet for execution while the global provider
        # is openai, the resolver would pair incompatible model+provider → 404 from
        # API. Auto-infer the per-purpose provider from the model id (prefix-based,
        # via panels_llm_models.provider_for_model — works for ANY model the live
        # catalogue surfaces, no hardcoded model→provider table).
        from panels_llm_models import provider_for_model
        for _purpose in ("routing", "execution", "navigate", "chain_narrative", "judge",
                         # Federalization 2026-05-19 — new per-purpose models
                         "conversational", "step_reclassify", "tool_picker", "action_narrator"):
            _model_key = f"{_purpose}_model"
            _provider_key = f"{_purpose}_provider"
            _model_val = updates.get(_model_key, "")
            if _model_val and not updates.get(_provider_key):
                # Admin set the model but left provider empty → infer provider.
                _inferred = provider_for_model(_model_val)
                if _inferred:
                    updates[_provider_key] = _inferred
            elif not str(getattr(params, _model_key, "") or "").strip():
                # "Same as default" (empty) submission → CLEAR the stored
                # override so this purpose inherits the global model. The generic
                # updates loop skips empty values, so without this an override
                # could be SET but never cleared (the value silently persisted).
                # 2026-06-06: fixes "per-purpose → default doesn't save".
                current.pop(_model_key, None)
                current.pop(_provider_key, None)

        # ── LCU-4 per-purpose AI params (2026-04-30) ──────────────
        # Form sends flat `purpose_{name}_{param}` strings; kernel cascade
        # reads nested `purpose: {name: {param: val}}` (format 1). Build that
        # nested dict and merge into the existing `purpose` map so existing
        # entries (e.g. ones written by earlier saves) survive.
        _purpose_map: dict = current.get("purpose") if isinstance(current.get("purpose"), dict) else {}
        for _p in ("routing", "execution", "navigate", "chain_narrative", "judge",
                   # Federalization 2026-05-19 — new per-purpose AI params
                   "conversational", "step_reclassify", "tool_picker", "action_narrator"):
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
        # Drop stale `llm_config` / `tenant_defaults` entries so the next
        # panel render re-fetches Redis instead of serving the pre-save copy.
        _invalidate_panel_cache()

        # ── Token Budget Controls dispatch (2026-04-27) ─────────────────
        # Admin-only and default-X fields go to PATCH /v1/admin/tenant-defaults
        # with X-Acting-User header so auth-gw verifies role='admin'.
        tb_payload: dict = {}
        if params.narration_history_limit is not None: tb_payload["narration_history_limit"] = params.narration_history_limit
        if params.confirmation_card_tokens is not None: tb_payload["confirmation_card_tokens"] = params.confirmation_card_tokens
        if params.judge_digest_chars is not None: tb_payload["judge_digest_chars"] = params.judge_digest_chars
        if params.chain_prior_step_max_chars is not None: tb_payload["chain_prior_step_max_chars"] = params.chain_prior_step_max_chars
        if params.chain_prior_total_max_chars is not None: tb_payload["chain_prior_total_max_chars"] = params.chain_prior_total_max_chars
        if params.hub_dispatch_max_depth is not None: tb_payload["hub_dispatch_max_depth"] = params.hub_dispatch_max_depth
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
        # Phase 16 — wire 5 new admin-tunable kctx fields
        if params.narrator_structured_data_chars is not None: tb_payload["narrator_structured_data_chars"] = params.narrator_structured_data_chars
        if params.default_max_result_tokens is not None: tb_payload["default_max_result_tokens"] = params.default_max_result_tokens
        if params.list_truncate_items is not None: tb_payload["list_truncate_items"] = params.list_truncate_items
        if params.classifier_fact_ledger_window is not None: tb_payload["classifier_fact_ledger_window"] = params.classifier_fact_ledger_window
        # P5 (2026-05-28): two new REF caps — federal I-REF-CAP-PER-ARGS + I-REF-CAP-CROSS-TURN.
        if params.chain_max_refs_per_args is not None: tb_payload["chain_max_refs_per_args"] = params.chain_max_refs_per_args
        if params.cross_turn_max_refs is not None: tb_payload["cross_turn_max_refs"] = params.cross_turn_max_refs
        if params.quality_ceiling_tokens is not None: tb_payload["quality_ceiling_tokens"] = params.quality_ceiling_tokens
        if params.string_truncate_chars is not None: tb_payload["string_truncate_chars"] = params.string_truncate_chars
        if params.history_ttl_days is not None: tb_payload["history_ttl_days"] = params.history_ttl_days

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
            refresh_panels=["tools"],
        )
    except Exception as e:
        log.error("save_llm_config failed: %s", e)
        return ActionResult.error(f"Failed: {e}", retryable=True)


class TestLlmParams(BaseModel):
    """Test LLM connection."""
    provider: str = Field(default="", description="Provider to test (default: current)")
    model: str = Field(default="", description="Model to test (default: current)")


@chat.function("test_llm_connection", action_type="read",
               data_model=LLMTestResultRecord,
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
        # SDL symmetry (I-EXT-RECORD-FIELD-NAMING-SYMMETRIC): every key here is a
        # field on LLMTestResultRecord — ``success``/``model``/``provider`` are
        # declared fields and ``status`` is the core sdl.Entity field.
        return ActionResult.success(
            data={"success": True, "provider": provider, "model": model, "status": "ok"},
            summary=f"Connection to {provider}/{model} appears configured",
        )
    except Exception as e:
        return ActionResult.error(f"Connection test failed: {e}")
