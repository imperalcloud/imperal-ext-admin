"""Admin · SaveLlmConfigParams Pydantic model.

Extracted from handlers_llm.py to keep that file under workspace rule 6
(no god files >300 lines). Defines the typed parameter schema for the
save_llm_config write tool — every field maps to one row in the LLM
configuration form on the LLM tab.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


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
    # ── Token Budget Controls (TBC, Phase 16 federal refactor 2026-05-17) ──
    # All fields admin-tunable; sourced from user_settings via Auth GW tenant-defaults.
    # Every field has explicit UNIT in description: tokens / chars / turns / count.
    # Max bounds raised to fit modern 200K-context models (Sonnet/Opus 4.x).

    narration_history_limit: Optional[int] = Field(
        default=None, ge=4, le=200,
        description=(
            "UNIT: turns. How many recent conversation turns the narrator LLM "
            "sees when composing replies. Higher = better continuity, more "
            "tokens per call. Default 12. Affects narration prompt context "
            "window in chain_renderer.py."
        ),
    )
    confirmation_card_tokens: Optional[int] = Field(
        default=None, ge=200, le=8000,
        description=(
            "UNIT: tokens. max_tokens cap for the LLM that summarizes write/"
            "destructive actions on confirmation cards. Default 300. Higher = "
            "more detailed card text, slightly more cost per confirmation. "
            "Reads at safety/confirmation.py:340."
        ),
    )
    judge_digest_chars: Optional[int] = Field(
        default=None, ge=2000, le=128000,
        description=(
            "UNIT: characters. Cap on audit-judge digest of tool results before "
            "LLM critique runs. Default 8000. Higher = judge sees more raw data, "
            "more cost per audit. Reads at responses/judge.py:151."
        ),
    )
    chain_prior_step_max_chars: Optional[int] = Field(
        default=None, ge=500, le=128000,
        description=(
            "UNIT: characters. Per-step truncation cap of prior step output that "
            "subsequent chain steps see in their context. Default 8000. Higher = "
            "next step has more context, more LLM tokens. Reads at "
            "chain_executor.py:_summarise_prior_steps."
        ),
    )
    chain_prior_total_max_chars: Optional[int] = Field(
        default=None, ge=3000, le=500000,
        description=(
            "UNIT: characters. Total budget across ALL prior-step summaries fed to "
            "current step (max sum of per-step caps). Default 64000. Higher = "
            "richer cross-step context but bigger prompt. Reads at "
            "chain_executor.py:_summarise_prior_steps."
        ),
    )

    # ── max_tokens caps for kernel-internal LLM purposes ──
    automation_main_max_tokens: Optional[int] = Field(
        default=None, ge=256, le=32000,
        description=(
            "UNIT: tokens. max_tokens for automation rule plan-parser LLM that "
            "decodes user prompt into structured rule definition. Default 4096. "
            "Reads at activities/automation.py:358."
        ),
    )
    automation_condition_max_tokens: Optional[int] = Field(
        default=None, ge=10, le=4096,
        description=(
            "UNIT: tokens. max_tokens for automation condition-eval LLM that "
            "decides whether an event matches a rule condition. Default 50 "
            "(small — yes/no answers). Reads at activities/automation.py:448."
        ),
    )
    intent_classifier_planner_max_tokens: Optional[int] = Field(
        default=None, ge=256, le=32000,
        description=(
            "UNIT: tokens. max_tokens for intent classifier (Haiku) that routes "
            "every user turn. Default 4096. Includes chain plans + action_plans. "
            "Reads at hub/intent_classifier.py:881."
        ),
    )
    prose_judge_max_tokens: Optional[int] = Field(
        default=None, ge=256, le=32000,
        description=(
            "UNIT: tokens. max_tokens for prose-judge LLM (federal Gate 6 anti-"
            "fabrication review of every narrator output). Default 4096. Reads "
            "at narration/prose_judge.py:234."
        ),
    )
    system_handlers_max_tokens: Optional[int] = Field(
        default=None, ge=256, le=32000,
        description=(
            "UNIT: tokens. max_tokens for kernel system_chat handler (the LLM "
            "that answers free-form 'what can you do' / capability questions). "
            "Default 4096. Reads at pipeline/system_handlers.py:300."
        ),
    )
    responses_judge_max_tokens: Optional[int] = Field(
        default=None, ge=256, le=32000,
        description=(
            "UNIT: tokens. max_tokens for audit-judge LLM (federal post-action "
            "review that records pass/fail in audit ledger). Default 4096. "
            "Reads at responses/judge.py:163."
        ),
    )
    rule_engine_max_tokens: Optional[int] = Field(
        default=None, ge=10, le=4096,
        description=(
            "UNIT: tokens. max_tokens for rule-engine eval LLM (one-shot "
            "trigger/condition matchers). Default 50. Reads at "
            "services/rule_engine.py:182."
        ),
    )

    # ── Default user limits (admin sets tenant baseline; users can override) ──
    default_max_response_tokens: Optional[int] = Field(
        default=None, ge=256, le=32000,
        description=(
            "UNIT: tokens. Default max_tokens for chat narration in new "
            "user accounts. Default 1024. Higher = longer detailed answers, "
            "more cost per response. Reads at kctx.max_response_tokens."
        ),
    )
    default_max_tool_rounds: Optional[int] = Field(
        default=None, ge=1, le=100,
        description=(
            "UNIT: count. How many sequential tool-call rounds the SDK chat "
            "handler may execute per turn (chain depth ceiling). Default 10. "
            "Higher = deeper auto-iteration, more cost. Reads at SDK "
            "chat/handler.py:252."
        ),
    )
    default_routing_context: Optional[int] = Field(
        default=None, ge=4, le=200,
        description=(
            "UNIT: turns. How many recent conversation turns the classifier "
            "LLM (Haiku, every turn) sees for context. Default 20. Higher = "
            "better anaphora resolution, more tokens. Reads at "
            "kctx.routing_context."
        ),
    )
    default_kav_max_retries: Optional[int] = Field(
        default=None, ge=0, le=50,
        description=(
            "UNIT: retries. How many times KAV (Kernel Action Validator) "
            "retries a tool call before reporting fail. Default 2. Higher = "
            "more resilient on transient errors, slower failure surface. "
            "Reads at kctx.kav_max_retries."
        ),
    )
    default_confirmation_enabled: Optional[bool] = Field(
        default=None,
        description=(
            "UNIT: boolean. Whether new users get write/destructive 2-step "
            "confirmation cards by default. Default false (admin tenants "
            "typically opt in via Settings). Reads at kctx.confirmation_enabled."
        ),
    )

    # ── Phase 16 NEW (wired previously-orphan System tab knobs) ──
    narrator_structured_data_chars: Optional[int] = Field(
        default=None, ge=1000, le=200000,
        description=(
            "UNIT: characters. Cap on JSON-serialized ActionResult.data shown "
            "to single-step narrator. Default 8000. Higher = narrator sees more "
            "raw tool data, can enumerate more items (e.g. show all 50 emails "
            "instead of first 5 + placeholders). Reads at "
            "chain_renderer.py:_synth_chain_prose."
        ),
    )
    default_max_result_tokens: Optional[int] = Field(
        default=None, ge=500, le=200000,
        description=(
            "UNIT: tokens. Cap on per-tool response/output text shown to "
            "narrator prose block (distinct from cross-step context cap and "
            "JSON data cap). Default 3000 tokens. Higher = narrator sees "
            "more verbose tool outputs."
        ),
    )
    list_truncate_items: Optional[int] = Field(
        default=None, ge=5, le=1000,
        description=(
            "UNIT: count. Max items rendered when $REF resolver shows a "
            "list as markdown bullets/table rows. Default 50. Higher = "
            "longer tables in chat, more output tokens. Reads at "
            "chain_arg_refs.py:_md_target_list."
        ),
    )
    quality_ceiling_tokens: Optional[int] = Field(
        default=None, ge=1024, le=500000,
        description=(
            "UNIT: tokens. Federal hard cap on max_tokens for ANY LLM call "
            "regardless of per-purpose setting. Default 50000. Protects "
            "against cost runaway. Reads at llm/provider.py:create_message."
        ),
    )
    string_truncate_chars: Optional[int] = Field(
        default=None, ge=200, le=50000,
        description=(
            "UNIT: characters. Cap on message/response preview length stored "
            "in SessionMemory turn digest (was hardcoded 1500). Default 1500. "
            "Higher = richer history context but more Redis storage. Reads at "
            "core/session_memory.py:_truncate_preview."
        ),
    )
    history_ttl_days: Optional[int] = Field(
        default=None, ge=1, le=90,
        description=(
            "UNIT: days. SessionMemory Redis TTL (was hardcoded 1 day / 86400s). "
            "Default 1 day. Higher = users keep more conversation history but more "
            "Redis storage. Reads via IMPERAL_HISTORY_TTL_SECONDS env at "
            "core/session_memory.py:_history_ttl_seconds (env set on worker boot)."
        ),
    )

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


