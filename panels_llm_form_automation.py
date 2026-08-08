"""Admin · LLM Config → "Automations" navigation map.

WHY THIS FILE EXISTS
--------------------
The LLM tab holds ~90 knobs spread over eight generic sections (Provider,
Per-Purpose Models, AI Params, Token Budgets, TBC, Coding Thread, Flags).
Every one of them is documented in isolation, but NOTHING said which of them
an *unattended automation run* actually touches -- so an admin tuning
automations had to know the kernel by heart to guess whether a given knob
fires when a rule runs at 03:00 with no human watching.

This section answers exactly that question, in the order the pipeline runs:

    trigger -> condition -> plan -> reason -> execute -> narrate -> guard

For each stage it states, in plain words:
  * WHAT the stage does,
  * WHICH knob controls it (the real param_name, spelled out),
  * WHERE that knob's input lives (which section to scroll to),
  * ITS CURRENT VALUE as loaded from the live config,
  * WHAT HAPPENS if you raise/lower it, and
  * WHETHER it also affects interactive chat (blast radius).

DELIBERATELY READ-ONLY — the single most important design decision here
------------------------------------------------------------------------
This section renders NO inputs. Every knob it describes is ALREADY rendered
by another section, and `param_name` is the form's write key: two controls
sharing one param_name would both submit it, and whichever the form
serialises last would silently clobber the other. An admin could set a value
here, watch a stale duplicate overwrite it, and reasonably conclude the panel
was lying. A map that always tells the truth beats a second set of inputs
that sometimes wins the race — so this is a map, and it points at the real
control instead of duplicating it.

Consequence worth stating out loud: this module CANNOT drift into a
write path by accident. It has no param_name anywhere, so it cannot
participate in form submission at all.
"""
from __future__ import annotations

from imperal_sdk import ui

# Section labels are duplicated as plain strings on purpose: they are
# navigation hints for a human ("scroll to this heading"), not identifiers.
# Keeping them as text means renaming a section never breaks this map at
# import time -- it just makes one hint slightly stale, which a reader
# survives, whereas a hard reference would crash the whole LLM tab.
# Verified against the live headings actually rendered by panels_llm_form.py /
# panels_llm_form_tbc*.py -- a hint that names a section which does not exist
# is worse than no hint, so these strings are copied from the real titles.
_SEC_MODELS = "🧠 Per-Purpose Models"
_SEC_BUDGETS = "📏 Per-Purpose Token Budgets (max_tokens)"
_SEC_TBC = "Token Budget Controls"          # no emoji on the real heading
_SEC_FLAGS = "🚩 Feature Flags (Kernel)"
_SEC_PROVIDER = "🔌 Provider & Connection"
_SEC_PARAMS = "🎛 Per-Purpose AI Parameters"

# Sub-headings inside "Token Budget Controls" -- that section is long, so the
# map points at the exact group rather than making the admin hunt the whole
# thing.
_GRP_CEILING = "Token Budget Controls → 🛡 Federal cost ceiling"
_GRP_LIMITS = "Token Budget Controls → 👥 Default user limits"
_GRP_PURPOSE_TOKENS = "Token Budget Controls → 🤖 max_tokens per kernel-internal LLM purpose"
_GRP_CHAIN = "Token Budget Controls → ⛓ Cross-step chain context"

# Honest marker for a knob that IS admin-tunable (declared on
# SaveLlmConfigParams, read by the kernel cascade) but has NO input rendered
# anywhere in this form -- resolve_max_tokens is absent from _TOKEN_BUDGETS.
# Saying "not exposed as a field yet" is the truth; pointing at a section that
# has no such row would send the admin looking for a control that isn't there.
_NOT_EXPOSED = "⚠ no form row yet (API/params only)"

# ── The automation pipeline, stage by stage ────────────────────────────────
# (stage_emoji, stage_title, what_it_does, [knob, ...])
# knob = (param_name, where_rendered, default_str, effect, blast_radius)
#   effect        — what changes when you move it, in consequences not units
#   blast_radius  — "automations only" | "shared with chat"
#
# Every param_name below was verified to exist as a declared field on
# SaveLlmConfigParams (models_llm_config.py) AND to be rendered by exactly
# one section, so each pointer lands on a control that really exists.
_PIPELINE: list[tuple[str, str, str, list[tuple[str, str, str, str, str]]]] = [
    (
        "1",
        "Trigger fires",
        "An event arrives (schedule tick, new email, webhook…) and the rule "
        "engine decides whether this rule is even a candidate. Cheap, "
        "high-frequency: it runs on every matching event for every rule.",
        [
            (
                "rule_engine_max_tokens",
                _GRP_PURPOSE_TOKENS,
                "50",
                "Room the trigger matcher gets to answer. It only ever emits a "
                "yes/no, so 50 is deliberate. Raising it buys nothing and costs "
                "on every event; lowering it risks a truncated verdict.",
                "automations only",
            ),
        ],
    ),
    (
        "2",
        "Condition is evaluated",
        "For a rule with a condition (\"only if the sender is a customer\"), a "
        "small LLM decides whether THIS event matches. Runs once per candidate "
        "event — before any real work is done.",
        [
            (
                "automation_condition_max_tokens",
                _GRP_PURPOSE_TOKENS,
                "50",
                "Room for the yes/no match decision. Same logic as above: small "
                "by design. If conditions started returning empty verdicts, this "
                "is the first place to look.",
                "automations only",
            ),
        ],
    ),
    (
        "3",
        "Rule is parsed into a plan",
        "When you CREATE or EDIT a rule, the prompt you typed is decoded into a "
        "structured rule (trigger + action + args). This runs at authoring "
        "time, not on every run — so it is the cheapest place to be generous.",
        [
            (
                "automation_main_max_tokens",
                _GRP_PURPOSE_TOKENS,
                "4096",
                "Room to decode your prompt into a rule. Too low and a long, "
                "detailed rule description gets cut off mid-parse, producing a "
                "rule that silently does less than you asked. Safe to raise.",
                "automations only",
            ),
        ],
    ),
    (
        "4",
        "The brain reasons",
        "The agentic loop that decides what to actually DO — the same reasoning "
        "tier that powers chat. This is where an unattended run spends most of "
        "its intelligence and most of its money.",
        [
            (
                "resolve_model",
                _SEC_MODELS,
                "inherit",
                "THE most consequential setting for automation quality. This is "
                "the model that thinks during every unattended run. Blank does "
                "NOT mean the default model at the top of this tab — the kernel "
                "makes the brain follow the ROUTING model instead, so a routing "
                "change silently re-prices every automation. Pick one to pin it.",
                "shared with chat",
            ),
            (
                "resolve_fallback_model",
                _SEC_MODELS,
                "platform reasoning default",
                "The retry target when the brain's primary model errors — one "
                "retry, then the run fails. Applies to every unattended run. "
                "Blank uses the platform's reasoning-grade default.",
                "shared with chat",
            ),
            (
                "resolve_max_tokens",
                _NOT_EXPOSED,
                "inherit (floored at 4096)",
                "Room the brain gets to reason AND answer. Reasoning models "
                "count their thinking against this cap, which is why the kernel "
                "refuses to go below 4096 — a too-small value here would starve "
                "the brain rather than just shorten its reply.",
                "shared with chat",
            ),
            (
                "purpose_resolve_temperature",
                _SEC_PARAMS,
                "inherit",
                "Determinism of the reasoning step. Lower = more repeatable runs, "
                "which is usually what you want for something firing unattended "
                "at 03:00. Blank inherits the global value.",
                "shared with chat",
            ),
        ],
    ),
    (
        "5",
        "The action runs",
        "The chosen extension tool is dispatched with real arguments — this is "
        "the step that sends the mail, writes the file, restarts the service.",
        [
            (
                "execution_model",
                _SEC_MODELS,
                "inherit",
                "Decides what actually gets called and with which arguments. "
                "Favour accuracy over speed: a wrong choice here is a wrong "
                "action taken with nobody watching.",
                "shared with chat",
            ),
            (
                "execution_max_tokens",
                _SEC_BUDGETS,
                "inherit",
                "Room for the dispatch decision. Truncation here means malformed "
                "arguments, which surfaces as a failed run rather than a wrong one.",
                "shared with chat",
            ),
            (
                "hub_dispatch_max_depth",
                _GRP_CHAIN,
                "6",
                "How many extensions one run may chain through (app A calls B "
                "calls C…). Set to 0 and multi-step automations stop working "
                "entirely — they collapse to a single action.",
                "shared with chat",
            ),
            (
                "default_max_tool_rounds",
                _GRP_LIMITS,
                "10",
                "How many sequential tool calls a single run may make. This is "
                "the ceiling on how much one automation can get done before it "
                "is cut off mid-task.",
                "shared with chat",
            ),
        ],
    ),
    (
        "6",
        "The result is written up",
        "The run's outcome is turned into the text you read in the notification "
        "or the run log. Affects what you SEE, never what was DONE.",
        [
            (
                "chain_narrative_model",
                _SEC_MODELS,
                "inherit",
                "Writes the multi-step summary of what the run did.",
                "shared with chat",
            ),
            (
                "chain_narrative_max_tokens",
                _SEC_BUDGETS,
                "8000",
                "Room for that summary. Large on purpose: a long report or mail "
                "body truncated here looks like a broken run even when the run "
                "itself succeeded perfectly.",
                "shared with chat",
            ),
            (
                "action_narrator_max_tokens",
                _SEC_BUDGETS,
                "1024",
                "Room for the short per-action description.",
                "shared with chat",
            ),
        ],
    ),
    (
        "7",
        "Safety guards",
        "Cross-cutting limits that apply to every run regardless of stage. "
        "These are the ones to reach for when the worry is cost or a runaway "
        "loop rather than quality.",
        [
            (
                "quality_ceiling_tokens",
                _GRP_CEILING,
                "50000",
                "Hard ceiling on ANY single LLM call, overriding every "
                "per-purpose value above. Your last line of defence against a "
                "cost runaway — nothing gets past it.",
                "shared with chat",
            ),
            (
                "default_kav_max_retries",
                _GRP_LIMITS,
                "2",
                "How many times a failing tool call is retried before the run is "
                "marked failed. Higher rides out transient blips (a flaky API); "
                "lower surfaces real breakage sooner.",
                "shared with chat",
            ),
            (
                "judge_enabled",
                _SEC_FLAGS,
                "off",
                "Anti-fabrication review of generated text. Costs an extra LLM "
                "pass on every narration — worth it if automations post "
                "user-visible content somewhere you cannot easily correct.",
                "shared with chat",
            ),
            (
                "step_reclassify_enabled",
                _SEC_FLAGS,
                "on",
                "Re-checks arguments against prior-step results before each "
                "write/destructive step. This is a correctness guard for exactly "
                "the unattended case; turn it off only to cut cost deliberately.",
                "shared with chat",
            ),
        ],
    ),
]

# Knobs admins reasonably EXPECT to matter for automations but which do not.
# Stating these explicitly is the difference between "I could not find it"
# and "I know it does not apply" -- the second is a real answer.
_NOT_APPLICABLE: list[tuple[str, str]] = [
    (
        "code_model / Webbee Code tiers",
        "Terminal coding sessions only. An automation rule never routes "
        "through the coding brain, so changing these cannot affect a run.",
    ),
    (
        "coding_thread_* (compaction)",
        "Coding-session thread compaction only. Automations do not maintain a "
        "coding thread.",
    ),
    (
        "routing_model / routing_max_tokens",
        "The every-turn intent classifier for INTERACTIVE messages. An "
        "automation's action is already resolved when the rule is stored, so a "
        "scheduled run does not re-classify intent.",
    ),
    (
        "conversational_model",
        "Chitchat fall-through for human conversation. Never reached by a rule.",
    ),
]


def _fmt_current(value) -> str:
    """Render a live config value for display; '' / None read as 'inherit'.

    Booleans are shown as on/off rather than True/False so a toggle's state
    reads the same here as it does on its own control.
    """
    if value is None or value == "":
        return "inherit"
    if isinstance(value, bool):
        return "on" if value else "off"
    return str(value)


def build_automation_section(defaults: dict, cfg: dict | None = None) -> object:
    """Build the read-only "Automations" navigation map.

    Args:
        defaults: the form `defaults` dict already assembled by
            build_llm_form — the same values the real controls render, so a
            number shown here can never disagree with its own input.
        cfg: raw `imperal:config:llm`, needed for the per-purpose model slots
            (resolve_model and friends) which live in cfg rather than in
            tenant defaults.

    Returns:
        A collapsible ui.Section. Contains no inputs by design — see the
        module docstring.
    """
    _cfg = cfg or {}

    def _current(param: str) -> str:
        # defaults wins: it is what the live controls are rendering right now.
        if param in defaults:
            return _fmt_current(defaults.get(param))
        return _fmt_current(_cfg.get(param))

    children: list = [
        ui.Text(
            "Everything on this tab that affects a rule running UNATTENDED, in "
            "the order it happens. This section is a map, not a second set of "
            "controls: each row names the exact setting, shows its current "
            "value, and tells you which section to scroll to in order to change "
            "it. Nothing here is editable — so a value shown here can never "
            "disagree with the control that owns it.",
            variant="caption",
        ),
        ui.Divider(),
    ]

    for num, title, what, knobs in _PIPELINE:
        children.append(ui.Text(f"{num} · {title}", variant="subtitle"))
        children.append(ui.Text(what, variant="caption"))

        rows: list = []
        for param, where, default_str, effect, blast in knobs:
            shared = blast == "shared with chat"
            rows.append({
                "setting": param,
                "now": _current(param),
                "default": default_str,
                "effect": effect,
                "affects": "chat too" if shared else "automations only",
                "change_in": where,
            })

        children.append(ui.DataTable(
            columns=[
                {"key": "setting", "label": "Setting"},
                {"key": "now", "label": "Now"},
                {"key": "default", "label": "Default"},
                {"key": "effect", "label": "What moving it does"},
                {"key": "affects", "label": "Blast radius"},
                {"key": "change_in", "label": "Change it in"},
            ],
            rows=rows,
        ))
        children.append(ui.Divider())

    # ── Does NOT affect automations ──
    children.append(ui.Text(
        "Does NOT affect automations", variant="subtitle",
    ))
    children.append(ui.Text(
        "Listed so you can stop looking: these are the settings most often "
        "mistaken for automation controls.",
        variant="caption",
    ))
    children.append(ui.DataTable(
        columns=[
            {"key": "setting", "label": "Setting"},
            {"key": "why", "label": "Why it does not apply"},
        ],
        rows=[{"setting": s, "why": w} for s, w in _NOT_APPLICABLE],
    ))
    children.append(ui.Divider())

    # ── Practical guidance, tied to the intent an admin actually arrives with ──
    children.append(ui.Text("If your goal is…", variant="subtitle"))
    children.append(ui.DataTable(
        columns=[
            {"key": "goal", "label": "Goal"},
            {"key": "do", "label": "What to change"},
        ],
        rows=[
            {
                "goal": "Smarter automation runs",
                "do": "Stage 4 · resolve_model → a stronger model. Note it is "
                      "shared with chat, so chat gets smarter and pricier too.",
            },
            {
                "goal": "Cheaper automation runs",
                "do": "Lower quality_ceiling_tokens (stage 7) first — it caps "
                      "everything at once. Turning off judge_enabled removes a "
                      "whole LLM pass per narration.",
            },
            {
                "goal": "Runs get cut off before finishing",
                "do": "Raise default_max_tool_rounds (stage 5); if it is a "
                      "multi-app chain, raise hub_dispatch_max_depth too.",
            },
            {
                "goal": "Rules do the wrong thing",
                "do": "Keep step_reclassify_enabled ON (stage 7) and prefer an "
                      "accurate execution_model (stage 5).",
            },
            {
                "goal": "Run summaries look truncated",
                "do": "Raise chain_narrative_max_tokens (stage 6). The run "
                      "itself was fine — only the write-up was clipped.",
            },
            {
                "goal": "Reports of a rule that 'ignores' part of its prompt",
                "do": "Raise automation_main_max_tokens (stage 3), then re-save "
                      "the rule so it is parsed again.",
            },
        ],
    ))
    children.append(ui.Divider())
    children.append(ui.Text(
        "Changes to these settings apply within about 60 seconds (config cache "
        "TTL) — no worker restart needed. A rule already mid-run finishes on "
        "the values it started with.",
        variant="caption",
    ))

    return ui.Section(
        title="🤖 Automations · what affects an unattended run",
        collapsible=True,
        children=children,
    )
