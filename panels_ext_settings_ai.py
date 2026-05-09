"""Admin · Extension Settings — AI Models + Persona tabs.

Called from panels_ext_settings.py tab router. Returns list of UINodes.
"""
from __future__ import annotations

from imperal_sdk import ui


# ── Model options ─────────────────────────────────────────────────────

_MODEL_OPTIONS = [
    {"value": "", "label": "— Default —"},
    {"value": "claude-opus-4-7", "label": "Claude Opus 4.7"},
    {"value": "claude-sonnet-4-6", "label": "Claude Sonnet 4.6"},
    {"value": "claude-haiku-4-5-20251001", "label": "Claude Haiku 4.5"},
    {"value": "gpt-5", "label": "GPT-5"},
    {"value": "gpt-5-mini", "label": "GPT-5 Mini"},
    {"value": "gpt-5-nano", "label": "GPT-5 Nano"},
    {"value": "o3", "label": "OpenAI o3 (reasoning)"},
    {"value": "gpt-4.1", "label": "GPT-4.1"},
    {"value": "gpt-4.1-mini", "label": "GPT-4.1 Mini"},
    {"value": "gpt-4.1-nano", "label": "GPT-4.1 Nano"},
    {"value": "gpt-4o", "label": "GPT-4o"},
    {"value": "gpt-4o-mini", "label": "GPT-4o Mini"},
    {"value": "claude-sonnet-4-20250514", "label": "Claude Sonnet 4 (legacy)"},
    {"value": "claude-opus-4-20250514", "label": "Claude Opus 4 (legacy)"},
]

_LANGUAGE_OPTIONS = [
    {"value": "auto", "label": "Auto-detect"},
    {"value": "en", "label": "English"},
    {"value": "ru", "label": "Russian"},
    {"value": "de", "label": "German"},
    {"value": "uk", "label": "Ukrainian"},
]

_TONE_OPTIONS = [
    {"value": "formal", "label": "Formal"},
    {"value": "professional", "label": "Professional"},
    {"value": "casual", "label": "Casual"},
]

_THINKING_OPTIONS = [
    {"value": "auto", "label": "Auto — platform decides based on model"},
    {"value": "off", "label": "Off — disable thinking (recommended for tool-use models)"},
    {"value": "on", "label": "On — enable extended thinking"},
]


# ── AI Models tab ─────────────────────────────────────────────────────

def build_models_tab(app_id: str, settings: dict) -> list:
    m = settings.get("models", {})
    thinking = m.get("thinking_mode", "auto")
    return [
        ui.Form(
            action="save_ext_models",
            submit_label="Save AI Models",
            defaults={
                "app_id": app_id,
                "primary_model": m.get("primary_model", ""),
                "intake_model": m.get("intake_model", ""),
                "analysis_model": m.get("analysis_model", ""),
                "router_model": m.get("router_model", ""),
                "temperature": str(m.get("temperature", 0.7)),
                "max_tokens": str(m.get("max_tokens", 2048)),
                "top_p": ("" if m.get("top_p") is None else str(m.get("top_p"))),
                "presence_penalty": ("" if m.get("presence_penalty") is None else str(m.get("presence_penalty"))),
                "frequency_penalty": ("" if m.get("frequency_penalty") is None else str(m.get("frequency_penalty"))),
                "thinking_mode": thinking,
            },
            children=[
                ui.Text("Primary Model", variant="caption"),
                ui.Select(
                    param_name="primary_model",
                    value=m.get("primary_model", ""),
                    options=_MODEL_OPTIONS,
                ),
                ui.Text("Intake Model", variant="caption"),
                ui.Select(
                    param_name="intake_model",
                    value=m.get("intake_model", ""),
                    options=_MODEL_OPTIONS,
                ),
                ui.Text("Analysis Model", variant="caption"),
                ui.Select(
                    param_name="analysis_model",
                    value=m.get("analysis_model", ""),
                    options=_MODEL_OPTIONS,
                ),
                ui.Text("Router Model", variant="caption"),
                ui.Select(
                    param_name="router_model",
                    value=m.get("router_model", ""),
                    options=_MODEL_OPTIONS,
                ),
                ui.Text("Temperature (0 — 2)", variant="caption"),
                ui.Input(
                    param_name="temperature",
                    value=str(m.get("temperature", 0.7)),
                    placeholder="0.7",
                ),
                ui.Text("Max Tokens (256 — 8192)", variant="caption"),
                ui.Input(
                    param_name="max_tokens",
                    value=str(m.get("max_tokens", 2048)),
                    placeholder="2048",
                ),
                # LCU-4 per-extension AI params (2026-04-30) — empty = inherit.
                # Cascade: per-extension > per-purpose > global > provider default.
                ui.Text("Top P (0.0 — 1.0; blank to inherit)", variant="caption"),
                ui.Input(
                    param_name="top_p",
                    value=("" if m.get("top_p") is None else str(m.get("top_p"))),
                    placeholder="inherit",
                ),
                ui.Text("Presence penalty (-2.0 — 2.0; blank to inherit)", variant="caption"),
                ui.Input(
                    param_name="presence_penalty",
                    value=("" if m.get("presence_penalty") is None else str(m.get("presence_penalty"))),
                    placeholder="inherit",
                ),
                ui.Text("Frequency penalty (-2.0 — 2.0; blank to inherit)", variant="caption"),
                ui.Input(
                    param_name="frequency_penalty",
                    value=("" if m.get("frequency_penalty") is None else str(m.get("frequency_penalty"))),
                    placeholder="inherit",
                ),
                ui.Divider(),
                ui.Section(title="Thinking Mode", children=[
                    ui.Text(
                        "Controls extended thinking for AI models. "
                        "Some models (Nemotron, Qwen3) have a thinking mode that uses the "
                        "token budget for internal reasoning before responding. "
                        "When using BYOLLM with these models, disable thinking to ensure "
                        "tool calls work correctly — otherwise the model may exhaust tokens "
                        "on thinking and never produce actions.",
                        variant="caption",
                    ),
                    ui.Select(
                        param_name="thinking_mode",
                        value=thinking,
                        options=_THINKING_OPTIONS,
                    ),
                ]),
            ],
        ),
    ]


# ── Persona tab ───────────────────────────────────────────────────────

def build_persona_tab(app_id: str, settings: dict) -> list:
    p = settings.get("persona", {})
    return [
        ui.Form(
            action="save_ext_persona",
            submit_label="Save Persona",
            defaults={
                "app_id": app_id,
                "system_prompt_intake": p.get("system_prompt_intake", ""),
                "system_prompt_intelligence": p.get("system_prompt_intelligence", ""),
                "language": p.get("language", "auto"),
                "tone": p.get("tone", "formal"),
                "use_emojis": bool(p.get("use_emojis", False)),
                "cite_sources": bool(p.get("cite_sources", True)),
            },
            children=[
                ui.Text("System Prompt — Intake Mode", variant="caption"),
                ui.TextArea(
                    param_name="system_prompt_intake",
                    value=p.get("system_prompt_intake", ""),
                    placeholder="Leave empty for default",
                    rows=4,
                ),
                ui.Text("System Prompt — Intelligence Mode", variant="caption"),
                ui.TextArea(
                    param_name="system_prompt_intelligence",
                    value=p.get("system_prompt_intelligence", ""),
                    placeholder="Leave empty for default",
                    rows=4,
                ),
                ui.Text("Language", variant="caption"),
                ui.Select(
                    param_name="language",
                    value=p.get("language", "auto"),
                    options=_LANGUAGE_OPTIONS,
                ),
                ui.Text("Tone", variant="caption"),
                ui.Select(
                    param_name="tone",
                    value=p.get("tone", "formal"),
                    options=_TONE_OPTIONS,
                ),
                ui.Toggle(
                    label="Use emojis",
                    param_name="use_emojis",
                    value=bool(p.get("use_emojis", False)),
                ),
                ui.Toggle(
                    label="Cite document sources",
                    param_name="cite_sources",
                    value=bool(p.get("cite_sources", True)),
                ),
            ],
        ),
    ]
