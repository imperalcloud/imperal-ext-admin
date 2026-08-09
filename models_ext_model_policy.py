"""Admin · per-extension AI model policy — "does this app pin its own model?"

The platform already resolves models centrally: a global default, per-purpose
slots, and a documented cascade. An extension is meant to INHERIT that. The
Extension Settings > AI Models tab exists for the rare app that genuinely
needs something else, and its "— Default —" option is exactly the empty
string: blank means *inherit*, not *unset*.

In practice apps drift away from that. A pinned `primary_model` keeps an app
on a model the operator has since moved away from, and -- because the
per-action platform fee follows the TIER of the model that actually runs --
a pinned premium model quietly bills at premium rates forever, no matter what
the system default says.

The save path used to be asymmetric, which is how the drift went unnoticed:

  * `top_p` / `presence_penalty` / `frequency_penalty` are dropped from the
    payload when blank, so they genuinely inherit.
  * `temperature` / `max_tokens` / `thinking_mode` were Pydantic fields with
    defaults 0.7 / 2048 / "auto" and were written on EVERY save. There was no
    blank, therefore no way to express "inherit" -- every app that ever opened
    the form carried a hard-pinned sampling config it never chose.

That second half is FIXED (2026-08-09): all three are now blank-able strings
handled exactly like the sampling params, so "inherit" is expressible for the
whole section. `FORCED_PARAMS` is kept as the name of the *legacy* residue --
values written by the old form that are still sitting in stored configs -- so
the audit can still spot and clean them.

This module is pure: no HTTP, no ctx. It decides what counts as pinned and
what a reset should look like, so the behaviour is unit-testable and the
admin tools stay thin.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

# The four model slots an extension can pin, with the role each one plays.
# Kept as data so a new slot appears in the audit automatically rather than
# becoming another invisible pin.
MODEL_SLOTS: tuple[tuple[str, str], ...] = (
    ("primary_model",  "Primary — the app's main model"),
    ("intake_model",   "Intake — first-pass understanding"),
    ("analysis_model", "Analysis — deeper reasoning step"),
    ("router_model",   "Router — picks the tool/route"),
)

# Sampling knobs that CAN already express inherit (blank -> key dropped).
INHERITABLE_PARAMS: tuple[str, ...] = ("top_p", "presence_penalty", "frequency_penalty")

# Sampling knobs the OLD form always wrote, so they could not inherit. The form
# no longer writes them when blank (2026-08-09), but stored configs still carry
# the residue, so they keep their own name for reporting and cleanup.
FORCED_PARAMS: tuple[str, ...] = ("temperature", "max_tokens")

# The values the form ships as its own defaults. A stored value equal to these
# is indistinguishable from "the admin just opened the tab and hit Save", so
# it is reported separately from a deliberate, distinct choice.
FORM_DEFAULTS: dict[str, float | int | str] = {
    "temperature": 0.7,
    "max_tokens": 2048,
    "thinking_mode": "auto",
}

# "Inherit the system default" for a model slot is the empty string -- the
# value behind the "— Default —" option in the AI Models tab.
INHERIT = ""


class SlotPin(BaseModel):
    """One model slot that is NOT inheriting the system default."""

    slot: str = Field(description="Config key, e.g. primary_model")
    role: str = Field(default="", description="What this slot drives")
    model: str = Field(description="The model id the extension pins")


class ExtensionModelPolicy(BaseModel):
    """Whether one extension defers to the system, and what it overrides."""

    app_id: str = ""
    display_name: str = ""
    uses_system_defaults: bool = Field(
        default=True,
        description="True when every model slot inherits (no pinned model).",
    )
    pinned_models: list[SlotPin] = Field(default_factory=list)
    # Sampling params the app carries. Split by whether the form even allows
    # expressing "inherit" for them -- an operator cannot fix what the UI
    # cannot express, so the two must not be reported as the same problem.
    pinned_params: dict[str, float | int | str] = Field(
        default_factory=dict,
        description="Params the app overrides that COULD have inherited.",
    )
    forced_params: dict[str, float | int | str] = Field(
        default_factory=dict,
        description="temperature/max_tokens — always written by the form.",
    )
    forced_params_are_form_defaults: bool = Field(
        default=True,
        description="True when forced params still equal the form's own defaults "
                    "(i.e. never a deliberate choice, just a Save).",
    )
    thinking_mode: str = "auto"
    findings: list[str] = Field(default_factory=list)


def read_policy(app_id: str, settings: dict, display_name: str = "") -> ExtensionModelPolicy:
    """Describe how one extension's `models` section relates to the defaults.

    `settings` is the whole settings document from
    ``GET /v1/apps/{app_id}/settings``; the `models` section is read out of it.
    A missing section is the ideal case -- the app never pinned anything.
    """
    models = (settings or {}).get("models") or {}

    pinned: list[SlotPin] = []
    for slot, role in MODEL_SLOTS:
        value = str(models.get(slot) or "").strip()
        if value and value != INHERIT:
            pinned.append(SlotPin(slot=slot, role=role, model=value))

    pinned_params: dict[str, float | int | str] = {}
    for key in INHERITABLE_PARAMS:
        if models.get(key) is not None:
            pinned_params[key] = models[key]

    forced_params: dict[str, float | int | str] = {}
    for key in FORCED_PARAMS:
        if models.get(key) is not None:
            forced_params[key] = models[key]

    at_form_defaults = all(
        forced_params.get(k) == FORM_DEFAULTS.get(k) for k in forced_params
    ) if forced_params else True

    findings: list[str] = []
    for pin in pinned:
        findings.append(
            f"{pin.slot} is pinned to '{pin.model}' — it will NOT follow the "
            f"system default, and it bills at that model's tier."
        )
    if pinned_params:
        findings.append(
            "Sampling overrides set: "
            + ", ".join(f"{k}={v}" for k, v in sorted(pinned_params.items()))
            + " (blank these to inherit)."
        )
    if forced_params and at_form_defaults:
        findings.append(
            "temperature/max_tokens are stored at the old form's defaults "
            f"({', '.join(f'{k}={v}' for k, v in sorted(forced_params.items()))}). "
            "The old form wrote them on every save, so this is probably not a "
            "deliberate choice — but it still overrides the platform cascade. "
            "Blank them in the AI Models tab (or reset) to inherit."
        )
    elif forced_params:
        findings.append(
            "temperature/max_tokens differ from the form defaults: "
            + ", ".join(f"{k}={v}" for k, v in sorted(forced_params.items()))
            + " — looks deliberate, confirm before resetting."
        )

    return ExtensionModelPolicy(
        app_id=app_id,
        display_name=display_name or app_id,
        uses_system_defaults=not pinned,
        pinned_models=pinned,
        pinned_params=pinned_params,
        forced_params=forced_params,
        forced_params_are_form_defaults=at_form_defaults,
        thinking_mode=str(models.get("thinking_mode") or "auto"),
        findings=findings,
    )


def build_reset_payload(models: dict, *, reset_params: bool = False) -> dict:
    """Return the `models` section rewritten to defer to the system.

    Every model slot becomes INHERIT. Sampling params that can express inherit
    are removed entirely (the save path drops blanks, so an absent key is a
    real inherit, whereas an empty string would be stored).

    `reset_params` now removes temperature/max_tokens/thinking_mode outright
    rather than rewriting them to the form defaults: since 2026-08-09 the save
    path drops them when blank, so an absent key is a REAL inherit for these
    too. Callers that still want the documented default value should set it
    explicitly instead of relying on a reset.

    Keys outside the model/sampling surface are preserved untouched: this
    resets model routing, not the whole section.
    """
    out = dict(models or {})

    # A slot the app never stored must STAY absent. Writing INHERIT into it
    # would materialise an app-scope key (and a row) for an app that was
    # already inheriting perfectly well -- turning a no-op reset into a real
    # write, and reporting phantom "changes" for apps that had pinned nothing.
    # A slot that IS present is blanked, because blank is what the save path
    # drops on the way out.
    for slot, _role in MODEL_SLOTS:
        if slot in out:
            out[slot] = INHERIT

    for key in INHERITABLE_PARAMS:
        out.pop(key, None)

    if reset_params:
        for key in (*FORCED_PARAMS, "thinking_mode"):
            out.pop(key, None)

    return out


def diff_policy(before: dict, after: dict) -> list[str]:
    """Human-readable list of what a reset actually changes.

    Used to show a dry-run preview: an operator should see the exact before ->
    after per key before anything is written to a live extension.
    """
    changes: list[str] = []
    for key in sorted(set(before or {}) | set(after or {})):
        old, new = (before or {}).get(key), (after or {}).get(key)
        if old == new:
            continue
        if key not in (after or {}):
            changes.append(f"{key}: {old!r} -> removed (inherit)")
        elif new == INHERIT:
            changes.append(f"{key}: {old!r} -> — Default — (inherit)")
        else:
            changes.append(f"{key}: {old!r} -> {new!r}")
    return changes
