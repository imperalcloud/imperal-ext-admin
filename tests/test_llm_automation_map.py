"""Tests for the LLM Config → Automations navigation map.

The map's whole value is that an admin can trust it: every row must name a
setting that (a) really exists as a save_llm_config field, and (b) really has
a control where the row says it does. A stale pointer sends someone hunting
for an input that isn't there, which is worse than no map at all — so those
two properties are asserted here rather than maintained by hand.

Also locks the deliberate read-only design: the map must never render an
input, because every knob it describes is already rendered elsewhere and a
duplicate `param_name` would make two controls fight over one write key.
"""
from __future__ import annotations

import inspect
import re

import pytest

import panels_llm_form_automation as amap
from models_llm_config import SaveLlmConfigParams


# ── helpers ───────────────────────────────────────────────────────────────

def _pipeline_knobs() -> list[tuple[str, str, str, str, str]]:
    """Flatten every knob row out of the pipeline definition."""
    out: list[tuple[str, str, str, str, str]] = []
    for _num, _title, _what, knobs in amap._PIPELINE:
        out.extend(knobs)
    return out


def _rendered_param_names() -> set[str]:
    """Every param_name the real form renders, static + loop-built.

    The per-purpose rows are built with f-strings (``f"{key}_model"``), so a
    literal grep misses them; expand those templates from the same source
    lists the form iterates.
    """
    import panels_llm_form as form

    names: set[str] = set()
    for mod in ("panels_llm_form", "panels_llm_form_tbc",
                "panels_llm_form_tbc_meta", "panels_llm_form_tiers",
                "panels_llm_form_coding_thread"):
        src = inspect.getsource(__import__(mod))
        names.update(re.findall(r'param_name="([a-z0-9_]+)"', src))

    # loop-built rows: per-purpose models + per-purpose AI params
    for key, *_ in form._PURPOSE_MODELS:
        names.add(f"{key}_model")
        for suffix in ("temperature", "top_p",
                       "presence_penalty", "frequency_penalty"):
            names.add(f"purpose_{key}_{suffix}")
    # loop-built rows: per-purpose token budgets
    for pname, *_ in form._TOKEN_BUDGETS:
        names.add(pname)
    return names


# ── the two invariants that make the map trustworthy ──────────────────────

def test_every_knob_is_a_real_save_llm_config_field():
    """No row may name a setting the save tool cannot actually persist."""
    declared = set(SaveLlmConfigParams.model_fields)
    unknown = sorted(
        k[0] for k in _pipeline_knobs()
        # purpose_* AI params are declared dynamically, not as literal fields
        if k[0] not in declared and not k[0].startswith("purpose_")
    )
    assert not unknown, f"map references non-existent settings: {unknown}"


def test_pointers_name_a_section_that_renders_that_knob():
    """A row must point at a real control — or admit there is none."""
    rendered = _rendered_param_names()
    lying = []
    for param, where, *_ in _pipeline_knobs():
        if where == amap._NOT_EXPOSED:
            # explicitly claims "no form row" — assert that is TRUE, so the
            # honesty marker cannot outlive the gap it documents
            assert param not in rendered, (
                f"{param} is marked as having no form row, but one exists now "
                f"— point the map at it instead"
            )
            continue
        if param not in rendered:
            lying.append((param, where))
    assert not lying, f"pointers to non-existent controls: {lying}"


def test_map_renders_no_inputs():
    """Read-only by design: an input here would collide on param_name."""
    node = amap.build_automation_section({"judge_enabled": True})
    assert "param_name" not in repr(node)


# ── content / usability guarantees ────────────────────────────────────────

def test_pipeline_covers_the_whole_run_in_order():
    titles = [t for _n, t, _w, _k in amap._PIPELINE]
    assert len(amap._PIPELINE) >= 7
    joined = " ".join(titles).lower()
    for stage in ("trigger", "condition", "run", "guard"):
        assert stage in joined, f"pipeline is missing the {stage} stage"


def test_every_knob_states_effect_and_blast_radius():
    """Each row must say what changes AND whether chat is affected too."""
    for param, where, default, effect, radius in _pipeline_knobs():
        assert where, f"{param}: no location given"
        assert default, f"{param}: no default shown"
        assert len(effect) > 40, f"{param}: effect text too thin to be useful"
        assert radius in ("automations only", "shared with chat"), (
            f"{param}: blast radius must be explicit, got {radius!r}"
        )


def test_not_applicable_list_explains_each_exclusion():
    """Saying 'this knob is irrelevant' only helps if it says why."""
    assert amap._NOT_APPLICABLE
    for setting, why in amap._NOT_APPLICABLE:
        assert setting and len(why) > 30, f"{setting}: no real explanation"


def test_current_value_formatting_is_human_readable():
    assert amap._fmt_current("") == "inherit"
    assert amap._fmt_current(None) == "inherit"
    assert amap._fmt_current(True) == "on"
    assert amap._fmt_current(False) == "off"
    assert amap._fmt_current(4096) == "4096"


def test_current_values_come_from_the_live_form_defaults():
    """A number shown here must equal what its own control renders."""
    node = amap.build_automation_section({"automation_main_max_tokens": 7777})
    assert "7777" in repr(node)


@pytest.mark.parametrize("missing", [{}, {"judge_enabled": None}])
def test_renders_even_with_incomplete_config(missing):
    """A partial config must degrade to 'inherit', never crash the tab."""
    node = amap.build_automation_section(missing)
    assert "inherit" in repr(node)
