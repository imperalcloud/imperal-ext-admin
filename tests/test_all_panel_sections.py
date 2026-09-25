"""Comprehensive test rendering EVERY section of the Admin extension panels.

Guarantees no NameError, AttributeError, or unhandled exceptions across every section.
"""
from __future__ import annotations

import pytest
from app import ext
import panels


class DummyCtx:
    user = {"role": "admin", "imperal_id": "imp_u_test", "email": "admin@imperal.io"}
    user_id = "imp_u_test"


SECTIONS_WITH_PARAMS = [
    ("dashboard", {}),
    ("management", {}),
    ("management", {"role_filter": "admin", "status_filter": "active"}),
    ("user_profile", {}),
    ("user_profile", {"user_id": "imp_u_test"}),
    ("extensions", {}),
    ("roles", {}),
    ("roles", {"role_filter": "admin"}),
    ("scopes", {}),
    ("scopes", {"role_filter": "admin"}),
    ("audit", {}),
    ("audit", {"hours": 12, "source": "api"}),
    ("billing_analytics", {}),
    ("billing_analytics", {"days": 7}),
    ("credits", {}),
    ("credits", {"user_id": "imp_u_test"}),
    ("email", {}),
    ("email", {"edit_case": "welcome"}),
    ("system", {}),
    ("llm", {}),
    ("llm", {"tab": "governance"}),
    ("llm", {"tab": "stt"}),
    ("pricing", {}),
    ("pricing", {"edit_id": "claude-3-7-sonnet"}),
    ("system_pricing", {}),
    ("plans", {}),
    ("voice", {}),
    ("ext_settings", {}),
    ("ext_settings", {"app_id": "notes", "tab": "general"}),
    ("ext_settings", {"app_id": "notes", "tab": "models"}),
    ("ext_settings", {"app_id": "notes", "tab": "persona"}),
    ("ext_settings", {"app_id": "notes", "tab": "ops"}),
    ("ext_access_policy", {}),
    ("ext_access_policy", {"app_id": "notes"}),
    ("ext_users", {}),
    ("ext_users", {"app_id": "notes"}),
    ("app_review", {}),
    ("payouts", {}),
    ("payment", {}),
]


@pytest.mark.asyncio
async def test_every_panel_section_renders():
    ctx = DummyCtx()
    failures = []

    # Also test sidebar
    try:
        sb = await panels.admin_sidebar(ctx, active="dashboard")
        assert sb is not None
    except Exception as e:
        failures.append(f"sidebar: {type(e).__name__}: {e}")

    # Test each section and sub-page variants
    for sec, kwargs in SECTIONS_WITH_PARAMS:
        try:
            res = await panels.admin_tools(ctx, active=sec, section="", **kwargs)
            assert res is not None, f"Section {sec} returned None"
            # Check if res is an Alert error
            if getattr(res, "component", None) == "Alert" and getattr(res, "props", {}).get("type") == "error":
                failures.append(f"{sec} (kwargs={kwargs}): UI Alert Error -> {res.props.get('title')}: {res.props.get('message')}")
            elif hasattr(res, "to_dict"):
                d = res.to_dict()
                assert isinstance(d, dict)
        except Exception as e:
            failures.append(f"{sec} (kwargs={kwargs}): Exception -> {type(e).__name__}: {e}")

    if failures:
        pytest.fail("Panel sections failed:\n" + "\n".join(failures))
