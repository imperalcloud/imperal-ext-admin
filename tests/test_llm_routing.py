"""Unit tests for the pure LLM routing/pricing resolver.

These lock down the two facts the operator was previously unable to see:
  * WHICH model actually runs for a purpose (the cascade, incl. inheritance)
  * what one action therefore COSTS (tier -> platform fee -> credits)

Pure functions, no gateway: the numbers here are reproducible, which is the
whole point -- the billing explanation must not depend on a narration.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from models_llm_routing import (  # noqa: E402
    DEFAULT_TIER_FEES,
    PURPOSE_SLOTS,
    UNKNOWN_TIER,
    ModelRate,
    estimate_run_cost,
    normalise_rates,
    resolve_slot,
)

SONNET = "claude-sonnet-4-20250514"
OPUS = "claude-opus-4-20250514"
HAIKU = "claude-haiku-4-20250514"

RATES = normalise_rates([
    {"id": SONNET, "tier": "standard", "input_cost_per_1k": 0.003,
     "output_cost_per_1k": 0.015, "is_available": True},
    {"id": OPUS, "tier": "premium", "input_cost_per_1k": 0.015,
     "output_cost_per_1k": 0.075, "is_available": True},
    {"id": HAIKU, "tier": "economy", "input_cost_per_1k": 0.0008,
     "output_cost_per_1k": 0.004, "is_available": True},
])


# ── the cascade ──────────────────────────────────────────────────────────── #

def test_explicit_slot_model_wins():
    cfg = {"model": SONNET, "resolve_model": OPUS}
    got = resolve_slot("resolve", "L", cfg, RATES, DEFAULT_TIER_FEES)
    assert got.effective_model == OPUS
    assert got.source == "explicit"
    assert got.tier == "premium"


def test_blank_slot_inherits_the_global_default():
    """The subtle one: a blank slot is NOT 'off', it silently inherits."""
    cfg = {"model": SONNET, "resolve_model": ""}
    got = resolve_slot("resolve", "L", cfg, RATES, DEFAULT_TIER_FEES)
    assert got.effective_model == SONNET
    assert got.source == "inherited_default"
    assert got.tier == "standard"


def test_nothing_configured_is_reported_not_guessed():
    got = resolve_slot("resolve", "L", {}, RATES, DEFAULT_TIER_FEES)
    assert got.effective_model == ""
    assert got.source == "unset"
    assert any("No model resolves" in w for w in got.warnings)


def test_provider_is_inferred_when_left_blank():
    cfg = {"model": SONNET}
    assert resolve_slot("resolve", "L", cfg, RATES, DEFAULT_TIER_FEES).provider == "anthropic"
    cfg = {"model": "gpt-4o"}
    assert resolve_slot("resolve", "L", cfg, RATES, DEFAULT_TIER_FEES).provider == "openai"


# ── tier -> money ────────────────────────────────────────────────────────── #

def test_tier_drives_the_per_action_fee():
    cfg_premium = {"model": OPUS}
    cfg_economy = {"model": HAIKU}
    assert resolve_slot("resolve", "L", cfg_premium, RATES, DEFAULT_TIER_FEES).platform_fee == DEFAULT_TIER_FEES["premium"]
    assert resolve_slot("resolve", "L", cfg_economy, RATES, DEFAULT_TIER_FEES).platform_fee == DEFAULT_TIER_FEES["economy"]


def test_the_37x_swing_is_reproducible():
    """Identical actions, different tier -- the exact reported symptom."""
    economy = estimate_run_cost(DEFAULT_TIER_FEES["economy"], actions=5)
    premium = estimate_run_cost(DEFAULT_TIER_FEES["premium"], actions=5)
    assert economy == 5 * (60 + 1) == 305
    assert premium == 5 * (2200 + 1) == 11005
    assert premium / economy > 30


def test_four_premium_actions_reproduce_the_reported_bill():
    """The ~8,000-credit run: 4 actions on premium, not a pricing glitch."""
    assert estimate_run_cost(DEFAULT_TIER_FEES["premium"], actions=4) == 8804


def test_unpriced_model_never_bills_as_premium():
    """An unknown model must fail CHEAP, and say so."""
    cfg = {"model": "some-brand-new-model"}
    got = resolve_slot("resolve", "L", cfg, RATES, DEFAULT_TIER_FEES)
    assert got.is_priced is False
    assert got.tier == UNKNOWN_TIER
    # No rate row => NO invented fee. Guessing one would misstate real money.
    assert got.platform_fee == 0
    assert any("no rate row" in w for w in got.warnings)


def test_live_fees_override_the_built_in_defaults():
    cfg = {"model": OPUS}
    got = resolve_slot("resolve", "L", cfg, RATES, {"premium": 999})
    assert got.platform_fee == 999


# ── the warnings that would have caught this incident ────────────────────── #

def test_premium_on_a_hot_path_is_flagged():
    cfg = {"model": OPUS}
    got = resolve_slot("resolve", "L", cfg, RATES, DEFAULT_TIER_FEES)
    assert any("premium tier" in w for w in got.warnings)


def test_unavailable_model_still_wired_is_flagged():
    rates = normalise_rates([
        {"id": OPUS, "tier": "premium", "is_available": False},
    ])
    got = resolve_slot("resolve", "L", {"model": OPUS}, rates, DEFAULT_TIER_FEES)
    assert any("unavailable" in w for w in got.warnings)


def test_model_outside_the_allowlist_is_flagged():
    got = resolve_slot("resolve", "L", {"model": OPUS}, RATES, DEFAULT_TIER_FEES, allowlist=[SONNET])
    assert any("NOT in the allowed-models list" in w for w in got.warnings)


def test_allowlist_of_none_means_no_restriction():
    got = resolve_slot("resolve", "L", {"model": OPUS}, RATES, DEFAULT_TIER_FEES, allowlist=None)
    assert not any("allowed-models" in w for w in got.warnings)


# ── coverage: no purpose may become invisible again ──────────────────────── #

def test_every_purpose_slot_resolves():
    """`resolve` was invisible for months. Nothing may silently drop out."""
    cfg = {"model": SONNET}
    for purpose, _label in PURPOSE_SLOTS:
        got = resolve_slot(purpose, _label, cfg, RATES, DEFAULT_TIER_FEES)
        assert got.effective_model == SONNET
        assert got.label, f"{purpose} must carry a human label"


def test_resolve_purpose_is_present_and_described_as_automation_critical():
    labels = dict(PURPOSE_SLOTS)
    assert "resolve" in labels
    assert "automation" in labels["resolve"].lower()
