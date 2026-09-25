"""Admin · LLM form sub-builder for Sampling Parameters and Thinking/Reasoning Governance.

Extracted from panels_llm_form.py to maintain modular code hygiene.
"""
from __future__ import annotations

from imperal_sdk import ui


def build_purpose_ai_params_section(defaults: dict, purpose_models: list) -> list:
    """Category 4: Per-Purpose AI Parameters (temperature, top_p, etc.)."""
    aiparam_children: list = [
        ui.Text(
            "Fine-tune sampling per purpose. Leave blank to inherit "
            "(per-extension > per-purpose > global > provider default).",
            variant="caption",
        ),
    ]
    for key, label, _desc in purpose_models:
        aiparam_children.extend([
            ui.Text(label, variant="body"),
            ui.Stack([
                ui.Stack([
                    ui.Text("Temperature (0.0 – 2.0)", variant="caption"),
                    ui.Input(
                        param_name=f"purpose_{key}_temperature",
                        value=defaults.get(f"purpose_{key}_temperature", ""),
                        placeholder="inherit",
                    ),
                ], gap=0),
                ui.Stack([
                    ui.Text("Top P (0.0 – 1.0)", variant="caption"),
                    ui.Input(
                        param_name=f"purpose_{key}_top_p",
                        value=defaults.get(f"purpose_{key}_top_p", ""),
                        placeholder="inherit",
                    ),
                ], gap=0),
                ui.Stack([
                    ui.Text("Presence penalty (-2.0 – 2.0)", variant="caption"),
                    ui.Input(
                        param_name=f"purpose_{key}_presence_penalty",
                        value=defaults.get(f"purpose_{key}_presence_penalty", ""),
                        placeholder="inherit",
                    ),
                ], gap=0),
                ui.Stack([
                    ui.Text("Frequency penalty (-2.0 – 2.0)", variant="caption"),
                    ui.Input(
                        param_name=f"purpose_{key}_frequency_penalty",
                        value=defaults.get(f"purpose_{key}_frequency_penalty", ""),
                        placeholder="inherit",
                    ),
                ], gap=0),
            ], direction="h", gap=1, wrap=True),
            ui.Divider(),
        ])
    return aiparam_children


def build_thinking_governance_section(defaults: dict) -> list:
    """Category 5b: Extended Thinking & Reasoning Governance (ICNLI)."""
    effort_opts = [
        {"label": "Inherit / Provider Default", "value": ""},
        {"label": "None (Disable reasoning / fast)", "value": "none"},
        {"label": "Low", "value": "low"},
        {"label": "Medium", "value": "medium"},
        {"label": "High", "value": "high"},
        {"label": "Max (Deepest reasoning / verification)", "value": "max"},
    ]

    return [
        ui.Text(
            "Extended Thinking (Chain-of-Thought), Reasoning Effort (hardness) and token budgets across "
            "Claude 3.7 / Gemini 2.5+ / OpenAI o-series / GPT-5 / DeepSeek / Qwen. "
            "Controls how deep the model thinks before returning actions or final answers.",
            variant="caption",
        ),
        ui.Stack([
            ui.Text("Thinking Mode (auto / on / off)", variant="body"),
            ui.Text("Global thinking switch. 'auto' = model decides, 'on' = force deep CoT, 'off' = max speed / low latency.", variant="caption"),
        ], gap=0),
        ui.Input(
            placeholder="auto (default)",
            param_name="thinking_mode",
            value=str(defaults.get("thinking_mode", "auto")),
        ),
        ui.Stack([
            ui.Text("Global Reasoning Effort (hardness)", variant="body"),
            ui.Text("Controls reasoning effort level for OpenAI o-series/GPT-5, Gemini 2.5+, Claude 3.7.", variant="caption"),
        ], gap=0),
        ui.Select(
            param_name="thinking_effort",
            value=str(defaults.get("thinking_effort", "")),
            options=effort_opts,
        ),
        ui.Stack([
            ui.Text("Panel Max Reasoning Effort", variant="body"),
            ui.Text("Caps reasoning effort allowed in interactive web panel chat.", variant="caption"),
        ], gap=0),
        ui.Select(
            param_name="panel_max_thinking_effort",
            value=str(defaults.get("panel_max_thinking_effort", "")),
            options=effort_opts,
        ),
        ui.Stack([
            ui.Text("Max Thinking Tokens (Budget)", variant="body"),
            ui.Text("Max token budget reserved for internal reasoning tokens (e.g. 16000 for Claude 3.7).", variant="caption"),
        ], gap=0),
        ui.Input(
            placeholder="0 (auto / provider default)",
            param_name="max_thinking_tokens",
            value=str(defaults.get("max_thinking_tokens", "")),
        ),
    ]
