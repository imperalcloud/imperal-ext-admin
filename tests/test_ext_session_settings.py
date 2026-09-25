"""Test that extension session, role, and user settings reflect ICNLI Clean-Context invariant.

Verifies:
1. Legacy compress_at (30) is removed.
2. max_history defaults to 10 (not legacy 40).
3. Session tab renders cleanly without legacy fields.
4. Role context_window default is 6 (not legacy 20).
5. User profile context_window placeholder falls back to 6.
"""
from __future__ import annotations

import pytest
from handlers_ext_settings import SaveSessionParams, fn_save_ext_session
from handlers_roles import UpdateRoleParams
from panels_ext_settings_ops import build_session_tab
from panels_roles import _build_role_expanded
from panels_user_profile import _role_default


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


def test_role_context_window_default_is_six():
    assert "default 6" in UpdateRoleParams.model_fields["context_window"].description

    # Test _build_role_expanded defaults context_window to 6
    role = {"name": "test_role", "id": "1"}
    nodes = _build_role_expanded(role, role_users=[], all_scopes=[])
    # Find form with context_window
    found = False
    for section in nodes:
        for child in getattr(section, "props", {}).get("children", []):
            defaults = getattr(child, "props", {}).get("defaults", {})
            if "context_window" in defaults:
                assert defaults["context_window"] == "6", f"Expected '6', got {defaults['context_window']}"
                found = True
    assert found, "context_window form field not found in role expanded nodes"


def test_user_profile_context_window_role_default():
    # When role has no context_window set, role default should be '6'
    roles = [{"name": "developer", "id": 1}]
    fallback = _role_default(roles, "developer", "context_window", 6)
    assert fallback == "6"

