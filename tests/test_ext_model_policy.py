"""Unit tests for the per-extension AI model policy.

The rule being locked down is the operator's: extensions should use the
SYSTEM defaults, because the system is already configured correctly. These
tests pin down what "pinned" means, what a reset produces, and -- importantly
-- the honest reporting of the one knob the current form cannot express as
inherit.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from models_ext_model_policy import (  # noqa: E402
    FORCED_PARAMS,
    FORM_DEFAULTS,
    INHERIT,
    INHERITABLE_PARAMS,
    MODEL_SLOTS,
    read_policy,
    build_reset_payload,
    diff_policy,
)

# The exact configuration from the operator's screenshot: three slots pinned,
# Analysis on "— Default —", sampling params at the form defaults.
REPORTED = {
    "primary_model": "claude-sonnet-4-6",
    "intake_model": "gpt-4o-mini",
    "analysis_model": "",
    "router_model": "gpt-4o-mini",
    "temperature": 0.7,
    "max_tokens": 2048,
    "thinking_mode": "auto",
}

CLEAN = {
    "primary_model": "",
    "intake_model": "",
    "analysis_model": "",
    "router_model": "",
    "thinking_mode": "auto",
}


# ── detecting a pin ──────────────────────────────────────────────────────── #

def test_the_reported_config_is_flagged_as_not_using_system_defaults():
    got = read_policy("sharelock-v2", {"models": REPORTED}, display_name="Sharelock")
    assert got.uses_system_defaults is False
    pinned = {p.slot: p.model for p in got.pinned_models}
    assert pinned == {
        "primary_model": "claude-sonnet-4-6",
        "intake_model": "gpt-4o-mini",
        "router_model": "gpt-4o-mini",
    }
    # The blank slot is genuinely inheriting and must NOT be reported as a pin.
    assert "analysis_model" not in pinned


def test_all_blank_slots_count_as_using_system_defaults():
    got = read_policy("notes", {"models": CLEAN})
    assert got.uses_system_defaults is True
    assert got.pinned_models == []


def test_missing_section_is_treated_as_inheriting_not_as_broken():
    """An app that never opened the tab inherits everything -- that is fine."""
    got = read_policy("mail", {"models": {}})
    assert got.uses_system_defaults is True
    assert got.pinned_models == []


def test_every_model_slot_is_covered():
    """A new slot must not become another invisible pin."""
    pinned_everything = {slot: "gpt-4o" for slot, _role in MODEL_SLOTS}
    got = read_policy("x", {"models": pinned_everything})
    assert len(got.pinned_models) == len(MODEL_SLOTS)
    assert got.uses_system_defaults is False


def test_pins_carry_the_role_so_the_operator_knows_what_it_drives():
    got = read_policy("x", {"models": {"primary_model": "gpt-4o"}})
    assert got.pinned_models[0].role
    assert "Primary" in got.pinned_models[0].role


# ── the honest half: params the form cannot express as inherit ───────────── #

def test_form_default_params_are_reported_separately_from_real_choices():
    """0.7/2048 is what the form writes on any save -- not a deliberate choice."""
    got = read_policy("x", {"models": REPORTED})
    assert got.forced_params_are_form_defaults is True
    for key in FORCED_PARAMS:
        assert key in got.forced_params


def test_a_deliberate_param_value_is_distinguished_from_the_form_default():
    section = dict(REPORTED, temperature=1.4)
    got = read_policy("x", {"models": section})
    assert got.forced_params_are_form_defaults is False
    assert got.forced_params["temperature"] == 1.4


def test_forced_params_are_flagged_as_unfixable_from_the_ui():
    """The operator must not be told to 'just blank it' -- the UI cannot."""
    got = read_policy("x", {"models": REPORTED})
    joined = " ".join(got.findings).lower()
    assert "temperature" in joined or "max_tokens" in joined
    # Deliberately NOT promising "inherit": the form always writes these two,
    # so the finding must say they override the cascade, not that blanking works.
    assert "the form always writes them" in joined
    assert "overrides the platform cascade" in joined


# ── the reset ────────────────────────────────────────────────────────────── #

def test_reset_returns_every_model_slot_to_inherit():
    out = build_reset_payload(REPORTED)
    for slot, _role in MODEL_SLOTS:
        assert out[slot] == INHERIT


def test_reset_removes_inheritable_params_entirely():
    """Blank would be STORED; absent is a real inherit (save path drops it)."""
    section = dict(REPORTED, top_p=0.9, presence_penalty=0.5)
    out = build_reset_payload(section)
    for key in INHERITABLE_PARAMS:
        assert key not in out


def test_reset_preserves_unrelated_keys():
    """This resets model routing, not the whole settings section."""
    section = dict(REPORTED, thinking_mode="off")
    out = build_reset_payload(section)
    assert out["thinking_mode"] == "off"


def test_reset_params_restores_the_documented_defaults():
    section = dict(REPORTED, temperature=1.9, max_tokens=8000)
    out = build_reset_payload(section, reset_params=True)
    assert out["temperature"] == FORM_DEFAULTS["temperature"]
    assert out["max_tokens"] == FORM_DEFAULTS["max_tokens"]


def test_reset_is_idempotent():
    once = build_reset_payload(REPORTED)
    twice = build_reset_payload(once)
    assert once == twice


def test_a_clean_extension_is_unchanged_by_a_reset():
    """Nothing to fix must mean nothing to write."""
    out = build_reset_payload(CLEAN)
    assert diff_policy(CLEAN, out) == []


# ── the preview ──────────────────────────────────────────────────────────── #

def test_diff_shows_each_change_before_anything_is_written():
    out = build_reset_payload(REPORTED)
    changes = " | ".join(diff_policy(REPORTED, out))
    assert "primary_model" in changes
    assert "claude-sonnet-4-6" in changes
    assert "inherit" in changes.lower()


def test_diff_reports_a_removed_key_as_inherit_not_as_deletion():
    section = dict(CLEAN, top_p=0.9)
    out = build_reset_payload(section)
    changes = diff_policy(section, out)
    assert any("top_p" in c and "inherit" in c for c in changes)
