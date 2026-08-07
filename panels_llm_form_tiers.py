"""Admin · Webbee Code Model Tiers panel section (2026-07-30).

Webbee Smart / SuperSmart / UltraSmart are the three named quality tiers the
Webbee terminal's `/model` command lets a user pick between. Each tier is a
full admin-owned (primary, fallback) model pair — a control-plane setting,
never a hardcoded model id anywhere in the kernel. Same shape/precedent as
the existing Webbee Code fallback pair (code_model/code_fallback_model) —
this is the SAME (primary, fallback) idea, generalized to three named tiers
instead of one.

Persisted at ``imperal:config:llm`` (Redis Config Store) as flat
``{tier}_model`` / ``{tier}_provider`` / ``{tier}_fallback_model`` /
``{tier}_fallback_provider`` keys — read by the kernel's
``config_resolver.resolve_model_tier`` (same cascade machinery every other
per-purpose override already goes through). A blank primary means "not
configured yet" — the kernel falls through to the existing purpose="code"
cascade rather than breaking.
"""
from __future__ import annotations

from imperal_sdk import ui

# (tier key, display name, one-line description of who/what selects it).
# `tier key` is the flat Config Store prefix — MUST match config_resolver.py's
# MODEL_TIERS tuple verbatim (federal source of truth for the read side).
_TIERS: tuple[tuple[str, str, str], ...] = (
    # NOTE: the key is "webbeesmart", NOT "smart" -- it must match
    # MODEL_TIERS in the kernel's llm/model_tiers.py verbatim, because that
    # tuple is what the READ side keys off. This form shipped writing
    # "smart_model", a key nothing reads, so the Webbee Smart row was inert:
    # the admin picked a model and the tier kept resolving through the
    # code_model cascade. The other two tiers were always correct.
    ("webbeesmart", "🐝 Webbee Smart",
     "The default, fast everyday tier."),
    ("supersmart", "🐝 Webbee SuperSmart",
     "A stronger reasoning tier for harder tasks."),
    ("ultrasmart", "🐝 Webbee UltraSmart",
     "The strongest tier for the hardest tasks."),
)


def build_tiers_section(defaults: dict, all_models: list[dict]) -> object:
    """Return the Model Tiers ui.Section, pre-populated from `defaults`.

    `defaults` MUST carry `{tier}_model` / `{tier}_fallback_model` for every
    tier in `_TIERS` (blank string = unset, renders as "Same as default" /
    "No fallback" exactly like the existing Webbee Code fallback control).
    `all_models` is the SAME live-catalogue option list every other
    per-purpose Select in this form uses (panels_llm_models.catalog_to_options).
    """
    children: list = [
        ui.Text(
            "Configure the primary + fallback model behind each Webbee Code "
            "quality tier — this is what the terminal's /model command "
            "switches between. Leave a tier's primary blank to fall through "
            "to the Webbee Code model above; each tier's fallback fires "
            "ONLY when its own primary errors (one retry, same as the "
            "Webbee Code fallback below).",
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
        ])
    return ui.Section(title="\U0001f41d Webbee Code Model Tiers", collapsible=True,
                       children=children)
