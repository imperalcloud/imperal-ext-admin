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
        title="\U0001f4be Webbee Code — Snapshot-First Retention & Archive", collapsible=True,
        children=[
            ui.Text(
                "The coding agent's mind operates on Snapshot-First mechanical retention "
                "(I-ZERO-LLM-COMPACTION-LAG) — when thread history grows past budget, "
                "oldest spans stream immediately into the cold vault archive (thread_archive) "
                "with zero LLM compaction lag. These knobs tune window bounds, "
                "verbatim message floors, and fallback retention limits. Consumer: "
                "core/coding_thread.py + activities/coding_thread.py.",
                variant="subtitle",
            ),

            ui.Text(
                "coding_thread_window_budget_chars — UNIT: characters. Active thread "
                "history budget before older spans stream to snapshot archive. "
                "Default 250000. Lower = streams earlier (leaner active window, faster turns); "
                "higher = keeps more verbatim history in the live active thread.",
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
                "MOST RECENT messages always survive verbatim in the live window (never archived). "
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
                "coding_thread_input_cap — UNIT: characters. Maximum chunk size "
                "processed per archive retention pass. Default 120000.",
                variant="caption",
            ),
            ui.Slider(
                min=5_000, max=500_000, step=5_000,
                value=defaults["coding_thread_input_cap"],
                label="coding_thread_input_cap (chars)",
                param_name="coding_thread_input_cap",
            ),

            ui.Text(
                "coding_thread_max_rounds — UNIT: rounds. Max batch rounds "
                "executed when catching up a large backlog of unarchived turns. "
                "Kernel default 12.",
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
                "for multi-round retention catch-up (stays safely inside the workflow "
                "timeout). Default 100.",
                variant="caption",
            ),
            ui.Slider(
                min=10, max=140, step=5,
                value=defaults["coding_thread_time_budget_s"],
                label="coding_thread_time_budget_s (seconds)",
                param_name="coding_thread_time_budget_s",
            ),

            ui.Text(
                "coding_thread_fold_max_tokens — UNIT: tokens. Token cap for "
                "snapshot digest synthesis. Kernel default 24576.",
                variant="caption",
            ),
            ui.Slider(
                min=1024, max=65_536, step=256,
                value=defaults["coding_thread_fold_max_tokens"],
                label="coding_thread_fold_max_tokens (tokens)",
                param_name="coding_thread_fold_max_tokens",
            ),

            ui.Text(
                "coding_thread_fold_retry_max_tokens — UNIT: tokens. Token cap for "
                "fallback retry if synthesis reply is truncated. Kernel default 49152.",
                variant="caption",
            ),
            ui.Slider(
                min=1024, max=131_072, step=1024,
                value=defaults["coding_thread_fold_retry_max_tokens"],
                label="coding_thread_fold_retry_max_tokens (tokens)",
                param_name="coding_thread_fold_retry_max_tokens",
            ),
        ],
    )
