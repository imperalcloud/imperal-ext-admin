"""Token Budget Controls (TBC) — meta groups 4-6 (cost ceiling, confirmation, user limits).

Federal cost ceiling, confirmation/audit budgets, and default-per-user knobs.
Split out of panels_llm_form_tbc.py to keep each module under 300 lines per
workspace rule 6 (no god files).

Federal: I-ADMIN-FIELD-DESCRIPTIONS-CANONICAL + I-ADMIN-NO-ORPHAN-UI.
"""
from imperal_sdk import ui


def build_tbc_meta_children(defaults: dict) -> list:
    """Return the Groups 4-6 children list for the TBC ui.Section.

    Spliced into panels_llm_form_tbc.build_tbc_section after Groups 1-3.
    """
    return [
        # ── Group 4: Federal cost ceiling ──
        ui.Text("🛡 Federal cost ceiling", variant="subtitle"),

        ui.Text(
            "quality_ceiling_tokens — UNIT: tokens. Federal hard cap on max_tokens "
            "for ANY LLM call, regardless of per-purpose setting. Default 50000. "
            "Prevents accidental cost runaway. Consumer: llm/provider.py:create_message "
            "(clamps requested max_tokens).",
            variant="caption",
        ),
        ui.Slider(
            min=1024, max=500000, step=1024,
            value=defaults.get("quality_ceiling_tokens", 50000),
            label="quality_ceiling_tokens (tokens)",
            param_name="quality_ceiling_tokens",
        ),

        # ── Group 5: Confirmation & audit ──
        ui.Text("✅ Confirmation & audit", variant="subtitle"),

        ui.Text(
            "confirmation_card_tokens — UNIT: tokens. max_tokens for LLM that "
            "summarizes write/destructive actions on confirmation cards. Default 300. "
            "Higher = more detailed card text. Consumer: safety/confirmation.py.",
            variant="caption",
        ),
        ui.Slider(
            min=200, max=8000, step=50,
            value=defaults["confirmation_card_tokens"],
            label="confirmation_card_tokens (tokens)",
            param_name="confirmation_card_tokens",
        ),

        ui.Text(
            "judge_digest_chars — UNIT: chars. Cap on audit-judge digest of tool "
            "results before LLM critique. Default 8000. Higher = judge sees more "
            "raw data. Consumer: responses/judge.py.",
            variant="caption",
        ),
        ui.Slider(
            min=2000, max=128000, step=500,
            value=defaults["judge_digest_chars"],
            label="judge_digest_chars (chars)",
            param_name="judge_digest_chars",
        ),

        # ── Group 6: Default user limits ──
        ui.Text("👥 Default user limits (admin sets baseline; users can override)", variant="subtitle"),

        ui.Text(
            "default_max_tool_rounds — UNIT: count. How many sequential tool-call "
            "rounds SDK chat handler may execute per turn (chain depth ceiling). "
            "Default 10. Higher = deeper auto-iteration. Consumer: SDK chat/handler.py.",
            variant="caption",
        ),
        ui.Slider(
            min=1, max=100, step=1,
            value=defaults["default_max_tool_rounds"],
            label="default_max_tool_rounds (count)",
            param_name="default_max_tool_rounds",
        ),

        ui.Text(
            "default_kav_max_retries — UNIT: retries. How many times KAV (Kernel "
            "Action Validator) retries a tool call before fail. Default 2. Higher = "
            "more resilient on transient errors. Consumer: kctx.kav_max_retries.",
            variant="caption",
        ),
        ui.Slider(
            min=0, max=50, step=1,
            value=defaults["default_kav_max_retries"],
            label="default_kav_max_retries (retries)",
            param_name="default_kav_max_retries",
        ),

        ui.Text(
            "default_confirmation_enabled — UNIT: boolean. Whether new users get "
            "write/destructive 2-step confirmation cards by default. Default false. "
            "Consumer: kctx.confirmation_enabled.",
            variant="caption",
        ),
        ui.Toggle(
            label="default_confirmation_enabled (new users)",
            value=defaults["default_confirmation_enabled"],
            param_name="default_confirmation_enabled",
        ),
    ]
