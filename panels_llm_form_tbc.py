"""Token Budget Controls (TBC) panel section — Phase 16 federal refactor 2026-05-17.

Each Slider has an explanatory `ui.Text(...)` caption above it stating:
  • WHAT the knob controls (which LLM call / which kernel chokepoint)
  • UNIT (tokens / chars / turns / count / retries / boolean)
  • IMPACT (cost / quality tradeoff)
  • DEFAULT value
  • CONSUMER source file:function (federal traceability)

All max limits bumped to fit modern 200K-context models (Sonnet 4.6 / Opus 4.7).
Federal: I-ADMIN-FIELD-DESCRIPTIONS-CANONICAL + I-ADMIN-NO-ORPHAN-UI.
"""
from imperal_sdk import ui

from panels_llm_form_tbc_meta import build_tbc_meta_children


def build_tbc_section(defaults: dict):
    """Return TBC ui.Section pre-populated with current tenant defaults.

    `defaults` MUST contain int/bool for every named param below — caller
    (panels_llm_form.build_llm_form) reads tenant config from auth-gw and
    populates defaults dict.
    """
    return ui.Section(title="Token Budget Controls", collapsible=True, children=[
        # ── Group 1: Narration & history ──
        ui.Text("📚 Narration & history", variant="subtitle"),

        ui.Text(
            "narration_history_limit — UNIT: turns. How many recent conversation "
            "turns the narrator LLM sees. Higher = better continuity, more tokens. "
            "Default 12. Consumer: hub/chain_renderer.py.",
            variant="caption",
        ),
        ui.Slider(
            min=4, max=200, step=1,
            value=defaults["narration_history_limit"],
            label="narration_history_limit (turns)",
            param_name="narration_history_limit",
        ),

        ui.Text(
            "default_routing_context — UNIT: turns. Classifier (Haiku, every turn) "
            "context window for anaphora resolution. Default 20. Consumer: "
            "kctx.routing_context → hub/intent_classifier.py.",
            variant="caption",
        ),
        ui.Slider(
            min=4, max=200, step=1,
            value=defaults["default_routing_context"],
            label="default_routing_context (turns)",
            param_name="default_routing_context",
        ),

        ui.Text(
            "default_max_response_tokens — UNIT: tokens. max_tokens for chat "
            "narration responses. Default 1024. Higher = longer detailed answers. "
            "Consumer: kctx.max_response_tokens.",
            variant="caption",
        ),
        ui.Slider(
            min=256, max=32000, step=128,
            value=defaults["default_max_response_tokens"],
            label="default_max_response_tokens (tokens)",
            param_name="default_max_response_tokens",
        ),

        ui.Text(
            "narrator_structured_data_chars — UNIT: chars. Cap on JSON-serialized "
            "ActionResult.data shown to single-step narrator. Default 8000. Higher = "
            "narrator enumerates more list items (was 6000 hardcoded; bumped after "
            "5-app list truncated to 1 row). Consumer: chain_renderer._synth_chain_prose.",
            variant="caption",
        ),
        ui.Slider(
            min=1000, max=200000, step=500,
            value=defaults.get("narrator_structured_data_chars", 8000),
            label="narrator_structured_data_chars (chars)",
            param_name="narrator_structured_data_chars",
        ),

        ui.Text(
            "default_max_result_tokens — UNIT: tokens. Cap on per-tool response "
            "text shown in narrator prose. Default 3000. Distinct from JSON cap "
            "(above) and cross-step context cap. Consumer: chain_renderer.",
            variant="caption",
        ),
        ui.Slider(
            min=500, max=200000, step=100,
            value=defaults.get("default_max_result_tokens", 3000),
            label="default_max_result_tokens (tokens)",
            param_name="default_max_result_tokens",
        ),

        ui.Text(
            "string_truncate_chars — UNIT: chars. Cap on message/response preview "
            "stored in SessionMemory turn digest. Default 1500. Higher = richer "
            "history context but more Redis usage. Consumer: core/session_memory.py.",
            variant="caption",
        ),
        ui.Slider(
            min=200, max=50000, step=100,
            value=defaults.get("string_truncate_chars", 1500),
            label="string_truncate_chars (chars)",
            param_name="string_truncate_chars",
        ),

        ui.Text(
            "history_ttl_days — UNIT: days. SessionMemory Redis TTL (was "
            "hardcoded 1 day). Default 1. Higher = longer history retention "
            "but more Redis storage. Floor 1 day to prevent data loss. "
            "Consumer: core/session_memory.py:_history_ttl_seconds "
            "(via IMPERAL_HISTORY_TTL_SECONDS env on worker boot).",
            variant="caption",
        ),
        ui.Slider(
            min=1, max=90, step=1,
            value=defaults.get("history_ttl_days", 1),
            label="history_ttl_days (days)",
            param_name="history_ttl_days",
        ),

        ui.Text(
            "list_truncate_items — UNIT: count. Max items rendered when $REF "
            "resolver shows a list as markdown bullets/rows. Default 50. Higher = "
            "longer tables in chat. Consumer: chain_arg_refs.py.",
            variant="caption",
        ),
        ui.Slider(
            min=5, max=1000, step=5,
            value=defaults.get("list_truncate_items", 50),
            label="list_truncate_items (count)",
            param_name="list_truncate_items",
        ),

        # ── Group 2: Chain context ──
        ui.Text("⛓ Cross-step chain context", variant="subtitle"),

        ui.Text(
            "chain_prior_step_max_chars — UNIT: chars. Per-step truncation cap of "
            "prior step output that subsequent chain steps see. Default 8000. "
            "Higher = next step gets more context. Consumer: orchestration/chain_executor.py.",
            variant="caption",
        ),
        ui.Slider(
            min=500, max=128000, step=500,
            value=defaults["chain_prior_step_max_chars"],
            label="chain_prior_step_max_chars (chars)",
            param_name="chain_prior_step_max_chars",
        ),

        ui.Text(
            "chain_prior_total_max_chars — UNIT: chars. Total budget across ALL "
            "prior-step summaries (sum cap). Default 64000. Higher = richer cross-"
            "step context but bigger prompt. Consumer: orchestration/chain_executor.py.",
            variant="caption",
        ),
        ui.Slider(
            min=3000, max=500000, step=1000,
            value=defaults["chain_prior_total_max_chars"],
            label="chain_prior_total_max_chars (chars)",
            param_name="chain_prior_total_max_chars",
        ),

        # ── Group 3: max_tokens per LLM purpose ──
        ui.Text("🤖 max_tokens per kernel-internal LLM purpose", variant="subtitle"),

        ui.Text(
            "intent_classifier_planner_max_tokens — UNIT: tokens. Classifier "
            "(Haiku) max_tokens, runs every user turn. Default 4096. Includes "
            "chain plans + action_plans. Consumer: hub/intent_classifier.py.",
            variant="caption",
        ),
        ui.Slider(
            min=256, max=32000, step=128,
            value=defaults["intent_classifier_planner_max_tokens"],
            label="intent_classifier_planner_max_tokens (tokens)",
            param_name="intent_classifier_planner_max_tokens",
        ),

        ui.Text(
            "prose_judge_max_tokens — UNIT: tokens. Prose-judge LLM (federal Gate 6, "
            "anti-fabrication review of every narrator output). Default 4096. "
            "Consumer: narration/prose_judge.py.",
            variant="caption",
        ),
        ui.Slider(
            min=256, max=32000, step=128,
            value=defaults["prose_judge_max_tokens"],
            label="prose_judge_max_tokens (tokens)",
            param_name="prose_judge_max_tokens",
        ),

        ui.Text(
            "responses_judge_max_tokens — UNIT: tokens. Audit-judge LLM (post-action "
            "review for audit ledger). Default 4096. Consumer: responses/judge.py.",
            variant="caption",
        ),
        ui.Slider(
            min=256, max=32000, step=128,
            value=defaults["responses_judge_max_tokens"],
            label="responses_judge_max_tokens (tokens)",
            param_name="responses_judge_max_tokens",
        ),

        ui.Text(
            "system_handlers_max_tokens — UNIT: tokens. Kernel system_chat handler "
            "(answers free-form 'what can you do' / capability questions). "
            "Default 4096. Consumer: pipeline/system_handlers.py.",
            variant="caption",
        ),
        ui.Slider(
            min=256, max=32000, step=128,
            value=defaults["system_handlers_max_tokens"],
            label="system_handlers_max_tokens (tokens)",
            param_name="system_handlers_max_tokens",
        ),

        ui.Text(
            "automation_main_max_tokens — UNIT: tokens. Automation rule plan-parser "
            "LLM (decodes user prompt → rule). Default 4096. Consumer: "
            "activities/automation.py.",
            variant="caption",
        ),
        ui.Slider(
            min=256, max=32000, step=128,
            value=defaults["automation_main_max_tokens"],
            label="automation_main_max_tokens (tokens)",
            param_name="automation_main_max_tokens",
        ),

        ui.Text(
            "automation_condition_max_tokens — UNIT: tokens. Automation condition-"
            "eval LLM (yes/no rule-match). Default 50 (small). Consumer: "
            "activities/automation.py.",
            variant="caption",
        ),
        ui.Slider(
            min=10, max=4096, step=10,
            value=defaults["automation_condition_max_tokens"],
            label="automation_condition_max_tokens (tokens)",
            param_name="automation_condition_max_tokens",
        ),

        ui.Text(
            "rule_engine_max_tokens — UNIT: tokens. Rule-engine eval LLM (trigger/"
            "condition matcher). Default 50. Consumer: services/rule_engine.py.",
            variant="caption",
        ),
        ui.Slider(
            min=10, max=4096, step=10,
            value=defaults["rule_engine_max_tokens"],
            label="rule_engine_max_tokens (tokens)",
            param_name="rule_engine_max_tokens",
        ),

        # Groups 4-6 (federal cost ceiling, confirmation/audit, default user limits)
        # live in panels_llm_form_tbc_meta.py — keeps each module under workspace's
        # 300-line god-file ceiling per rule 6.
        *build_tbc_meta_children(defaults),
    ])
