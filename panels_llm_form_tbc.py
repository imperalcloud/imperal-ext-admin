"""Admin · Token Budget Controls section (split from panels_llm_form.py).

Builds the collapsible "Token Budget Controls" Section for the LLM config Form.
Pure UI assembly — reads numeric defaults from the parent Form's `defaults` dict
and emits the matching Slider/Toggle inputs. No I/O.
"""
from __future__ import annotations

from imperal_sdk import ui


def build_tbc_section(defaults: dict) -> object:
    """Build the Token Budget Controls Section.

    Caller-supplied `defaults` must already contain the int/bool values for
    each named slider/toggle (see panels_llm_form.build_llm_form for the full
    key list). Returns a single ui.Section to embed in the parent Form.
    """
    return ui.Section(title="Token Budget Controls", collapsible=True, children=[
        ui.Text("System internals (admin-only)", variant="caption"),
        ui.Text("Narration history limit (turns)", variant="caption"),
        ui.Slider(
            min=4, max=50, step=1,
            value=defaults["narration_history_limit"],
            label="narration_history_limit",
            param_name="narration_history_limit",
        ),
        ui.Text("Confirmation card max_tokens", variant="caption"),
        ui.Slider(
            min=200, max=1024, step=32,
            value=defaults["confirmation_card_tokens"],
            label="confirmation_card_tokens",
            param_name="confirmation_card_tokens",
        ),
        ui.Text("Judge digest max chars", variant="caption"),
        ui.Slider(
            min=2000, max=32000, step=500,
            value=defaults["judge_digest_chars"],
            label="judge_digest_chars",
            param_name="judge_digest_chars",
        ),
        ui.Text("Chain prior-step max chars (truncation per step)", variant="caption"),
        ui.Slider(
            min=500, max=32000, step=500,
            value=defaults["chain_prior_step_max_chars"],
            label="chain_prior_step_max_chars",
            param_name="chain_prior_step_max_chars",
        ),
        ui.Text("Chain prior-total max chars (cap fed to next step)", variant="caption"),
        ui.Slider(
            min=3000, max=200000, step=1000,
            value=defaults["chain_prior_total_max_chars"],
            label="chain_prior_total_max_chars",
            param_name="chain_prior_total_max_chars",
        ),

        # TBC-FULL audit (2026-04-29 → cleanup 2026-05-13) — 7 admin-tunable max_tokens caps
        # (structured_gen_max_tokens dropped — no kernel reader; all 3 callers pass purpose-specific caps.)
        ui.Text("Automation plan-parser max_tokens (activities/automation.py:358)", variant="caption"),
        ui.Slider(
            min=256, max=16000, step=256,
            value=defaults["automation_main_max_tokens"],
            label="automation_main_max_tokens",
            param_name="automation_main_max_tokens",
        ),
        ui.Text("Automation condition-eval max_tokens (activities/automation.py:448)", variant="caption"),
        ui.Slider(
            min=10, max=1024, step=10,
            value=defaults["automation_condition_max_tokens"],
            label="automation_condition_max_tokens",
            param_name="automation_condition_max_tokens",
        ),
        ui.Text("Intent classifier max_tokens (hub/intent_classifier.py:881)", variant="caption"),
        ui.Slider(
            min=256, max=16000, step=256,
            value=defaults["intent_classifier_planner_max_tokens"],
            label="intent_classifier_planner_max_tokens",
            param_name="intent_classifier_planner_max_tokens",
        ),
        ui.Text("Prose-judge Gate 6 max_tokens (narration/prose_judge.py:234)", variant="caption"),
        ui.Slider(
            min=256, max=16000, step=256,
            value=defaults["prose_judge_max_tokens"],
            label="prose_judge_max_tokens",
            param_name="prose_judge_max_tokens",
        ),
        ui.Text("system_chat handler max_tokens (pipeline/system_handlers.py:300)", variant="caption"),
        ui.Slider(
            min=256, max=16000, step=256,
            value=defaults["system_handlers_max_tokens"],
            label="system_handlers_max_tokens",
            param_name="system_handlers_max_tokens",
        ),
        ui.Text("Audit-judge max_tokens (responses/judge.py:163)", variant="caption"),
        ui.Slider(
            min=256, max=16000, step=256,
            value=defaults["responses_judge_max_tokens"],
            label="responses_judge_max_tokens",
            param_name="responses_judge_max_tokens",
        ),
        ui.Text("Rule-engine eval max_tokens (services/rule_engine.py:182)", variant="caption"),
        ui.Slider(
            min=10, max=512, step=10,
            value=defaults["rule_engine_max_tokens"],
            label="rule_engine_max_tokens",
            param_name="rule_engine_max_tokens",
        ),

        ui.Text("Default user limits (admin sets baseline; users can override via Settings)", variant="caption"),
        ui.Text("Default max reply tokens", variant="caption"),
        ui.Slider(
            min=256, max=4096, step=64,
            value=defaults["default_max_response_tokens"],
            label="default_max_response_tokens",
            param_name="default_max_response_tokens",
        ),
        ui.Text("Default max tool rounds", variant="caption"),
        ui.Slider(
            min=1, max=30, step=1,
            value=defaults["default_max_tool_rounds"],
            label="default_max_tool_rounds",
            param_name="default_max_tool_rounds",
        ),
        ui.Text("Default routing context (classifier history)", variant="caption"),
        ui.Slider(
            min=4, max=50, step=1,
            value=defaults["default_routing_context"],
            label="default_routing_context",
            param_name="default_routing_context",
        ),
        ui.Text("Default KAV max retries", variant="caption"),
        ui.Slider(
            min=0, max=10, step=1,
            value=defaults["default_kav_max_retries"],
            label="default_kav_max_retries",
            param_name="default_kav_max_retries",
        ),
        ui.Toggle(
            label="Default confirmation enabled (new users)",
            value=defaults["default_confirmation_enabled"],
            param_name="default_confirmation_enabled",
        ),
    ])
