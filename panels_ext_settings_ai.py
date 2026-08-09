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

# The four model slots, as data: a new slot shows up in the tab and in the
# "what does this app pin" header automatically instead of being hand-wired.
_MODEL_SLOT_FIELDS: tuple[tuple[str, str], ...] = (
    ("primary_model", "Primary Model"),
    ("intake_model", "Intake Model"),
    ("analysis_model", "Analysis Model"),
    ("router_model", "Router Model"),
)


def _model_options(inherited: str) -> list[dict]:
    """Model options whose blank entry names what blank actually resolves to.

    "— Default —" alone gave no clue which model the platform would pick, so an
    admin could not tell what they were opting into by leaving it blank.
    """
    label = f"— Inherit platform default ({inherited}) —" if inherited else "— Inherit platform default —"
    return [{"value": "", "label": label}] + _MODEL_OPTIONS[1:]


def _thinking_options(inherited: str) -> list[dict]:
    """Thinking-mode options with an explicit inherit entry.

    Blank is the inherit value; "auto" is a real, stored choice that happens to
    mean "platform decides". Keeping them distinct is what lets an app stop
    overriding this key at all.
    """
    label = f"— Inherit platform default ({inherited}) —" if inherited else "— Inherit platform default —"
    return [{"value": "", "label": label}] + _THINKING_OPTIONS


# ── AI Models tab ─────────────────────────────────────────────────────

def build_models_tab(app_id: str, settings: dict, own_models: dict | None = None) -> list:
    """AI Models tab.

    `settings` is the RESOLVED view (platform defaults already merged in);
    `own_models` is what this app actually stored, or None when that could not
    be read. The difference matters: rendering the resolved value into a
    Select's `value=` makes an inherited default indistinguishable from a
    deliberate pin, which is why every app looked pre-configured. Anything the
    app did not choose is therefore shown as a hint ("Inherited: X"), never as
    a selection.
    """
    m = settings.get("models", {}) or {}
    # own is the authoritative "what did this app actually choose" map. When the
    # unresolved read failed we fall back to the resolved view — the old,
    # imprecise behaviour — rather than claiming everything inherits.
    own = own_models if isinstance(own_models, dict) else m
    unresolved = isinstance(own_models, dict)

    def _own(key: str) -> str:
        """The app's OWN value for key, or '' when it inherits."""
        return str(own.get(key) or "").strip()

    def _inherited(key: str) -> str:
        """What the platform resolves key to, for display only."""
        return str(m.get(key) or "").strip()

    def _hint(key: str, fallback: str = "inherit") -> str:
        inherited = _inherited(key)
        return f"Inherited: {inherited}" if inherited else fallback

    pinned_slots = [s for s, _ in _MODEL_SLOT_FIELDS if _own(s)]
    legacy_params = [k for k in ("temperature", "max_tokens", "thinking_mode") if _own(k)]

    header: list = []
    if unresolved and not pinned_slots and not legacy_params:
        header = [
            ui.Alert(
                title="Following the system defaults",
                message=(
                    "This app pins nothing of its own — every slot below "
                    "inherits the platform cascade and follows it "
                    "automatically. The greyed-out values are what the "
                    "platform currently resolves to, not stored choices."
                ),
                type="info",
            ),
        ]
    elif unresolved:
        parts = []
        if pinned_slots:
            parts.append(
                "pins " + ", ".join(sorted(pinned_slots))
            )
        if legacy_params:
            parts.append(
                "overrides " + ", ".join(sorted(legacy_params))
            )
        header = [
            ui.Alert(
                title="This app overrides the system defaults",
                message=(
                    "This app " + " and ".join(parts) + ". Pinned values do "
                    "NOT follow the platform default, and a pinned model bills "
                    "at its own tier. Blank a field to hand it back to the "
                    "platform."
                ),
                type="warning",
            ),
        ]

    return header + [
        ui.Form(
            action="save_ext_models",
            submit_label="Save AI Models",
            defaults={
                "app_id": app_id,
                "primary_model": _own("primary_model"),
                "intake_model": _own("intake_model"),
                "analysis_model": _own("analysis_model"),
                "router_model": _own("router_model"),
                "temperature": _own("temperature"),
                "max_tokens": _own("max_tokens"),
                "top_p": _own("top_p"),
                "presence_penalty": _own("presence_penalty"),
                "frequency_penalty": _own("frequency_penalty"),
                "thinking_mode": _own("thinking_mode"),
            },
            children=[
                ui.Text("Primary Model", variant="caption"),
                ui.Select(
                    param_name="primary_model",
                    value=_own("primary_model"),
                    options=_model_options(_inherited("primary_model")),
                ),
                ui.Text("Intake Model", variant="caption"),
                ui.Select(
                    param_name="intake_model",
                    value=_own("intake_model"),
                    options=_model_options(_inherited("intake_model")),
                ),
                ui.Text("Analysis Model", variant="caption"),
                ui.Select(
                    param_name="analysis_model",
                    value=_own("analysis_model"),
                    options=_model_options(_inherited("analysis_model")),
                ),
                ui.Text("Router Model", variant="caption"),
                ui.Select(
                    param_name="router_model",
                    value=_own("router_model"),
                    options=_model_options(_inherited("router_model")),
                ),
                ui.Text("Temperature (0 — 2; blank to inherit)", variant="caption"),
                ui.Input(
                    param_name="temperature",
                    value=_own("temperature"),
                    placeholder=_hint("temperature", "inherit"),
                ),
                ui.Text("Max Tokens (256 — 8192; blank to inherit)", variant="caption"),
                ui.Input(
                    param_name="max_tokens",
                    value=_own("max_tokens"),
                    placeholder=_hint("max_tokens", "inherit"),
                ),
                # LCU-4 per-extension AI params (2026-04-30) — empty = inherit.
                # Cascade: per-extension > per-purpose > global > provider default.
                ui.Text("Top P (0.0 — 1.0; blank to inherit)", variant="caption"),
                ui.Input(
                    param_name="top_p",
                    value=_own("top_p"),
                    placeholder="inherit",
                ),
                ui.Text("Presence penalty (-2.0 — 2.0; blank to inherit)", variant="caption"),
                ui.Input(
                    param_name="presence_penalty",
                    value=_own("presence_penalty"),
                    placeholder="inherit",
                ),
                ui.Text("Frequency penalty (-2.0 — 2.0; blank to inherit)", variant="caption"),
                ui.Input(
                    param_name="frequency_penalty",
                    value=_own("frequency_penalty"),
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
                        value=_own("thinking_mode"),
                        options=_thinking_options(_inherited("thinking_mode")),
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
