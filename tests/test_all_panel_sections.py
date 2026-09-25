"""Fast comprehensive test verifying EVERY panel section renders cleanly.

Mocks network and async helpers so all 22 panels render in < 1 second.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
import pytest

import panels


class DummyCtx:
    user = {"role": "admin", "imperal_id": "imp_u_test", "email": "admin@imperal.io"}
    user_id = "imp_u_test"


# Exactly the 22 sections registered in panels._BUILDERS + dashboard
PANEL_SECTIONS = [
    ("dashboard", {}),
    ("management", {}),
    ("user_profile", {"user_id": "imp_u_test"}),
    ("extensions", {}),
    ("roles", {}),
    ("scopes", {}),
    ("audit", {}),
    ("billing_analytics", {}),
    ("credits", {"user_id": "imp_u_test"}),
    ("email", {}),
    ("system", {}),
    ("llm", {}),
    ("pricing", {}),
    ("system_pricing", {}),
    ("plans", {}),
    ("voice", {}),
    ("ext_settings", {"app_id": "notes"}),
    ("ext_access_policy", {"app_id": "notes"}),
    ("ext_users", {"app_id": "notes"}),
    ("app_review", {}),
    ("payouts", {}),
    ("payment", {}),
]


async def _mock_cached(key, factory):
    res = factory()
    if asyncio.iscoroutine(res):
        return await res
    return res


@pytest.mark.asyncio
async def test_every_admin_panel_section_renders_cleanly():
    ctx = DummyCtx()
    failures = []

    mock_gw = AsyncMock(return_value={})
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json = lambda: []
    mock_resp.text = "[]"

    modules_with_gw = [
        "app",
        "panels_audit",
        "panels_developer",
        "panels_email",
        "panels_ext_access_policy",
        "panels_ext_settings",
        "panels_extensions",
        "panels_llm",
        "panels_payment",
        "panels_payouts",
        "panels_sections",
        "panels_user_profile",
        "panels_voice",
    ]

    patches = [patch(f"{mod}._gw_request", new=mock_gw) for mod in modules_with_gw]
    patches.extend([
        patch("app._registry_get", new=AsyncMock(return_value=mock_resp)),
        patch("panels_sections._registry_get", new=AsyncMock(return_value=mock_resp)),
        patch("handlers_billing_mode._admin_get", new=AsyncMock(return_value={})),
        patch("panels_sections._cached", new=_mock_cached),
        patch("panels_system._check_health", new=AsyncMock(return_value="Operational")),
        patch("panels_sections._check_health", new=AsyncMock(return_value="Operational")),
        patch("panels_sections._fetch_users", new=AsyncMock(return_value=[])),
        patch("panels_sections._fetch_roles", new=AsyncMock(return_value=[])),
        patch("panels_sections._fetch_extensions", new=AsyncMock(return_value=[])),
        patch("panels_sections._fetch_llm_usage", new=AsyncMock(return_value={})),
        patch("panels_sections._fetch_action_stats", new=AsyncMock(return_value={})),
        patch("app._resolve_app_id", new=AsyncMock(return_value="notes")),
        patch("panels_ext_settings._resolve_app_id", new=AsyncMock(return_value="notes")),
        patch("panels_ext_access_policy._resolve_app_id", new=AsyncMock(return_value="notes")),
    ])

    import contextlib
    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)

        # 1. Test left sidebar
        try:
            sb = await panels.admin_sidebar(ctx, active="dashboard")
            assert sb is not None, "Sidebar returned None"
            if hasattr(sb, "to_dict"):
                assert isinstance(sb.to_dict(), dict)
        except Exception as e:
            failures.append(f"sidebar: {type(e).__name__}: {e}")

        # 2. Test every single tools page / section
        for sec, kwargs in PANEL_SECTIONS:
            try:
                res = await panels.admin_tools(ctx, active=sec, section="", **kwargs)
                assert res is not None, f"Section '{sec}' returned None"
                if getattr(res, "component", None) == "Alert" and getattr(res, "props", {}).get("type") == "error":
                    failures.append(f"{sec} (kwargs={kwargs}): Alert Error -> {res.props.get('title')}: {res.props.get('message')}")
                elif hasattr(res, "to_dict"):
                    d = res.to_dict()
                    assert isinstance(d, dict)
            except Exception as e:
                failures.append(f"{sec} (kwargs={kwargs}): {type(e).__name__}: {e}")

    if failures:
        pytest.fail("Panel sections failed rendering:\n" + "\n".join(failures))
