"""Tests for the extension-override CREATE path (2026-08-28).

WHY THIS TEST EXISTS
--------------------
handlers_llm.py::fn_save_llm_config always accepted
set_extension_override + override_model (+ optional override_provider) and
wrote them via set_extension_override/override_model -- but panels_llm.py
only ever rendered a Reset button for EXISTING overrides. There was no
control anywhere that could POST set_extension_override + override_model,
so the write path was reachable by API/curl but completely unreachable from
the panel UI itself. This pins:

  1. the panel renders a real Select-based Form that CAN create an override
     for any extension that doesn't already have one,
  2. extensions that already have an override are excluded from that Select
     (change = Reset then re-add, never a silent second write racing the
     first),
  3. the save handler auto-infers override_provider from override_model via
     provider_for_model when the admin (who has no override_provider Select
     to fill in) leaves it blank.
"""
from __future__ import annotations

import inspect

import pytest

import handlers_llm
from panels_llm import _build_add_override_form


def _plain(node):
    for method in ("model_dump", "dict", "to_dict"):
        if hasattr(node, method):
            return getattr(node, method)()
    return node


def _find_selects(node, found=None):
    if found is None:
        found = []
    if isinstance(node, dict):
        if node.get("param_name") in ("set_extension_override", "override_model"):
            found.append(node)
        for v in node.values():
            _find_selects(v, found)
    elif isinstance(node, (list, tuple)):
        for v in node:
            _find_selects(v, found)
    return found


def test_override_provider_is_inferred_from_override_model():
    """The panel form has no override_provider Select (see module docstring) --
    the save handler must infer it from override_model via provider_for_model,
    exactly like the failover/per-purpose pairs elsewhere in this handler."""
    src = inspect.getsource(handlers_llm.fn_save_llm_config)
    assert "provider_for_model(params.override_model)" in src, (
        "fn_save_llm_config must infer override_provider from override_model "
        "-- the panel form never renders an override_provider control, so a "
        "literal params.override_provider would always be blank and the "
        "override would inherit whatever the global provider happens to be, "
        "silently pairing the wrong key with the pinned model."
    )
    assert "params.override_provider or inferred" in src, (
        "an explicit override_provider (e.g. a future API caller) must still "
        "win over the inferred one -- inference is a fallback, not an override"
    )


_CATALOG = {"anthropic": ["claude-opus-4-6"], "openai": ["gpt-5"]}
_EXTENSIONS = [
    {"app_id": "mail", "display_name": "Mail"},
    {"app_id": "billing", "display_name": "Billing"},
    {"app_id": "notes", "display_name": "Notes"},
]


def test_renders_a_real_form_with_extension_and_model_selects():
    nodes = _build_add_override_form({}, _EXTENSIONS, _CATALOG)
    tree = [_plain(n) for n in nodes]
    selects = []
    for t in tree:
        _find_selects(t, selects)
    param_names = {s.get("param_name") for s in selects}
    assert "set_extension_override" in param_names, (
        "no control can ever POST set_extension_override -- the create path "
        "is unreachable from the UI"
    )
    assert "override_model" in param_names


def test_extensions_with_existing_override_are_excluded():
    """Changing an override is Reset-then-re-add, never a silent second write."""
    overrides = {"billing": {"model": "claude-opus-4-6", "provider": "anthropic"}}
    nodes = _build_add_override_form(overrides, _EXTENSIONS, _CATALOG)
    tree = [_plain(n) for n in nodes]
    selects = []
    for t in tree:
        _find_selects(t, selects)
    ext_select = next(s for s in selects if s.get("param_name") == "set_extension_override")
    offered = {o["value"] for o in ext_select.get("options", [])}
    assert "billing" not in offered
    assert {"mail", "notes"} <= offered


def test_no_candidates_renders_informative_text_not_a_crash():
    overrides = {e["app_id"]: {"model": "x"} for e in _EXTENSIONS}
    nodes = _build_add_override_form(overrides, _EXTENSIONS, _CATALOG)
    tree = [_plain(n) for n in nodes]
    assert any("already has an override" in str(t) for t in tree)


def test_no_extensions_installed_renders_informative_text_not_a_crash():
    nodes = _build_add_override_form({}, [], _CATALOG)
    tree = [_plain(n) for n in nodes]
    assert any("already has an override" in str(t) or "none are installed" in str(t) for t in tree)
