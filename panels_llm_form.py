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
        # Federalization 2026-05-19 \u2014 Sprint 2 #26+
        "conversational": "Chitchat / empty-apps fallback responses",
        "step_reclassify": "Two-Phase Sprint 1 per-step LLM (binds args from prior step data)",
        "tool_picker": "Chain executor disambiguation LLM (action_plan=null fallback)",
        "action_narrator": "Action data narrator (post-tool prose)",
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
    # Federalization 2026-05-19 \u2014 new per-purpose model overrides.
    # Empty default = inherit global `model`. Caller fetches from
    # imperal:config:llm flat-keys (cfg.get("conversational_model"), etc.).
    conversational_model: str = "",
    step_reclassify_model: str = "",
    tool_picker_model: str = "",
    action_narrator_model: str = "",
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
        # Federalization 2026-05-19 — new per-purpose model overrides
        "conversational_model": conversational_model if conversational_model != model else "",
        "step_reclassify_model": step_reclassify_model if step_reclassify_model != model else "",
        "tool_picker_model": tool_picker_model if tool_picker_model != model else "",
        "action_narrator_model": action_narrator_model if action_narrator_model != model else "",
        # Federalization 2026-05-19 — per-purpose max_tokens caps (was hardcoded)
        "routing_max_tokens": int(_td.get("routing_max_tokens", 4096)),
        "execution_max_tokens": int(_td.get("execution_max_tokens", 4096)),
        "navigate_max_tokens": int(_td.get("navigate_max_tokens", 4096)),
        "chain_narrative_max_tokens": int(_td.get("chain_narrative_max_tokens", 8000)),
        "judge_max_tokens": int(_td.get("judge_max_tokens", 4096)),
        "conversational_max_tokens": int(_td.get("conversational_max_tokens", 4096)),
        "step_reclassify_max_tokens": int(_td.get("step_reclassify_max_tokens", 8000)),
        "tool_picker_max_tokens": int(_td.get("tool_picker_max_tokens", 1024)),
        "chain_arg_refs_max_tokens": int(_td.get("chain_arg_refs_max_tokens", 2000)),
        "semantic_verifier_max_tokens": int(_td.get("semantic_verifier_max_tokens", 128)),
        "action_narrator_max_tokens": int(_td.get("action_narrator_max_tokens", 1024)),
        # Federalization 2026-05-19 — feature flags (was env-only)
        "step_reclassify_enabled": bool(_td.get("step_reclassify_enabled", True)),
        "judge_enabled": bool(_td.get("judge_enabled", False)),
        "failover_enabled": bool(failover_enabled),
        "failover_provider": failover_provider or "openai",
        "failover_model": failover_model,
        "failover_api_key": "",
        # Token Budget Controls (admin-only kernel-internal knobs)
        "narration_history_limit": int(_td.get("narration_history_limit", 12)),
        "confirmation_card_tokens": int(_td.get("confirmation_card_tokens", 300)),
        "judge_digest_chars": int(_td.get("judge_digest_chars", 8000)),
        "chain_prior_step_max_chars": int(_td.get("chain_prior_step_max_chars", 8000)),
        "chain_prior_total_max_chars": int(_td.get("chain_prior_total_max_chars", 64000)),
        "hub_dispatch_max_depth": int(_td.get("hub_dispatch_max_depth", 6)),
        # Token Budget Controls — full audit (TBC-FULL, 2026-04-29) — 7 admin-tunable max_tokens caps
        # (planner_max_tokens + structured_gen_max_tokens dropped 2026-05-13 — orphan UI; no kernel reader.)
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
        # Phase 16 (2026-05-17): orphans wired from System tab
        "narrator_structured_data_chars": int(_td.get("narrator_structured_data_chars", 8000)),
        "default_max_result_tokens": int(_td.get("default_max_result_tokens", 3000)),
        "list_truncate_items": int(_td.get("list_truncate_items", 50)),
        "classifier_fact_ledger_window": int(_td.get("classifier_fact_ledger_window", 20)),
        # P5 (2026-05-28): federal I-REF-CAP-PER-ARGS + I-REF-CAP-CROSS-TURN.
        "chain_max_refs_per_args": int(_td.get("chain_max_refs_per_args", 20)),
        "cross_turn_max_refs": int(_td.get("cross_turn_max_refs", 5)),
        "quality_ceiling_tokens": int(_td.get("quality_ceiling_tokens", 50000)),
        "string_truncate_chars": int(_td.get("string_truncate_chars", 1500)),
        "history_ttl_days": int(_td.get("history_ttl_days", 1)),
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
    for _p in ("routing", "execution", "navigate", "chain_narrative", "judge",
               "conversational", "step_reclassify", "tool_picker", "action_narrator"):
        _slot = _purpose_ai.get(_p) or {}
        for _k in ("temperature", "top_p", "presence_penalty", "frequency_penalty"):
            _v = _slot.get(_k)
            defaults[f"purpose_{_p}_{_k}"] = "" if _v is None else str(_v)

    # Per-purpose children with descriptions + LCU-4 AI param row
    purpose_children: list = []
    for key, label in [("routing", "Routing"), ("execution", "Execution"),
                       ("navigate", "Navigate"),
                       ("chain_narrative", "Chain Narrator"),
                       ("judge", "Judge"),
                       # Federalization 2026-05-19
                       ("conversational", "Conversational"),
                       ("step_reclassify", "Step Reclassify (Two-Phase Sprint 1)"),
                       ("tool_picker", "Tool Picker (Chain Disambiguation)"),
                       ("action_narrator", "Action Narrator")]:
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

            # ── Per-Purpose Token Budgets ─────────────────────────
            # Federalization 2026-05-19 (Sprint 2 fix #26+). Each kernel
            # LLM purpose has admin-tunable max_tokens cap. NULL = inherit
            # quality_ceiling_tokens. Replaces previously hardcoded values.
            ui.Section(title="Per-Purpose Token Budgets (max_tokens)",
                       collapsible=True, children=[
                ui.Text(
                    "max_tokens cap for each LLM purpose. Lower = cheaper but truncates output. "
                    "Higher = reliable long-output (mail body, 10-step chain plan, etc.) but more cost. "
                    "Empty = inherit quality_ceiling_tokens global cap.",
                    variant="caption",
                ),
                ui.Text("Routing (Classifier)", variant="caption"),
                ui.Input(
                    placeholder="4096 (default)",
                    param_name="routing_max_tokens",
                    value=str(defaults["routing_max_tokens"]),
                ),
                ui.Text("Execution (Extension dispatch)", variant="caption"),
                ui.Input(
                    placeholder="4096", param_name="execution_max_tokens",
                    value=str(defaults["execution_max_tokens"]),
                ),
                ui.Text("Navigate (Hub navigator)", variant="caption"),
                ui.Input(
                    placeholder="4096", param_name="navigate_max_tokens",
                    value=str(defaults["navigate_max_tokens"]),
                ),
                ui.Text("Chain Narrator", variant="caption"),
                ui.Input(
                    placeholder="8000", param_name="chain_narrative_max_tokens",
                    value=str(defaults["chain_narrative_max_tokens"]),
                ),
                ui.Text("Judge (anti-fab Gate 6)", variant="caption"),
                ui.Input(
                    placeholder="4096", param_name="judge_max_tokens",
                    value=str(defaults["judge_max_tokens"]),
                ),
                ui.Text("Conversational (chitchat)", variant="caption"),
                ui.Input(
                    placeholder="4096", param_name="conversational_max_tokens",
                    value=str(defaults["conversational_max_tokens"]),
                ),
                ui.Text("Step Reclassify (Two-Phase Sprint 1, Sonnet)",
                        variant="caption"),
                ui.Input(
                    placeholder="8000", param_name="step_reclassify_max_tokens",
                    value=str(defaults["step_reclassify_max_tokens"]),
                ),
                ui.Text("Tool Picker (chain disambiguation)", variant="caption"),
                ui.Input(
                    placeholder="1024", param_name="tool_picker_max_tokens",
                    value=str(defaults["tool_picker_max_tokens"]),
                ),
                ui.Text("Chain $REF Formatter (BUG-M markdown narration)",
                        variant="caption"),
                ui.Input(
                    placeholder="2000", param_name="chain_arg_refs_max_tokens",
                    value=str(defaults["chain_arg_refs_max_tokens"]),
                ),
                ui.Text("Semantic Verifier (binary post-action check)",
                        variant="caption"),
                ui.Input(
                    placeholder="128", param_name="semantic_verifier_max_tokens",
                    value=str(defaults["semantic_verifier_max_tokens"]),
                ),
                ui.Text("Action Narrator (post-tool prose)", variant="caption"),
                ui.Input(
                    placeholder="1024", param_name="action_narrator_max_tokens",
                    value=str(defaults["action_narrator_max_tokens"]),
                ),
            ]),

            # ── Feature Flags ─────────────────────────────────────
            # Federalization 2026-05-19 — env-only flags moved to admin Panel.
            ui.Section(title="Feature Flags (Kernel)", collapsible=True,
                       children=[
                ui.Text(
                    "Toggle kernel-side LLM features that were previously env-var-only. "
                    "Changes apply within 60s (config cache TTL) — no worker restart needed.",
                    variant="caption",
                ),
                ui.Toggle(
                    label="Step Reclassify (Two-Phase Sprint 1)",
                    value=bool(defaults["step_reclassify_enabled"]),
                    param_name="step_reclassify_enabled",
                ),
                ui.Text(
                    "When ON: each write/destructive chain step runs through a "
                    "focused Sonnet LLM that binds args from prior step results before "
                    "dispatch. Replaces legacy _apply_target_hint_post_ref + "
                    "_verify_user_named_container_intent path. Default ON (Sprint 2 prod).",
                    variant="caption",
                ),
                ui.Toggle(
                    label="Prose Judge (Federal Gate 6 anti-fabrication)",
                    value=bool(defaults["judge_enabled"]),
                    param_name="judge_enabled",
                ),
                ui.Text(
                    "When ON: every narrator output is reviewed by a judge LLM that "
                    "flags fabricated entities/IDs. Default OFF (opt-in). Higher cost "
                    "per chat turn.",
                    variant="caption",
                ),
            ]),

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
