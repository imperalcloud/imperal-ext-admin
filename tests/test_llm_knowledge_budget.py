"""Contract test: the docs-router budget knob is REACHABLE from the panel.

WHY THIS TEST EXISTS (live incident, 2026-08-18)
------------------------------------------------
The kernel read ``knowledge_pick_max_tokens`` from the admin LLM Config
(``activities/knowledge.py:_pick_llm`` via ``get_admin_llm_config_field``)
from the day the knowledge subsystem shipped -- but NO panel field ever
wrote it. An ORPHAN READER: the store key never existed, so the hardcoded
kernel fallback (200) was the only value ``search_docs`` ever ran with, and
no admin could change it from anywhere.

200 tokens is not enough for a REASONING router model (measured live:
gpt-5-mini on purpose="routing"). Reasoning tokens count against max_tokens,
so when they consume the budget the reply carries NO text block at all --
content=[], stop_reason='end_turn', no exception, nothing logged. The picker
returns "", zero section ids are picked, and the brain is told "no
documentation found" for docs that plainly exist. Measured on 12 identical
"Webbee Code" probes: 9 OK, 3 empty, out_tokens exactly 200 on every
failure == ~25% silent doc blindness.

The assertions below are the WHOLE contract. If any breaks, the knob is
unreachable again and the failure is silent -- exactly what let the original
bug survive unnoticed.
"""
from __future__ import annotations

import inspect

import pytest

from models_llm_config import SaveLlmConfigParams
from panels_llm_form import build_llm_form

FIELD = "knowledge_pick_max_tokens"

# The kernel's own fallback (activities/knowledge.py:_DEFAULT_PICK_MAX_TOKENS).
# The form must render THIS when the store is empty, so the panel shows the
# value the kernel actually runs with -- never an aspirational number.
KERNEL_FALLBACK = 200


def _build(knowledge_config):
    """Build the real form, supplying only its required arguments."""
    required = dict(
        provider="openai", model="gpt-5", base_url="", routing_model="",
        execution_model="", navigate_model="", chain_narrative_model="",
        judge_model="",
    )
    kwargs = {}
    for name, param in inspect.signature(build_llm_form).parameters.items():
        if name in required:
            kwargs[name] = required[name]
        elif param.default is inspect._empty:
            kwargs[name] = ""
    kwargs["knowledge_config"] = knowledge_config
    return build_llm_form(**kwargs)


def _plain(form):
    for method in ("model_dump", "dict", "to_dict"):
        if hasattr(form, method):
            return getattr(form, method)()
    raise AssertionError(f"cannot serialize form: {type(form).__name__}")


def _controls(node, want=FIELD, found=None):
    """Collect every control bound to ``want`` in the serialized form tree."""
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


def test_field_is_declared_on_the_save_params():
    """Without the Pydantic field the save handler drops the value silently."""
    assert FIELD in SaveLlmConfigParams.model_fields, (
        f"{FIELD} is not declared on SaveLlmConfigParams -- the kernel reads "
        "this key, so the panel MUST be able to write it"
    )


def test_field_is_not_skipped_by_the_save_handler():
    """It must land in imperal:config:llm, NOT the tenant-defaults endpoint.

    ``get_admin_llm_config_field`` reads the Redis config store. Fields listed
    in the handler's ``skip_fields`` are routed to tenant-defaults instead --
    a field sent there would be written but never read: a NEW orphan.
    """
    import handlers_llm

    source = inspect.getsource(handlers_llm)
    start = source.find("skip_fields = {")
    assert start != -1, "skip_fields set not found in handlers_llm"
    skip_block = source[start:source.find("}", start)]
    assert FIELD not in skip_block, (
        f"{FIELD} must NOT be in skip_fields: the kernel reads it from the "
        "Redis LLM config store, not from tenant-defaults"
    )


def test_accepts_the_recommended_value_and_rejects_a_regression():
    """1500 clears the reasoning-token overhead that 200 could not."""
    params = SaveLlmConfigParams(knowledge_pick_max_tokens=1500)
    assert params.knowledge_pick_max_tokens == 1500

    # Anything below the kernel fallback would be a strict regression.
    with pytest.raises(Exception):
        SaveLlmConfigParams(knowledge_pick_max_tokens=10)


def test_form_renders_one_control_showing_the_live_value():
    """Empty store shows the kernel fallback; a set store shows the set value."""
    empty = _controls(_plain(_build(None)))
    assert len(empty) == 1, (
        f"expected exactly 1 control for {FIELD}, got {len(empty)}"
    )
    assert empty[0]["value"] == KERNEL_FALLBACK, (
        "with an empty store the panel must show the value the kernel really "
        f"runs with ({KERNEL_FALLBACK}), got {empty[0]['value']}"
    )

    configured = _controls(_plain(_build({FIELD: 1500})))
    assert len(configured) == 1
    assert configured[0]["value"] == 1500, (
        f"a stored value must reach the control, got {configured[0]['value']}"
    )
