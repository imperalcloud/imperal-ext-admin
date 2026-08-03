"""Admin · Webbee Code (coding-thread) compaction settings panel section.

Separate module (workspace rule 6: no god files >300 lines). Stored in
imperal:config:llm (NOT tenant_defaults — read via panels_llm.py's cfg,
NOT _fetch_tenant_defaults) because the kernel reads these through the
SAME get_admin_llm_config_field cascade every other purpose-scoped LLM
knob uses (core/coding_thread.py's constants are the final fallback).

I-CODING-THREAD-COMPACTION-ADMIN-TUNABLE (2026-07-31): the coherent-mind
thread never truncates — compaction (folding the oldest span into the
working-model digest) is the ONLY scaling mechanism, and these 6 knobs
tune when/how aggressively that folding runs, entirely from the panel.
"""
from __future__ import annotations

from imperal_sdk import ui


def build_coding_thread_section(defaults: dict):
    """Return the 'Webbee Code — Thread Compaction' ui.Section.

    `defaults` MUST contain int values for all 6 keys below — caller
    (panels_llm_form.build_llm_form) populates them from cfg
    (imperal:config:llm), with the SAME literal fallbacks the kernel uses
    when nothing is configured (core/coding_thread.py constants).
    """
    return ui.Section(
        title="\U0001f9f5 Webbee Code — Thread Compaction", collapsible=True,
        children=[
            ui.Text(
                "The coding agent's mind (the whole conversation thread) NEVER "
                "truncates — when it grows past a budget, the OLDEST span is "
                "folded into a maintained digest instead of being dropped. These "
                "knobs tune that folding. A guaranteed-progress fallback (a "
                "deterministic, no-LLM digest) kicks in automatically if the "
                "distiller LLM is unavailable or its reply is truncated/unparseable "
                "— the thread can never grow without bound, even during an LLM "
                "outage. Consumer: core/coding_thread.py + "
                "activities/coding_thread.py:compact_coding_thread.",
                variant="subtitle",
            ),

            ui.Text(
                "coding_thread_window_budget_chars — UNIT: characters. Serialized "
                "thread size that triggers a compaction round. Default 250000. "
                "Lower = compacts earlier/more often (cheaper turns, more digest "
                "cycles); higher = keeps more verbatim history before the first "
                "fold.",
                variant="caption",
            ),
            ui.Slider(
                min=20_000, max=2_000_000, step=10_000,
                value=defaults["coding_thread_window_budget_chars"],
                label="coding_thread_window_budget_chars (chars)",
                param_name="coding_thread_window_budget_chars",
            ),

            ui.Text(
                "coding_thread_keep_recent — UNIT: messages. How many of the "
                "MOST RECENT messages always survive verbatim (never folded). "
                "Default 20. Higher = more exact recent context, more chars per "
                "step.",
                variant="caption",
            ),
            ui.Slider(
                min=4, max=200, step=1,
                value=defaults["coding_thread_keep_recent"],
                label="coding_thread_keep_recent (messages)",
                param_name="coding_thread_keep_recent",
            ),

            ui.Text(
                "coding_thread_input_cap — UNIT: characters. Max size of the "
                "oldest span folded into ONE digest LLM call (progressive "
                "folding — a huge backlog folds over several rounds). Default "
                "120000. Higher = fewer rounds but a heavier single call.",
                variant="caption",
            ),
            ui.Slider(
                min=5_000, max=500_000, step=5_000,
                value=defaults["coding_thread_input_cap"],
                label="coding_thread_input_cap (chars)",
                param_name="coding_thread_input_cap",
            ),

            ui.Text(
                "coding_thread_max_rounds — UNIT: rounds. Max fold rounds ONE "
                "compact_coding_thread invocation runs (catch-up folding for a "
                "thread that fell far behind budget). Default 6.",
                variant="caption",
            ),
            ui.Slider(
                min=1, max=30, step=1,
                value=defaults["coding_thread_max_rounds"],
                label="coding_thread_max_rounds (rounds)",
                param_name="coding_thread_max_rounds",
            ),

            ui.Text(
                "coding_thread_time_budget_s — UNIT: seconds. Wall-clock ceiling "
                "for a multi-round catch-up (stays safely inside the workflow's "
                "150s activity timeout). Default 100.",
                variant="caption",
            ),
            ui.Slider(
                min=10, max=140, step=5,
                value=defaults["coding_thread_time_budget_s"],
                label="coding_thread_time_budget_s (seconds)",
                param_name="coding_thread_time_budget_s",
            ),

            ui.Text(
                "coding_thread_fold_max_tokens — UNIT: tokens. Base response cap "
                "for the fold digest LLM call. Default 4096 — on a truncated/"
                "unparseable reply the kernel automatically retries ONCE at 2x "
                "this cap before falling back to the mechanical digest, so "
                "raising this lowers how often that retry is even needed "
                "(Cyrillic-heavy / other dense-token spans truncate sooner).",
                variant="caption",
            ),
            ui.Slider(
                min=1024, max=16000, step=256,
                value=defaults["coding_thread_fold_max_tokens"],
                label="coding_thread_fold_max_tokens (tokens)",
                param_name="coding_thread_fold_max_tokens",
            ),
        ],
    )
