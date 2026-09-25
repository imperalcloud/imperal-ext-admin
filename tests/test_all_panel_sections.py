"""Fast comprehensive test verifying EVERY panel section and sub-route renders cleanly.

Mocks network boundaries (_gw_request, _registry_get, shared_http, _admin_get)
so that all 22 panels render in < 5s without network hangs.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
import pytest

import panels


class DummyCtx:
    user = {"role": "admin", "imperal_id": "imp_u_test", "email": "admin@imperal.io"}
    user_id = "imp_u_test"


SECTIONS_TO_TEST = [
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
async def test_every_admin_panel_section_renders_cleanly():
    ctx = DummyCtx()
    failures = []

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json = lambda: []
    mock_resp.text = "[]"

    client_mock = AsyncMock()
    client_mock.get = AsyncMock(return_value=mock_resp)
    client_mock.post = AsyncMock(return_value=mock_resp)
    client_mock.put = AsyncMock(return_value=mock_resp)
    client_mock.patch = AsyncMock(return_value=mock_resp)
    client_mock.delete = AsyncMock(return_value=mock_resp)

    shared_http_mock = MagicMock(return_value=client_mock)

    with patch("app._gw_request", new=AsyncMock(return_value={})), \
         patch("app._registry_get", new=AsyncMock(return_value=mock_resp)), \
         patch("imperal_sdk._shared_http.shared_http", new=shared_http_mock), \
         patch("handlers_billing_mode._admin_get", new=AsyncMock(return_value={})):

        # 1. Test left sidebar
        try:
            sb = await panels.admin_sidebar(ctx, active="dashboard")
            assert sb is not None, "Sidebar returned None"
            if hasattr(sb, "to_dict"):
                assert isinstance(sb.to_dict(), dict)
        except Exception as e:
            failures.append(f"sidebar: {type(e).__name__}: {e}")

        # 2. Test every single tools page / section
        for sec, kwargs in SECTIONS_TO_TEST:
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
