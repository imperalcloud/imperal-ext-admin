"""Admin · Webbee Code Model Tiers panel section (2026-07-30).

Webbee Smart / SuperSmart / UltraSmart are the three named quality tiers the
Webbee terminal command lets a user pick between. Each tier is a
full admin-owned (primary, fallback) model pair — a control-plane setting,
never a hardcoded model id anywhere in the kernel. Same shape/precedent as
the existing Webbee Code fallback pair (code_model/code_fallback_model) —
this is the SAME (primary, fallback) idea, generalized to three named tiers
instead of one.

Persisted at imperal:config:llm (Redis Config Store) as flat
{tier}_model / {tier}_provider / {tier}_fallback_model /
{tier}_fallback_provider / {tier}_thinking_effort / {tier}_thinking_budget
keys — read by the kernel's config_resolver.resolve_model_tier.
"""
from __future__ import annotations

from imperal_sdk import ui

_TIERS: tuple[tuple[str, str, str], ...] = (
    ("webbeesmart", "🐝 Webbee Smart",
     "The default, fast everyday tier."),
    ("supersmart", "🐝 Webbee SuperSmart",
     "A stronger reasoning tier for harder tasks."),
    ("ultrasmart", "🐝 Webbee UltraSmart",
     "The strongest tier for the hardest tasks."),
)

EFFORT_OPTIONS: list[dict[str, str]] = [
    {"label": "Inherit / Provider Default", "value": ""},
    {"label": "None (Disable reasoning / fast)", "value": "none"},
    {"label": "Low", "value": "low"},
    {"label": "Medium", "value": "medium"},
    {"label": "High", "value": "high"},
    {"label": "Max (Deepest reasoning / verification)", "value": "max"},
]


def build_tiers_section(defaults: dict, all_models: list[dict]) -> object:
    """Return the Model Tiers ui.Section, pre-populated from defaults."""
    children: list = [
        ui.Text(
            "Configure the primary + fallback model behind each Webbee Code "
            "quality tier and tune the reasoning effort (hardness) and token budgets "
            "per tier with zero hardcoded defaults.",
            variant="caption",
        ),
    ]
    for key, label, desc in _TIERS:
        children.extend([
            ui.Divider(),
            ui.Stack([
                ui.Text(label, variant="body"),
                ui.Text(desc, variant="caption"),
            ], gap=0),
            ui.Text("Primary model", variant="caption"),
            ui.Select(
                options=all_models,
                value=defaults.get(f"{key}_model", ""),
                param_name=f"{key}_model",
                placeholder="Same as Webbee Code model",
            ),
            ui.Text(
                "Fallback model — used only when this tier's primary errors "
                "(one retry). Blank = no fallback.",
                variant="caption",
            ),
            ui.Select(
                options=all_models,
                value=defaults.get(f"{key}_fallback_model", ""),
                param_name=f"{key}_fallback_model",
                placeholder="No fallback",
            ),
            ui.Text("Tier Reasoning Effort (hardness)", variant="caption"),
            ui.Select(
                options=EFFORT_OPTIONS,
                value=defaults.get(f"{key}_thinking_effort", ""),
                param_name=f"{key}_thinking_effort",
                placeholder="Inherit / Provider Default",
            ),
            ui.Text("Tier Thinking Budget (tokens, e.g. 8000–32000)", variant="caption"),
            ui.Input(
                placeholder="Inherit (default)",
                param_name=f"{key}_thinking_budget",
                value=str(defaults.get(f"{key}_thinking_budget", "")),
            ),
        ])
    return ui.Section(title="🐝 Webbee Code Model Tiers", collapsible=True,
                       children=children)
