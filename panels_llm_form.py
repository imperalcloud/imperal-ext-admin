"""Admin · LLM Config Form builder.

Builds the interactive Form for save_llm_config. Imported by panels_llm.py —
separate file for the 300L convention.

Layout — seven clearly-labelled categories (admin reads top → bottom):
  1. 🔌 Provider & Connection   — default provider/model/key/base-url + test
  2. 🔁 Failover                — fallback provider when primary is down
  3. 🧠 Per-Purpose Models      — override the model for each kernel LLM purpose
  4. 🎛 Per-Purpose AI Params   — temperature/top_p/penalties per purpose
  5. 📏 Per-Purpose Token Budgets — max_tokens cap per purpose (cost ceiling)
  6. Token Budget Controls      — kernel-internal char/window/depth knobs (TBC)
  7. 🚩 Feature Flags           — kernel LLM feature toggles

Every control's `param_name` maps 1:1 to a key the kernel actually reads
(verified against the live resolve-cascade — see _TOKEN_BUDGETS note). No dead
knobs: per-purpose max_tokens are read dynamically via
`config_resolver.resolve → cascade("max_tokens") → f"{purpose}_max_tokens"`.
"""
from __future__ import annotations

from imperal_sdk import ui
from panels_llm_form_tbc import build_tbc_section
from panels_llm_models import catalog_to_options, FALLBACK_CATALOG

_PROVIDERS = [
    {"value": "anthropic", "label": "Anthropic"},
    {"value": "openai", "label": "OpenAI"},
    {"value": "google", "label": "Google"},
    {"value": "custom", "label": "Custom (OpenAI-compatible)"},
]

# Model dropdown options are built per-render inside build_llm_form() from the
# live catalogue passed via model_catalog= (fetched from the provider APIs in
# panels_llm_models.fetch_model_catalog). No hardcoded model list lives here.


# ── Per-purpose catalogue ───────────────────────────────────────────────────
# (key, label, what-it-drives). `key` is the kernel LLM purpose; the model
# Select writes `{key}_model` and the AI-param inputs write `purpose_{key}_*`.
# Order = the order the purposes fire across a typical turn.
_PURPOSE_MODELS: list[tuple[str, str, str]] = [
    ("code", "Coding Brain · Webbee Code",
     "The model behind EVERY Webbee Code terminal turn and marathon "
     "(purpose=code). The single biggest intelligence lever — pick the "
     "strongest coding model you can afford. Blank = inherit the reasoning "
     "tier."),
    ("routing", "Routing · Intent Classifier",
     "Runs on EVERY user turn — detects intent, picks apps, plans the chain. "
     "The brain's first pass; a fast model here is cheapest (cost × every message)."),
    ("execution", "Execution · Tool Dispatch",
     "Drives extension tool-use and automation actions (purpose=execution). "
     "Favour an accurate model — it decides what actually runs."),
    ("navigate", "Navigate · Clarify & Offer",
     "Navigator prose: clarifying questions and proactive offers. Recognised "
     "override slot — inherits the default model when left blank."),
    ("chain_narrative", "Chain Narrator",
     "Weaves multi-step chain results into the final user-facing reply "
     "(purpose=chain_narrative)."),
    ("judge", "Judge · Anti-Fabrication",
     "Federal Gate-6 judge — reviews narrator output for fabricated "
     "entities/IDs before it reaches the user (purpose=judge)."),
    ("conversational", "Conversational · Chitchat",
     "Free-form chat and the empty-apps fallback reply (purpose=conversational)."),
    ("step_reclassify", "Step Reclassify · Two-Phase",
     "Per-step re-classifier that binds args from prior-step data before each "
     "write/destructive step. Default model: Claude Sonnet."),
    ("tool_picker", "Tool Picker · Chain Disambiguation",
     "Picks the tool when a chain step has no explicit action_plan "
     "(disambiguation fallback)."),
    ("action_narrator", "Action Narrator",
     "Turns post-action tool output into user-facing prose."),
]

# (param_name, label, default-hint, description). max_tokens cap per purpose.
# READ PATH (verified live): config_resolver.resolve() builds
# LLMConfig(max_tokens=cascade("max_tokens")); cascade pulls per_purpose_cfg =
# _extract_per_purpose_admin(store, purpose) which reads store[f"{purpose}_max_tokens"].
# So every row below is a live control. Blank = inherit quality_ceiling_tokens.
_TOKEN_BUDGETS: list[tuple[str, str, str, str]] = [
    ("routing_max_tokens", "Routing (Classifier)", "4096",
     "Cap for the every-turn classifier — must fit the whole chain/action-plan "
     "JSON. Raise to 8000+ for reliable 10-step plans."),
    ("execution_max_tokens", "Execution (Tool Dispatch)", "inherit",
     "Cap for extension-dispatch / automation execution calls."),
    ("navigate_max_tokens", "Navigate (Clarify & Offer)", "inherit",
     "Cap for navigator clarify / offer prose."),
    ("chain_narrative_max_tokens", "Chain Narrator", "8000",
     "Cap for the multi-step narrator — large so long mail bodies and 10-step "
     "summaries aren't truncated."),
    ("judge_max_tokens", "Judge (Anti-Fab)", "4096",
     "Cap for the anti-fabrication judge pass (purpose=judge)."),
    ("conversational_max_tokens", "Conversational (Chitchat)", "4096",
     "Cap for chitchat / empty-apps fallback replies."),
    ("step_reclassify_max_tokens", "Step Reclassify (Sonnet)", "8000",
     "Cap for the per-step reclassifier — large so long mail.body synthesis "
     "from tool JSON isn't truncated mid-emit."),
    ("tool_picker_max_tokens", "Tool Picker", "1024",
     "Cap for the chain-disambiguation tool pick."),
    ("chain_arg_refs_max_tokens", "Chain $REF Formatter", "2000",
     "Cap for the $REF→markdown formatter (renders content-shaped fields "
     "like mail.body / notes.content_text)."),
    ("semantic_verifier_max_tokens", "Semantic Verifier", "128",
     "Cap for the binary post-action yes/no schema-validity check (tiny by design)."),
    ("action_narrator_max_tokens", "Action Narrator", "1024",
     "Cap for post-tool prose narration."),
]


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
    # Federalization 2026-05-19 — new per-purpose model overrides.
    # Empty default = inherit global `model`. Caller fetches from
    # imperal:config:llm flat-keys (cfg.get("conversational_model"), etc.).
    conversational_model: str = "",
    step_reclassify_model: str = "",
    tool_picker_model: str = "",
    code_model: str = "",
    # G2 (2026-07-16): Webbee Code fallback pair — retry target when the
    # coding-brain primary errors. Blank = no fallback (off).
    code_fallback_model: str = "",
    action_narrator_model: str = "",
    # Live model catalogue fetched from the provider APIs (panels_llm_models.
    # fetch_model_catalog). None → resilience fallback. No hardcoded model list.
    model_catalog: dict | None = None,
) -> object:
    """Full save_llm_config Form — seven categories (see module docstring)."""

    # Filter providers by availability
    if available_providers:
        avail_set = set(available_providers)
        provider_opts = [
            {**p, "label": p["label"] + (" (no API key)" if p["value"] not in avail_set else "")}
            for p in _PROVIDERS
        ]
    else:
        provider_opts = _PROVIDERS

    # Model dropdown options from the live catalogue (fallback iff none supplied).
    _all_models, _provider_models = catalog_to_options(model_catalog or FALLBACK_CATALOG)

    _td = tenant_defaults or {}
    defaults = {
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "api_key": "",
        "code_model": code_model if code_model != model else "",
        # G2: fallback is an independent pair (not an inherit-from-default
        # override) — pass through verbatim; blank means "no fallback".
        "code_fallback_model": code_fallback_model,
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
    for _p, _label, _desc in _PURPOSE_MODELS:
        _slot = _purpose_ai.get(_p) or {}
        for _k in ("temperature", "top_p", "presence_penalty", "frequency_penalty"):
            _v = _slot.get(_k)
            defaults[f"purpose_{_p}_{_k}"] = "" if _v is None else str(_v)

    # ── Category 3: Per-Purpose Models ───────────────────────────
    model_children: list = [
        ui.Text(
            "Override the model used for each kernel LLM purpose. Leave on "
            "“Same as default” to inherit the provider/model above.",
            variant="caption",
        ),
    ]
    for key, label, desc in _PURPOSE_MODELS:
        model_children.extend([
            ui.Stack([
                ui.Text(label, variant="body"),
                ui.Text(desc, variant="caption"),
            ], gap=0),
            ui.Select(
                options=_all_models,
                value=defaults.get(f"{key}_model", ""),
                param_name=f"{key}_model",
                placeholder="Same as default",
            ),
        ])
        if key == "code":
            # G2 (2026-07-16): Webbee Code fallback model — one retry on this
            # model when the primary errors. Same Select pattern as the
            # per-purpose rows above; writes the flat code_fallback_model key
            # (provider auto-inferred on save). Blank = no fallback.
            model_children.extend([
                ui.Text(
                    "Fallback model — used only when the primary errors "
                    "(one retry). Blank = no fallback.",
                    variant="caption",
                ),
                ui.Select(
                    options=_all_models,
                    value=defaults.get("code_fallback_model", ""),
                    param_name="code_fallback_model",
                    placeholder="No fallback",
                ),
            ])
        model_children.append(ui.Divider())

    # ── Category 4: Per-Purpose AI Parameters ────────────────────
    aiparam_children: list = [
        ui.Text(
            "Fine-tune sampling per purpose. Leave blank to inherit "
            "(per-extension > per-purpose > global > provider default).",
            variant="caption",
        ),
    ]
    for key, label, _desc in _PURPOSE_MODELS:
        aiparam_children.extend([
            ui.Text(label, variant="body"),
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
            ui.Divider(),
        ])

    # ── Category 5: Per-Purpose Token Budgets (max_tokens) ───────
    budget_children: list = [
        ui.Text(
            "max_tokens cap for each LLM purpose. Lower = cheaper but risks "
            "truncated output; higher = reliable long output (mail body, 10-step "
            "plan) at more cost. Blank = inherit the global quality_ceiling_tokens.",
            variant="caption",
        ),
    ]
    for pname, label, hint, desc in _TOKEN_BUDGETS:
        budget_children.extend([
            ui.Stack([
                ui.Text(label, variant="body"),
                ui.Text(desc, variant="caption"),
            ], gap=0),
            ui.Input(
                placeholder=f"{hint} (default)",
                param_name=pname,
                value=str(defaults[pname]),
            ),
        ])

    return ui.Form(
        action="save_llm_config",
        submit_label="Save LLM Config",
        defaults=defaults,
        children=[
            # ── 1 · Provider & Connection ─────────────────────────
            ui.Section(title="\U0001f50c Provider & Connection", children=[
                ui.Text(
                    "The default LLM used everywhere unless a per-purpose or "
                    "per-extension override applies.",
                    variant="caption",
                ),
                ui.Text("Provider", variant="caption"),
                ui.Select(
                    options=provider_opts, value=provider,
                    param_name="provider",
                ),
                ui.Text("Model", variant="caption"),
                ui.Select(
                    options=_provider_models,
                    value=model, param_name="model",
                ),
                ui.Text("API Key", variant="caption"),
                ui.Input(
                    placeholder="sk-…  (leave blank to keep current)",
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

            # ── 2 · Failover ──────────────────────────────────────
            ui.Section(title="\U0001f501 Failover", collapsible=True, children=[
                ui.Text(
                    "Fallback provider used automatically when the primary is "
                    "unavailable or returns an error.",
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
                    options=_provider_models,
                    value=failover_model,
                    param_name="failover_model",
                    placeholder="Select failover model",
                ),
                ui.Text("Failover API Key", variant="caption"),
                ui.Input(
                    placeholder="sk-…  (leave blank to keep current)",
                    param_name="failover_api_key", value="",
                ),
                ui.Button(
                    label="Test Failover", variant="ghost",
                    on_click=ui.Call("__panel__tools",
                                     section="llm", run_test="failover"),
                ),
            ]),

            # ── 3 · Per-Purpose Models ────────────────────────────
            ui.Section(title="\U0001f9e0 Per-Purpose Models", collapsible=True,
                       children=model_children),

            # ── 4 · Per-Purpose AI Parameters ─────────────────────
            ui.Section(title="\U0001f39b Per-Purpose AI Parameters",
                       collapsible=True, children=aiparam_children),

            # ── 5 · Per-Purpose Token Budgets ─────────────────────
            ui.Section(title="\U0001f4cf Per-Purpose Token Budgets (max_tokens)",
                       collapsible=True, children=budget_children),

            # ── 6 · Token Budget Controls (TBC) ───────────────────
            build_tbc_section(defaults),

            # ── 7 · Feature Flags ─────────────────────────────────
            ui.Section(title="\U0001f6a9 Feature Flags (Kernel)", collapsible=True,
                       children=[
                ui.Text(
                    "Kernel-side LLM features that were previously env-var-only. "
                    "Changes apply within 60s (config cache TTL) — no worker "
                    "restart needed.",
                    variant="caption",
                ),
                ui.Toggle(
                    label="Step Reclassify (Two-Phase Sprint 1)",
                    value=bool(defaults["step_reclassify_enabled"]),
                    param_name="step_reclassify_enabled",
                ),
                ui.Text(
                    "When ON: each write/destructive chain step runs through a "
                    "focused Sonnet LLM that binds args from prior step results "
                    "before dispatch. Default ON (Sprint 2 prod).",
                    variant="caption",
                ),
                ui.Toggle(
                    label="Prose Judge (Federal Gate 6 anti-fabrication)",
                    value=bool(defaults["judge_enabled"]),
                    param_name="judge_enabled",
                ),
                ui.Text(
                    "When ON: every narrator output is reviewed by a judge LLM "
                    "that flags fabricated entities/IDs. Default OFF (opt-in). "
                    "Higher cost per chat turn.",
                    variant="caption",
                ),
            ]),
        ],
    )
