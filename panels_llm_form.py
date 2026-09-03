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
from panels_llm_form_coding_thread import build_coding_thread_section
from panels_llm_form_tiers import build_tiers_section
from panels_llm_form_automation import build_automation_section
from panels_llm_form_voice import build_voice_section
from panels_llm_models import catalog_to_options, FALLBACK_CATALOG

_PROVIDERS = [
    {"value": "anthropic", "label": "Anthropic"},
    {"value": "openai", "label": "OpenAI"},
    {"value": "openrouter", "label": "OpenRouter (Multi-Vendor)"},
    {"value": "qwen", "label": "Qwen (DashScope)"},
    {"value": "kimi", "label": "Kimi (Moonshot)"},
    {"value": "zhipu", "label": "GLM (Zhipu z.ai)"},
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
    ("resolve", "Universal Brain · Reasoning Tier",
     "The brain's own reasoning model (purpose=resolve) — the agentic loop "
     "behind chat AND every unattended automation run. It was configurable "
     "all along (flat resolve_model key) but had no field here, so the model "
     "actually doing the thinking was invisible in this form. Blank = "
     "inherit the default model above."),
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
    # Coding brain (purpose=code). Declared on SaveLlmConfigParams and read
    # by the SAME generic _extract_per_purpose_admin flat-key cascade as
    # every other row above (store[f"{purpose}_max_tokens"]) -- it just had
    # no row here, so a saved value was silently discarded (nothing rendered
    # it, so nothing ever posted it to the handler).
    ("code_max_tokens", "Coding Brain (Webbee Code)", "inherit",
     "Cap for every Webbee Code terminal/marathon turn. Raise for long "
     "diffs and multi-file edits."),
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
    failover_base_url: str = "",
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
    # Webbee Code model tiers (2026-07-30): Webbee Smart/SuperSmart/UltraSmart,
    # each a full admin-owned (primary, fallback) pair. Blank primary = tier
    # falls through to code_model above (never a broken/unset tier).
    webbeesmart_model: str = "",
    webbeesmart_fallback_model: str = "",
    # Universal Brain reasoning tier (purpose="resolve") -- settable all along
    # through the flat resolve_model key, but with no field here until now.
    resolve_model: str = "",
    # Brain failover pair (2026-08-08): the retry target for chat AND every
    # unattended automation run. Independent pair like code_fallback_model --
    # blank means "no admin override" (kernel keeps its reasoning-grade default).
    resolve_fallback_model: str = "",
    supersmart_model: str = "",
    supersmart_fallback_model: str = "",
    ultrasmart_model: str = "",
    ultrasmart_fallback_model: str = "",
    # Live model catalogue fetched from the provider APIs (panels_llm_models.
    # fetch_model_catalog). None → resilience fallback. No hardcoded model list.
    model_catalog: dict | None = None,
    # I-CODING-THREAD-COMPACTION-ADMIN-TUNABLE (2026-07-31): the 6 coding-thread
    # compaction knobs live in imperal:config:llm (cfg), NOT tenant_defaults —
    # panels_llm.py reads them straight off cfg and passes them here.
    coding_thread_config: dict | None = None,
    # ORPHAN READER FIX (2026-08-18): knowledge_pick_max_tokens lives in
    # imperal:config:llm (cfg) like the coding-thread knobs above — the kernel
    # reads it through the SAME get_admin_llm_config_field cascade, so it must
    # NOT be routed via tenant_defaults. panels_llm.py passes cfg straight in.
    knowledge_config: dict | None = None,
    # ORPHAN READER FIXES (2026-08-18): the kernel feature flags below live in
    # imperal:config:llm (cfg) -- the store get_admin_llm_config_field reads and
    # the store fn_save_llm_config writes. NOT tenant_defaults.
    kernel_flags_config: dict | None = None,
    # BUG FIX (2026-08-28): the 11 per-purpose max_tokens caps below are
    # SAVED into imperal:config:llm by the generic save loop (they are not
    # in handlers_llm.py's skip_fields) -- the SAME store the kernel's
    # config_resolver.py cascade actually reads via
    # _extract_per_purpose_admin(config_store, purpose). But this form was
    # displaying their "current value" from tenant_defaults (a DIFFERENT
    # store: Postgres-backed /v1/admin/tenant-defaults) -- an admin who
    # saved e.g. routing_max_tokens=8000 saw the OLD number reappear on
    # next load, looking like the save silently failed. Same bug class as
    # the step_reclassify_enabled/judge_enabled fix above; those two were
    # caught in the 2026-08-18 orphan-reader audit, these 11 were not.
    # panels_llm.py passes cfg straight in, like kernel_flags_config.
    purpose_max_tokens_config: dict | None = None,
    # Voice / STT (Whisper) (2026-08-29): blank stt_model = use the
    # gateway's own platform default (whisper-1). Read by
    # app.voice.service.transcribe() through get_llm_config().
    stt_provider: str = "",
    stt_model: str = "",
    stt_api_key: str = "",
    stt_base_url: str = "",
    # Live STT model catalogue fetched from the STT provider's own API using
    # the admin's BYOK key (panels_llm_models.fetch_stt_model_catalog). None
    # -> the section falls back to a plain text Model input (no dropdown).
    stt_model_catalog: list[str] | None = None,
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

    # Ensure custom/saved models that are not in catalog are included in dropdown options
    # so ui.Select doesn't render empty or drop the selection on client reload.
    if model and not any(opt.get("value") == model for opt in _provider_models):
        custom_opt = {"value": model, "label": f"{model} (current / custom)"}
        _provider_models.insert(0, dict(custom_opt))
        _all_models.insert(1, dict(custom_opt))

    if failover_model and not any(opt.get("value") == failover_model for opt in _provider_models):
        custom_fo_opt = {"value": failover_model, "label": f"{failover_model} (current / custom)"}
        _provider_models.insert(0, dict(custom_fo_opt))
        _all_models.insert(1, dict(custom_fo_opt))

    is_custom_primary = bool(model and (model not in (model_catalog or {}).get(provider, [])))
    is_custom_fo = bool(failover_model and (failover_model not in (model_catalog or {}).get(failover_provider or "openai", [])))

    _td = tenant_defaults or {}
    _kf = kernel_flags_config or {}
    _pmt = purpose_max_tokens_config or {}
    defaults = {
        "provider": provider,
        "model": model,
        "custom_model": model if is_custom_primary else "",
        "base_url": base_url,
        "api_key": "",
        "code_model": code_model if code_model != model else "",
        # G2: fallback is an independent pair (not an inherit-from-default
        # override) — pass through verbatim; blank means "no fallback".
        "code_fallback_model": code_fallback_model,
        # Webbee Code model tiers (2026-07-30): each tier's primary follows
        # the SAME "blank if same as global default" convention as code_model
        # above; each fallback is an independent pair (verbatim, like
        # code_fallback_model) -- blank simply means "no fallback set yet".
        "webbeesmart_model": webbeesmart_model if webbeesmart_model != model else "",
        "webbeesmart_fallback_model": webbeesmart_fallback_model,
        # Universal Brain reasoning tier.
        # 2026-08-08: written VERBATIM, NOT blanked when it equals the global
        # model. For purpose="resolve" a blank key does NOT mean "use the
        # global default" -- the kernel cascade (step 3c) makes the brain
        # inherit whatever the ROUTING model happens to be, so blanking it
        # silently re-priced every automation run whenever routing changed.
        # An explicit pick must stay explicit.
        "resolve_model": resolve_model,
        "resolve_fallback_model": resolve_fallback_model,
        "supersmart_model": supersmart_model if supersmart_model != model else "",
        "supersmart_fallback_model": supersmart_fallback_model,
        "ultrasmart_model": ultrasmart_model if ultrasmart_model != model else "",
        "ultrasmart_fallback_model": ultrasmart_fallback_model,
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
        # BUG FIX (2026-08-28, see purpose_max_tokens_config note above): read
        # cfg (_pmt) FIRST -- it is where fn_save_llm_config actually writes
        # these -- keep _td as the fallback so anything an older build wrote
        # there still renders instead of silently reverting to the hardcoded
        # number.
        "routing_max_tokens": int(_pmt.get("routing_max_tokens", _td.get("routing_max_tokens", 4096))),
        "execution_max_tokens": int(_pmt.get("execution_max_tokens", _td.get("execution_max_tokens", 4096))),
        "navigate_max_tokens": int(_pmt.get("navigate_max_tokens", _td.get("navigate_max_tokens", 4096))),
        "chain_narrative_max_tokens": int(_pmt.get("chain_narrative_max_tokens", _td.get("chain_narrative_max_tokens", 8000))),
        "judge_max_tokens": int(_pmt.get("judge_max_tokens", _td.get("judge_max_tokens", 4096))),
        "conversational_max_tokens": int(_pmt.get("conversational_max_tokens", _td.get("conversational_max_tokens", 4096))),
        "step_reclassify_max_tokens": int(_pmt.get("step_reclassify_max_tokens", _td.get("step_reclassify_max_tokens", 8000))),
        "tool_picker_max_tokens": int(_pmt.get("tool_picker_max_tokens", _td.get("tool_picker_max_tokens", 1024))),
        "chain_arg_refs_max_tokens": int(_pmt.get("chain_arg_refs_max_tokens", _td.get("chain_arg_refs_max_tokens", 2000))),
        "semantic_verifier_max_tokens": int(_pmt.get("semantic_verifier_max_tokens", _td.get("semantic_verifier_max_tokens", 128))),
        "action_narrator_max_tokens": int(_pmt.get("action_narrator_max_tokens", _td.get("action_narrator_max_tokens", 1024))),
        # Coding brain (purpose=code) -- NEW row, same cfg-first read as the
        # others above; no tenant_defaults fallback exists since this key
        # never had a form row before this fix (nothing legacy to read back).
        "code_max_tokens": int(_pmt.get("code_max_tokens", 0)) or "",
        # Federalization 2026-05-19 — feature flags (was env-only)
        # FLAG READ PATH (fixed 2026-08-18): these two are SAVED into
        # imperal:config:llm (they are not in the handler's skip_fields), but
        # were READ back from tenant_defaults -- so a saved value never showed
        # up in the form again. Read cfg FIRST, keep _td as the fallback so
        # anything an older build wrote there still renders.
        "step_reclassify_enabled": bool(_kf.get("step_reclassify_enabled", _td.get("step_reclassify_enabled", True))),
        "judge_enabled": bool(_kf.get("judge_enabled", _td.get("judge_enabled", False))),
        # Orphan flags wired 2026-08-18. Fallbacks mirror the KERNEL's own
        # defaults so a blank store renders real behaviour, not a guess:
        #   hub_brain_first_enabled -> True  (activities/brain_first.py)
        #   panel_diet_enabled      -> True  (activities/agentic_catalog.py)
        #   frame_v2_enabled        -> False (dual-emit is opt-in)
        "hub_brain_first_enabled": bool(_kf.get("hub_brain_first_enabled", True)),
        "panel_diet_enabled": bool(_kf.get("panel_diet_enabled", True)),
        "frame_v2_enabled": bool(_kf.get("frame_v2_enabled", False)),
        "failover_enabled": bool(failover_enabled),
        "failover_provider": failover_provider or "openai",
        "failover_model": failover_model,
        "failover_custom_model": failover_model if is_custom_fo else "",
        "failover_base_url": failover_base_url,
        "failover_api_key": "",
        # Voice / STT (Whisper) BYOK (2026-08-29 owner report, pass 2): "чтобы
        # SST Provider можно было настроить, чтобы я свой ключ от любого
        # провайдера мог юзать". api_key is write-only — the value here is
        # already masked by the gateway's read path (or "" if never set), so
        # a re-save with the field untouched round-trips the mask back and
        # handlers_llm.py's stt-merge block treats it as "keep current".
        "stt_provider": stt_provider or "openai",
        "stt_model": stt_model,
        "stt_api_key": stt_api_key,
        "stt_base_url": stt_base_url,
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
        # I-CODING-THREAD-COMPACTION-ADMIN-TUNABLE (2026-07-31): read from cfg
        # (imperal:config:llm), not tenant_defaults -- see coding_thread_config= above.
        "coding_thread_window_budget_chars": int((coding_thread_config or {}).get("coding_thread_window_budget_chars", 250000)),
        "coding_thread_keep_recent": int((coding_thread_config or {}).get("coding_thread_keep_recent", 20)),
        "coding_thread_input_cap": int((coding_thread_config or {}).get("coding_thread_input_cap", 120000)),
        "coding_thread_max_rounds": int((coding_thread_config or {}).get("coding_thread_max_rounds", 12)),
        "coding_thread_time_budget_s": int((coding_thread_config or {}).get("coding_thread_time_budget_s", 100)),
        "coding_thread_fold_max_tokens": int((coding_thread_config or {}).get("coding_thread_fold_max_tokens", 24576)),
        # Kernel constant is 49152 (activities/coding_thread.py:181). The panel
        # must show what the kernel RUNS with, never a prettier number.
        "coding_thread_fold_retry_max_tokens": int((coding_thread_config or {}).get("coding_thread_fold_retry_max_tokens", 49152)),
        # Docs router budget. Fallback mirrors the kernel's own
        # _DEFAULT_PICK_MAX_TOKENS (200) so a blank store renders the value the
        # kernel actually runs with — not an aspirational number.
        "knowledge_pick_max_tokens": int((knowledge_config or {}).get("knowledge_pick_max_tokens", 200)),
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
        if key == "resolve":
            # Brain failover (2026-08-08): the retry target for chat AND every
            # unattended automation run. Writes the flat resolve_fallback_model
            # key (provider auto-inferred on save); blank = kernel default.
            model_children.extend([
                ui.Text(
                    "Failover model — used only when the brain's primary "
                    "errors (one retry). Applies to every automation run. "
                    "Blank = platform reasoning default.",
                    variant="caption",
                ),
                ui.Select(
                    options=_all_models,
                    value=defaults.get("resolve_fallback_model", ""),
                    param_name="resolve_fallback_model",
                    placeholder="Platform default",
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
            # ── 0 · Automations map (read-only) ───────────────────
            # Placed FIRST deliberately: it is the "you are here" for the
            # whole tab. An admin who came to tune automations reads this,
            # learns which knob matters and where it lives, and only then
            # scrolls into the generic sections below. It renders no inputs,
            # so it cannot collide with the write controls it points at.
            # Values come from `defaults`, which already holds every knob this
            # map displays — so no extra config plumbing is needed here.
            build_automation_section(defaults),

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
                ui.Text("Model (select from catalog)", variant="caption"),
                ui.Select(
                    options=_provider_models,
                    value=model, param_name="model",
                ),
                ui.Text("Custom / Manual Model ID (optional — overrides dropdown if entered)", variant="caption"),
                ui.Input(
                    placeholder="e.g. z-ai/glm-5.3 or custom-model-name",
                    param_name="custom_model", value=defaults.get("custom_model", ""),
                ),
                ui.Text("API Key — for the provider selected above", variant="caption"),
                ui.Input(
                    placeholder="sk-…  (leave blank to keep current)",
                    param_name="api_key", value="",
                ),
                ui.Text("Base URL (for Custom, OpenRouter or local OpenAI-compatible endpoints)", variant="caption"),
                ui.Input(
                    placeholder="https://openrouter.ai/api/v1 or https://api.example.com/v1",
                    param_name="base_url", value=base_url,
                ),
                ui.Stack([
                    ui.Button(
                        label="Test Connection", variant="ghost",
                        on_click=ui.Call("__panel__tools",
                                         section="llm", run_test="main"),
                    ),
                    ui.Button(
                        label="Test Tool-Use Compatibility", variant="ghost",
                        on_click=ui.Call("__panel__tools",
                                         section="llm", run_test="main_compat"),
                    ),
                ]),
            ]),

            # ── 2 · Failover ──────────────────────────────────────
            ui.Section(title="\U0001f501 Failover", collapsible=True, children=[
                ui.Text(
                    "Optional retry target used only after the primary fails. "
                    "Leave its model blank to keep no global failover configured.",
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
                    options=provider_opts, value=failover_provider,
                    param_name="failover_provider",
                    placeholder="Select failover provider",
                ),
                ui.Text("Failover Model (select from catalog)", variant="caption"),
                ui.Select(
                    options=_provider_models,
                    value=failover_model,
                    param_name="failover_model",
                    placeholder="Select failover model",
                ),
                ui.Text("Custom / Manual Failover Model ID (optional — overrides dropdown if entered)", variant="caption"),
                ui.Input(
                    placeholder="e.g. z-ai/glm-5.3 or custom-model-name",
                    param_name="failover_custom_model", value=defaults.get("failover_custom_model", ""),
                ),
                ui.Text("Failover API Key", variant="caption"),
                ui.Input(
                    placeholder="sk-…  (leave blank to keep current)",
                    param_name="failover_api_key", value="",
                ),
                ui.Text("Failover Base URL (for Custom, OpenRouter or local endpoints)", variant="caption"),
                ui.Input(
                    placeholder="https://openrouter.ai/api/v1 or https://api.example.com/v1",
                    param_name="failover_base_url", value=defaults.get("failover_base_url", ""),
                ),
                ui.Stack([
                    ui.Button(
                        label="Test Failover", variant="ghost",
                        on_click=ui.Call("__panel__tools",
                                         section="llm", run_test="failover"),
                    ),
                    ui.Button(
                        label="Test Failover Tool-Use Compatibility", variant="ghost",
                        on_click=ui.Call("__panel__tools",
                                         section="llm", run_test="failover_compat"),
                    ),
                ]),
            ]),

            # ── 3 · Per-Purpose Models ────────────────────────────
            ui.Section(title="\U0001f9e0 Per-Purpose Models", collapsible=True,
                       children=model_children),

            # ── 3b · Webbee Code Model Tiers (2026-07-30) ─────────
            build_tiers_section(defaults, _all_models),

            # ── 3c · Voice / STT (Whisper) (2026-08-29, BYOK pass 2) ──
            build_voice_section(defaults, stt_model_catalog),

            # ── 4 · Per-Purpose AI Parameters ─────────────────────
            ui.Section(title="\U0001f39b Per-Purpose AI Parameters",
                       collapsible=True, children=aiparam_children),

            # ── 5 · Per-Purpose Token Budgets ─────────────────────
            ui.Section(title="\U0001f4cf Per-Purpose Token Budgets (max_tokens)",
                       collapsible=True, children=budget_children),

            # ── 6 · Token Budget Controls (TBC) ───────────────────
            build_tbc_section(defaults),

            # ── 6b · Webbee Code Thread Compaction ────────────────
            build_coding_thread_section(defaults),

            # ── 6c · Docs Knowledge (search_docs) ─────────────────
            ui.Section(title="\U0001f4da Docs Knowledge (search_docs)",
                       collapsible=True, children=[
                ui.Text(
                    "Webbee answers product questions by retrieving from the "
                    "live docs corpus in two stages: a ROUTER LLM picks which "
                    "sections fit the question, then only those sections are "
                    "read. This is the router's response budget. Changes apply "
                    "within 60s (config cache TTL) — no worker restart needed.",
                    variant="caption",
                ),
                ui.Text(
                    "knowledge_pick_max_tokens — UNIT: tokens. Kernel fallback "
                    "when unset: 200. That is too small for a REASONING router "
                    "model (e.g. gpt-5-mini): its thinking tokens count against "
                    "this budget, and when they consume it the reply arrives "
                    "with an EMPTY text block — no error, nothing logged — so "
                    "retrieval silently returns nothing and Webbee reports 'no "
                    "documentation found' for docs that DO exist. Measured "
                    "2026-08-18: ~25% of calls (3 of 12 identical probes). "
                    "Recommended 1500. Consumer: activities/knowledge.py:_pick_llm.",
                    variant="caption",
                ),
                ui.Slider(
                    min=200, max=8000, step=100,
                    value=defaults["knowledge_pick_max_tokens"],
                    label="knowledge_pick_max_tokens (tokens)",
                    param_name="knowledge_pick_max_tokens",
                ),
            ]),

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

                # ── Orphan flags wired 2026-08-18 ─────────────────
                # The kernel already read all three through the SAME
                # get_admin_llm_config_field cascade as the two toggles above,
                # but no panel field ever wrote them -- so the store key never
                # existed and only the kernel's env/literal default could ever
                # apply. Leaving a toggle at its rendered value is a no-op.
                ui.Divider(),
                ui.Toggle(
                    label="Brain-First Routing (skip the classifier gate)",
                    value=bool(defaults["hub_brain_first_enabled"]),
                    param_name="hub_brain_first_enabled",
                ),
                ui.Text(
                    "When ON: an interactive turn with no open confirmation card "
                    "goes straight to the brain, skipping the classify_intent LLM "
                    "gate — one less LLM call and lower latency per turn. BYOLLM "
                    "tenants always keep the classifier. Kernel default ON. This "
                    "is the runtime kill-switch: turning it OFF rolls routing "
                    "back within 60s with no redeploy.",
                    variant="caption",
                ),
                ui.Toggle(
                    label="Panel Diet (slim tool catalogue on panel turns)",
                    value=bool(defaults["panel_diet_enabled"]),
                    param_name="panel_diet_enabled",
                ),
                ui.Text(
                    "When ON: the agentic tool catalogue sent to the brain is "
                    "trimmed for panel turns — fewer prompt tokens on every turn. "
                    "Kernel default ON. Turn OFF only to rule the diet out while "
                    "debugging a tool the brain claims not to see.",
                    variant="caption",
                ),
                ui.Toggle(
                    label="Frame v2 Dual Emit (facts-only frames)",
                    value=bool(defaults["frame_v2_enabled"]),
                    param_name="frame_v2_enabled",
                ),
                ui.Text(
                    "When ON: surfaces whose profile declares frame_version=v2 "
                    "ALSO receive the facts-only v2 frame alongside the existing "
                    "v1 emit — v1 is never replaced, so this cannot break a "
                    "surface. Kernel default OFF (opt-in dual emission).",
                    variant="caption",
                ),
            ]),
        ],
    )
