"""Admin · LLM Config Form builder.

Builds the interactive Form for save_llm_config.
Imported by panels_llm.py — separate file for 300L rule.

Structure matches React LLMConfigTab:
1. Default Provider — provider + model + API key + base URL + test
2. Per-Purpose Models — routing/execution/navigate selects
3. Failover — enable toggle + provider + model + API key + test
"""
from __future__ import annotations

from imperal_sdk import ui
from panels_llm_form_tbc import build_tbc_section

_PROVIDERS = [
    {"value": "anthropic", "label": "Anthropic"},
    {"value": "openai", "label": "OpenAI"},
    {"value": "google", "label": "Google"},
    {"value": "custom", "label": "Custom (OpenAI-compatible)"},
]

_MODELS = {
    "anthropic": [
        "claude-opus-4-7",
        "claude-sonnet-4-6",
        "claude-haiku-4-5-20251001",
        "claude-sonnet-4-20250514",
        "claude-opus-4-20250514",
    ],
    "openai": [
        "gpt-5",
        "gpt-5-mini",
        "gpt-5-nano",
        "o3",
        "gpt-4.1",
        "gpt-4.1-mini",
        "gpt-4.1-nano",
        "gpt-4o",
        "gpt-4o-mini",
    ],
    "google": ["gemini-2.5-pro", "gemini-2.5-flash"],
}

ALL_MODELS: list[dict] = [{"value": "", "label": "\u2014 Same as default \u2014"}]
for _prov, _models in _MODELS.items():
    for _m in _models:
        ALL_MODELS.append({"value": _m, "label": f"{_m} ({_prov})"})

# Full model list (without "same as default") for default provider + failover
PROVIDER_MODELS: list[dict] = []
for _prov, _models in _MODELS.items():
    for _m in _models:
        PROVIDER_MODELS.append({"value": _m, "label": f"{_m} ({_prov})"})


def _purpose_description(key: str) -> str:
    """React-matching purpose descriptions."""
    return {
        "routing": "Intent detection & hub routing \u2014 fast/cheap",
        "execution": "Tool use & task execution \u2014 accurate",
        "navigate": "Conversational replies & navigation",
        "chain_narrative": "Chain narrator that weaves multi-step results into final user response",
        "judge": "Quality judge for narration verification",
    }.get(key, "")


def build_llm_form(
    provider: str,
    model: str,
    base_url: str,
    routing_model: str,
    execution_model: str,
    navigate_model: str,
    chain_narrative_model: str,
    judge_model: str,
    failover_enabled: bool,
    failover_provider: str,
    failover_model: str,
    available_providers: list[str] | None = None,
    tenant_defaults: dict | None = None,
    purpose_ai_params: dict | None = None,
) -> object:
    """Full save_llm_config Form matching React LLMConfigTab."""

    # Filter providers by availability
    if available_providers:
        avail_set = set(available_providers)
        provider_opts = [
            {**p, "label": p["label"] + (" (no API key)" if p["value"] not in avail_set else "")}
            for p in _PROVIDERS
        ]
    else:
        provider_opts = _PROVIDERS

    _td = tenant_defaults or {}
    defaults = {
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "api_key": "",
        "routing_model": routing_model if routing_model != model else "",
        "execution_model": execution_model if execution_model != model else "",
        "navigate_model": navigate_model if navigate_model != model else "",
        "chain_narrative_model": chain_narrative_model if chain_narrative_model != model else "",
        "judge_model": judge_model if judge_model != model else "",
        "failover_enabled": bool(failover_enabled),
        "failover_provider": failover_provider or "openai",
        "failover_model": failover_model,
        "failover_api_key": "",
        # Token Budget Controls (admin-only kernel-internal knobs)
        "narration_history_limit": int(_td.get("narration_history_limit", 12)),
        "confirmation_card_tokens": int(_td.get("confirmation_card_tokens", 300)),
        "judge_digest_chars": int(_td.get("judge_digest_chars", 8000)),
        "planner_max_tokens": int(_td.get("planner_max_tokens", 300)),
        "chain_prior_step_max_chars": int(_td.get("chain_prior_step_max_chars", 8000)),
        "chain_prior_total_max_chars": int(_td.get("chain_prior_total_max_chars", 64000)),
        # Token Budget Controls — full audit (TBC-FULL, 2026-04-29) — 8 admin-tunable max_tokens caps
        "structured_gen_max_tokens": int(_td.get("structured_gen_max_tokens", 8192)),
        "automation_main_max_tokens": int(_td.get("automation_main_max_tokens", 4096)),
        "automation_condition_max_tokens": int(_td.get("automation_condition_max_tokens", 50)),
        "intent_classifier_planner_max_tokens": int(_td.get("intent_classifier_planner_max_tokens", 4096)),
        "prose_judge_max_tokens": int(_td.get("prose_judge_max_tokens", 4096)),
        "system_handlers_max_tokens": int(_td.get("system_handlers_max_tokens", 4096)),
        "responses_judge_max_tokens": int(_td.get("responses_judge_max_tokens", 4096)),
        "rule_engine_max_tokens": int(_td.get("rule_engine_max_tokens", 50)),
        # Default user limits (admin sets tenant default)
        "default_max_response_tokens": int(_td.get("max_response_tokens", 1024)),
        "default_max_tool_rounds": int(_td.get("max_tool_rounds", 10)),
        "default_routing_context": int(_td.get("routing_context", 12)),
        "default_kav_max_retries": int(_td.get("kav_max_retries", 2)),
        "default_confirmation_enabled": bool(_td.get("confirmation_enabled", False)),
    }

    # ── Per-purpose AI params (LCU-4, 2026-04-30) ────────────────
    # `purpose_ai_params` carries `{purpose_name: {temperature, top_p,
    # presence_penalty, frequency_penalty}}`. Caller passes the `purpose`
    # subtree of `imperal:config:llm` directly (kernel cascade format 1).
    # Falls back to `tenant_defaults["purpose_ai_params"]` for tests.
    # Flat form keys: `purpose_{name}_{param}`. Empty string == "inherit".
    if isinstance(purpose_ai_params, dict):
        _purpose_ai = purpose_ai_params
    else:
        _purpose_ai = (_td.get("purpose_ai_params") or {}) if isinstance(_td, dict) else {}
    for _p in ("routing", "execution", "navigate", "chain_narrative", "judge"):
        _slot = _purpose_ai.get(_p) or {}
        for _k in ("temperature", "top_p", "presence_penalty", "frequency_penalty"):
            _v = _slot.get(_k)
            defaults[f"purpose_{_p}_{_k}"] = "" if _v is None else str(_v)

    # Per-purpose children with descriptions + LCU-4 AI param row
    purpose_children: list = []
    for key, label in [("routing", "Routing"), ("execution", "Execution"),
                       ("navigate", "Navigate"),
                       ("chain_narrative", "Chain Narrator"),
                       ("judge", "Judge")]:
        val = defaults[f"{key}_model"]
        # AI param caption row + 4 inputs (LCU-4, 2026-04-30).
        # Empty string means "inherit" — kernel cascade falls through to
        # global / provider default. Numeric strings are parsed by save handler.
        ai_row = [
            ui.Text(
                "AI params (leave blank to inherit; per-extension > per-purpose > global)",
                variant="caption",
            ),
            ui.Stack([
                ui.Stack([
                    ui.Text("Temperature (0.0 – 2.0)", variant="caption"),
                    ui.Input(
                        param_name=f"purpose_{key}_temperature",
                        value=defaults[f"purpose_{key}_temperature"],
                        placeholder="inherit",
                    ),
                ], gap=0),
                ui.Stack([
                    ui.Text("Top P (0.0 – 1.0)", variant="caption"),
                    ui.Input(
                        param_name=f"purpose_{key}_top_p",
                        value=defaults[f"purpose_{key}_top_p"],
                        placeholder="inherit",
                    ),
                ], gap=0),
                ui.Stack([
                    ui.Text("Presence penalty (-2.0 – 2.0)", variant="caption"),
                    ui.Input(
                        param_name=f"purpose_{key}_presence_penalty",
                        value=defaults[f"purpose_{key}_presence_penalty"],
                        placeholder="inherit",
                    ),
                ], gap=0),
                ui.Stack([
                    ui.Text("Frequency penalty (-2.0 – 2.0)", variant="caption"),
                    ui.Input(
                        param_name=f"purpose_{key}_frequency_penalty",
                        value=defaults[f"purpose_{key}_frequency_penalty"],
                        placeholder="inherit",
                    ),
                ], gap=0),
            ], direction="h", gap=1, wrap=True),
        ]
        purpose_children.extend([
            ui.Stack([
                ui.Text(label, variant="body"),
                ui.Text(_purpose_description(key), variant="caption"),
            ], gap=0),
            ui.Select(
                options=ALL_MODELS,
                value=val,
                param_name=f"{key}_model",
                placeholder="Same as default",
            ),
            *ai_row,
            ui.Divider(),
        ])

    return ui.Form(
        action="save_llm_config",
        submit_label="Save LLM Config",
        defaults=defaults,
        children=[
            # ── Default Provider ──────────────────────────────────
            ui.Section(title="Default Provider", children=[
                ui.Text("Provider", variant="caption"),
                ui.Select(
                    options=provider_opts, value=provider,
                    param_name="provider",
                ),
                ui.Text("Model", variant="caption"),
                ui.Select(
                    options=PROVIDER_MODELS if PROVIDER_MODELS else ALL_MODELS,
                    value=model, param_name="model",
                ),
                ui.Text("API Key", variant="caption"),
                ui.Input(
                    placeholder="sk-\u2026  (leave blank to keep current)",
                    param_name="api_key", value="",
                ),
                ui.Text("Base URL (custom providers only)", variant="caption"),
                ui.Input(
                    placeholder="https://api.example.com/v1",
                    param_name="base_url", value=base_url,
                ),
                ui.Button(
                    label="Test Connection", variant="ghost",
                    on_click=ui.Call("__panel__tools",
                                     section="llm", run_test="main"),
                ),
            ]),

            # ── Per-Purpose Models ────────────────────────────────
            ui.Section(title="Per-Purpose Models", collapsible=True,
                       children=purpose_children),

            # ── Failover ──────────────────────────────────────────
            ui.Section(title="Failover", collapsible=True, children=[
                ui.Text(
                    "Fallback provider when primary is unavailable",
                    variant="caption",
                ),
                ui.Toggle(
                    label="Enable Failover" if not failover_enabled
                    else "Failover enabled",
                    value=bool(failover_enabled),
                    param_name="failover_enabled",
                ),
                ui.Text("Failover Provider", variant="caption"),
                ui.Select(
                    options=provider_opts, value=failover_provider or "openai",
                    param_name="failover_provider",
                    placeholder="Select failover provider",
                ),
                ui.Text("Failover Model", variant="caption"),
                ui.Select(
                    options=PROVIDER_MODELS if PROVIDER_MODELS else ALL_MODELS,
                    value=failover_model,
                    param_name="failover_model",
                    placeholder="Select failover model",
                ),
                ui.Text("Failover API Key", variant="caption"),
                ui.Input(
                    placeholder="sk-\u2026  (leave blank to keep current)",
                    param_name="failover_api_key", value="",
                ),
                ui.Button(
                    label="Test Failover", variant="ghost",
                    on_click=ui.Call("__panel__tools",
                                     section="llm", run_test="failover"),
                ),
            ]),

            build_tbc_section(defaults),
        ],
    )
