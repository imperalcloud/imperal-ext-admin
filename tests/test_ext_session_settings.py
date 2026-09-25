"""Test that extension session settings reflect ICNLI Clean-Context invariant.

Verifies:
1. Legacy compress_at (30) is removed.
2. max_history defaults to 10 (not legacy 40).
3. Session tab renders cleanly without legacy fields.
"""
from __future__ import annotations

import pytest
from handlers_ext_settings import SaveSessionParams, fn_save_ext_session
from panels_ext_settings_ops import build_session_tab


def test_save_session_params_defaults_and_legacy_removal():
    params = SaveSessionParams(app_id="notes")
    assert params.max_history == 10, f"Expected max_history=10, got {params.max_history}"
    assert not hasattr(params, "compress_at"), "Legacy compress_at field must not exist"


def test_build_session_tab_no_compress_at():
    children = build_session_tab("notes", {"session": {"max_history": 10, "timeout_hours": 24}})
    form = children[0]
    defaults = form.props.get("defaults", {})
    assert "compress_at" not in defaults, "Legacy compress_at should not be in form defaults"
    assert defaults.get("max_history") == "10", f"Expected max_history='10', got {defaults.get('max_history')}"

    # Verify no input child has param_name='compress_at'
    param_names = [
        c.props.get("param_name")
        for c in form.props.get("children", [])
        if hasattr(c, "props") and "param_name" in c.props
    ]
    assert "compress_at" not in param_names, "Legacy compress_at input must not be rendered"
    assert "max_history" in param_names
