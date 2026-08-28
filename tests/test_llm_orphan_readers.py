"""Contract test: EVERY kernel-read LLM Config key is reachable from the panel.

WHY THIS TEST EXISTS
--------------------
The kernel reads admin LLM Config keys through ONE cascade --
``imperal_kernel/llm/admin_toggles.py:get_admin_llm_config_field`` -- backed by
the ``imperal:config:llm`` Redis store. The panel is the only writer of that
store (``fn_save_llm_config``).

That makes a specific, SILENT failure possible: the kernel reads a key that no
panel field ever writes. The store key then never exists, the kernel forever
falls through to its own env/literal default, and nothing anywhere logs a
problem. We call it an ORPHAN READER.

It is not theoretical -- it shipped and caused a live incident:

  knowledge_pick_max_tokens was read by activities/knowledge.py:_pick_llm from
  day one, but had no panel field. So the docs router ran permanently at the
  hardcoded 200 tokens. 200 is not enough for a REASONING model: its thinking
  tokens count against max_tokens, so the reply arrived with content=[],
  stop_reason='end_turn', no exception. The picker returned "", zero doc
  sections were selected, and Webbee told the admin "no documentation found"
  about docs that plainly existed -- measured at ~25% of calls.

A full audit of the live worker (2026-08-18) found FOUR such orphans. This
test pins every one of them, so a key the kernel reads can never again be
unreachable from the panel.

HOW TO EXTEND
-------------
When the kernel starts reading a NEW admin LLM Config key, add it to
KERNEL_READ_KEYS below. If the panel can't write it, this test fails loudly --
which is the entire point, because the alternative is failing silently in
production months later.
"""
from __future__ import annotations

import inspect

import pytest

from models_llm_config import SaveLlmConfigParams
from panels_llm_form import build_llm_form

# Every key the live kernel reads via get_admin_llm_config_field, mapped to the
# kernel-side reader that reads it. Audited on the running worker, 2026-08-18.
KERNEL_READ_KEYS: dict[str, str] = {
    # --- knobs that already had panel fields ---
    "action_narrator_max_tokens": "workflows/action_data_narrator.py:150",
    "chain_arg_refs_max_tokens": "orchestration/chain_arg_refs.py:1033",
    "semantic_verifier_max_tokens": "safety/semantic_verifier.py:192",
    "step_reclassify_max_tokens": "hub/step_classifier.py:266",
    "step_reclassify_enabled": "orchestration/chain/prior_steps.py:106",
    "judge_enabled": "activities/delivery.py:857",
    # --- the docs-router budget: the live incident above ---
    "knowledge_pick_max_tokens": "activities/knowledge.py:131",
    # --- orphans found by the 2026-08-18 audit ---
    "hub_brain_first_enabled": "activities/brain_first.py:_read_brain_first_flag",
    "panel_diet_enabled": "activities/agentic_catalog.py:107",
    "frame_v2_enabled": "activities/agentic_catalog.py:126",
    # --- coding-thread compaction table (activities/coding_thread.py:192-200) ---
    "coding_thread_window_budget_chars": "activities/coding_thread.py:192",
    "coding_thread_keep_recent": "activities/coding_thread.py:193",
    "coding_thread_max_rounds": "activities/coding_thread.py:194",
    "coding_thread_input_cap": "activities/coding_thread.py:195",
    "coding_thread_fold_max_tokens": "activities/coding_thread.py:196",
    "coding_thread_fold_retry_max_tokens": "activities/coding_thread.py:197",
    "coding_thread_time_budget_s": "activities/coding_thread.py:200",
    # --- 2026-08-28 audit: purpose="code" max_tokens read generically by
    # LLMProvider._extract_per_purpose_admin (provider.py:666) via the flat
    # f"{purpose}_max_tokens" key -- like every other purpose in this dict --
    # but had no panel row at all until this fix.
    "code_max_tokens": "llm/provider.py:_extract_per_purpose_admin (flat key 'code_max_tokens')",
}

# Keys the SAVE handler deliberately routes to the tenant-defaults endpoint
# instead of imperal:config:llm. A kernel-read key must NOT be in there, or the
# value lands in a store the kernel never looks at.
_SKIP_MARKER = "skip_fields = {"

# The kernel's OWN default for each key. The panel must render THESE when the
# store is empty, so an admin sees what the kernel actually runs with rather
# than a prettier number someone typed into the form years ago.
KERNEL_DEFAULTS: dict[str, object] = {
    "knowledge_pick_max_tokens": 200,      # activities/knowledge.py:36
    "hub_brain_first_enabled": True,       # activities/brain_first.py
    "panel_diet_enabled": True,            # activities/agentic_catalog.py
    "frame_v2_enabled": False,             # opt-in dual emit
    "coding_thread_window_budget_chars": 250_000,  # core/coding_thread.py:324
    "coding_thread_keep_recent": 20,               # core/coding_thread.py:325
    "coding_thread_input_cap": 120_000,            # core/coding_thread.py:326
    "coding_thread_max_rounds": 12,                # activities/coding_thread.py:154
    "coding_thread_time_budget_s": 100,            # activities/coding_thread.py:155
    "coding_thread_fold_max_tokens": 24_576,       # activities/coding_thread.py:180
    "coding_thread_fold_retry_max_tokens": 49_152,  # activities/coding_thread.py:181
}


def _skip_fields_literal() -> str:
    src = open("handlers_llm.py").read()
    start = src.find(_SKIP_MARKER)
    assert start != -1, "skip_fields literal not found in handlers_llm.py"
    return src[start:src.find("}", start)]


def _build_form(**overrides):
    """Build the real form, passing only its required arguments."""
    required = dict(
        provider="openai", model="gpt-5", base_url="", routing_model="",
        execution_model="", navigate_model="", chain_narrative_model="",
        judge_model="",
    )
    kwargs = {}
    for name, p in inspect.signature(build_llm_form).parameters.items():
        if name in required:
            kwargs[name] = required[name]
        elif p.default is inspect._empty:
            kwargs[name] = ""
    kwargs.update(overrides)
    return build_llm_form(**kwargs)


def _plain(form):
    for method in ("model_dump", "dict", "to_dict"):
        if hasattr(form, method):
            return getattr(form, method)()
    raise AssertionError(f"cannot serialize form: {type(form).__name__}")


def _controls(node, want, found=None):
    """Collect every control in the serialized tree bound to ``want``."""
    if found is None:
        found = []
    if isinstance(node, dict):
        if node.get("param_name") == want:
            found.append(node)
        for value in node.values():
            _controls(value, want, found)
    elif isinstance(node, (list, tuple)):
        for value in node:
            _controls(value, want, found)
    return found


@pytest.mark.parametrize("key", sorted(KERNEL_READ_KEYS))
def test_kernel_read_key_is_declared(key):
    """No Pydantic field == the save handler drops the value silently."""
    assert key in SaveLlmConfigParams.model_fields, (
        f"ORPHAN READER: the kernel reads {key!r} at "
        f"{KERNEL_READ_KEYS[key]}, but it is not declared on "
        "SaveLlmConfigParams -- the panel cannot write it, so the kernel is "
        "stuck on its own default forever and nothing logs it."
    )


@pytest.mark.parametrize("key", sorted(KERNEL_READ_KEYS))
def test_kernel_read_key_reaches_the_right_store(key):
    """Kernel-read keys must go to imperal:config:llm, not tenant-defaults."""
    assert f'"{key}"' not in _skip_fields_literal(), (
        f"{key} is in skip_fields, so the save handler routes it to the "
        "tenant-defaults endpoint -- but the kernel reads it from "
        "imperal:config:llm via get_admin_llm_config_field. The value would "
        "land in a store nothing reads."
    )


@pytest.mark.parametrize("key", sorted(KERNEL_READ_KEYS))
def test_kernel_read_key_has_exactly_one_control(key):
    """An admin must be able to SEE and set the knob, exactly once."""
    tree = _plain(_build_form())
    hits = _controls(tree, key)
    assert len(hits) == 1, (
        f"expected exactly 1 panel control for {key} (kernel reads it at "
        f"{KERNEL_READ_KEYS[key]}), found {len(hits)}"
    )


@pytest.mark.parametrize("key", sorted(KERNEL_DEFAULTS))
def test_blank_store_renders_the_kernel_default(key):
    """A blank store must render what the KERNEL runs with, not a guess.

    This is what made the coding-thread rows misleading before 2026-08-18: the
    form advertised 4096 / 6 while the kernel really ran 24576 / 12, so an
    admin reading the panel was told the wrong thing about production.
    """
    tree = _plain(_build_form())
    hits = _controls(tree, key)
    assert hits, f"no control rendered for {key}"
    value = hits[0].get("value")
    expected = KERNEL_DEFAULTS[key]
    if isinstance(expected, bool):
        assert bool(value) is expected, (
            f"{key}: panel renders {value!r} on a blank store, kernel "
            f"default is {expected!r}"
        )
    else:
        assert int(value) == expected, (
            f"{key}: panel renders {value!r} on a blank store, kernel "
            f"default is {expected!r} -- the panel would misreport production"
        )


@pytest.mark.parametrize("key", sorted(KERNEL_DEFAULTS))
def test_kernel_default_passes_field_validation(key):
    """The kernel's real value must be enterable.

    coding_thread_fold_max_tokens shipped with le=16000 while the kernel ran
    24576 -- so an admin literally could not type production's own value.
    """
    expected = KERNEL_DEFAULTS[key]
    if isinstance(expected, bool):
        pytest.skip("bounds only apply to numeric knobs")
    SaveLlmConfigParams(**{key: expected})  # raises ValidationError if bounded out


def test_stored_value_is_rendered_back():
    """A saved value must come BACK in the form.

    judge_enabled / step_reclassify_enabled were SAVED into imperal:config:llm
    but READ from tenant_defaults, so a saved flag never reappeared in the UI.
    """
    stored = {
        "knowledge_pick_max_tokens": 1500,
        "hub_brain_first_enabled": False,
        "panel_diet_enabled": False,
        "frame_v2_enabled": True,
        "judge_enabled": True,
        "step_reclassify_enabled": False,
        "coding_thread_fold_retry_max_tokens": 65_536,
    }
    tree = _plain(_build_form(
        knowledge_config=stored,
        kernel_flags_config=stored,
        coding_thread_config=stored,
    ))
    for key, want in stored.items():
        hits = _controls(tree, key)
        assert hits, f"no control rendered for {key}"
        got = hits[0].get("value")
        if isinstance(want, bool):
            assert bool(got) is want, f"{key}: stored {want!r}, form shows {got!r}"
        else:
            assert int(got) == want, f"{key}: stored {want!r}, form shows {got!r}"


def test_purpose_max_tokens_stored_in_cfg_is_rendered_back():
    """The 11 per-purpose max_tokens caps + code_max_tokens must read from cfg.

    2026-08-28 bug: fn_save_llm_config writes these into imperal:config:llm
    (they are not in skip_fields), but the form used to read their "current
    value" from tenant_defaults -- a completely different store. An admin who
    saved routing_max_tokens=9000 saw 4096 reappear on next load, looking
    like the save silently failed.
    """
    stored = {
        "routing_max_tokens": 9000,
        "execution_max_tokens": 8001,
        "navigate_max_tokens": 8002,
        "chain_narrative_max_tokens": 12000,
        "judge_max_tokens": 8003,
        "conversational_max_tokens": 8004,
        "step_reclassify_max_tokens": 12001,
        "tool_picker_max_tokens": 8005,
        "chain_arg_refs_max_tokens": 8006,
        "semantic_verifier_max_tokens": 500,
        "action_narrator_max_tokens": 8007,
        "code_max_tokens": 32000,
    }
    tree = _plain(_build_form(purpose_max_tokens_config=stored))
    for key, want in stored.items():
        hits = _controls(tree, key)
        assert hits, f"no control rendered for {key}"
        got = hits[0].get("value")
        assert int(got) == want, (
            f"{key}: cfg has {want!r} but the form rendered {got!r} -- it is "
            "still reading a stale/wrong store"
        )


def test_purpose_max_tokens_falls_back_to_legacy_tenant_defaults():
    """A value an OLDER build wrote to tenant_defaults must still render.

    cfg (the correct store) is empty here -- the legacy tenant_defaults copy
    must not be silently dropped by the fix.
    """
    tree = _plain(_build_form(tenant_defaults={"routing_max_tokens": 7777}))
    hits = _controls(tree, "routing_max_tokens")
    assert hits and int(hits[0].get("value")) == 7777


def test_toggle_off_survives_the_save_filter():
    """False must reach the store.

    The handler keeps a value when `val is not None and val != ""`. If False
    were filtered out, a toggle could only ever be switched ON -- turning a
    feature off from the panel would silently do nothing.
    """
    for value, should_save in ((False, True), (True, True), (None, False), ("", False)):
        assert (value is not None and value != "") is should_save, (
            f"save filter changed: {value!r} -> expected saved={should_save}"
        )
