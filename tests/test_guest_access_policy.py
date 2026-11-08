"""Tests for guest showcase RBAC access policy editor & handlers in imperal-ext-admin."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

import handlers_extensions
import panels_ext_access_policy
from panels_ext_access_policy import _build_role_resolution, build_ext_access_policy


def _serialize_node(node) -> dict:
    if hasattr(node, "to_dict"):
        return node.to_dict()
    if hasattr(node, "model_dump"):
        return node.model_dump()
    if isinstance(node, dict):
        return node
    return {}


def test_build_role_resolution_includes_guest_deny_by_default():
    roles = [
        {"name": "admin", "scopes": ["*"]},
        {"name": "user", "scopes": ["chat:send"]},
    ]
    # Default public policy without guest_enabled -> guest is DENIED
    items = _build_role_resolution({"mode": "public"}, roles)
    text_dump = json.dumps([_serialize_node(i) for i in items])
    assert "guest" in text_dump
    assert "DENIED" in text_dump

    # Enabled with 9 functions -> guest shows PARTIAL (9 fns)
    guest_policy = {
        "mode": "public",
        "guest_enabled": True,
        "guest_allowed_functions": [
            "domain_full_check",
            "dns_lookup",
            "ssl_check",
            "http_check",
            "whois_lookup",
            "network_check",
            "seo_check",
            "email_check",
            "geo_check",
        ],
    }
    items_enabled = _build_role_resolution(guest_policy, roles)
    dump_enabled = json.dumps([_serialize_node(i) for i in items_enabled])
    assert "PARTIAL (9 fns)" in dump_enabled

    # Enabled but guest is in denied_roles -> guest is DENIED (role exception)
    denied_policy = {
        "mode": "public",
        "guest_enabled": True,
        "guest_allowed_functions": ["dns_lookup"],
        "exceptions": {"denied_roles": ["guest"]},
    }
    items_denied = _build_role_resolution(denied_policy, roles)
    dump_denied = json.dumps([_serialize_node(i) for i in items_denied])
    assert "DENIED (role" in dump_denied


@pytest.mark.asyncio
async def test_build_ext_access_policy_renders_guest_controls():
    class DummyCtx:
        user_id = "imp_u_admin"
        user = {"imperal_id": "imp_u_admin", "role": "admin"}

    policy_data = {
        "mode": "public",
        "guest_enabled": True,
        "guest_allowed_functions": ["dns_lookup", "ssl_check"],
    }
    with (
        patch.object(panels_ext_access_policy, "_resolve_app_id", AsyncMock(return_value="web-tools")),
        patch.object(panels_ext_access_policy, "_fetch_policy", AsyncMock(return_value=policy_data)),
        patch.object(panels_ext_access_policy, "_fetch_scopes", AsyncMock(return_value=[])),
        patch.object(
            panels_ext_access_policy,
            "_fetch_roles",
            AsyncMock(return_value=[{"name": "admin", "scopes": ["*"]}, {"name": "user", "scopes": []}]),
        ),
        patch.object(
            panels_ext_access_policy,
            "_fetch_app_functions",
            AsyncMock(return_value=["dns_lookup", "ssl_check"]),
        ),
    ):
        panel = await build_ext_access_policy(DummyCtx(), app_id="web-tools")
        dumped = json.dumps(_serialize_node(panel))
        assert "Guest Showcase Access" in dumped
        assert "guest_enabled" in dumped
        assert "guest_allowed_functions" in dumped
        assert "dns_lookup" in dumped
        assert "PARTIAL (2 fns)" in dumped


@pytest.mark.asyncio
async def test_set_and_get_access_policy_guest_fields():
    class DummyCtx:
        user_id = "imp_u_admin"
        user = {"imperal_id": "imp_u_admin", "role": "admin"}

    ctx = DummyCtx()
    saved_payloads: list[dict] = []

    async def custom_gw(method: str, path: str, body: dict | None = None):
        if method == "PUT" and "/v1/internal/config/app/web-tools" in path:
            saved_payloads.append(body or {})
            return {"updated": True}
        if method == "GET" and "/v1/internal/config/app/web-tools" in path:
            if saved_payloads:
                return saved_payloads[-1]
            return {"config": {"access_policy": {"mode": "public"}}}
        if path == "/v1/roles":
            return [
                {"name": "admin", "default_scopes": ["*"]},
                {"name": "user", "default_scopes": []},
            ]
        return {}

    async def custom_reg_get(path: str):
        class FakeResp:
            status_code = 200

            def json(self):
                return {
                    "tools": [
                        {"name": "dns_lookup", "action_type": "read"},
                        {"name": "ssl_check", "action_type": "read"},
                        {"name": "receive_files", "action_type": "write"},
                        {"name": "forget_files", "action_type": "delete"},
                    ]
                }

        return FakeResp()

    with (
        patch.object(handlers_extensions, "_resolve_app_id", AsyncMock(return_value="web-tools")),
        patch.object(handlers_extensions, "_gw_request", side_effect=custom_gw),
        patch.object(handlers_extensions, "_registry_get", side_effect=custom_reg_get),
        patch.object(handlers_extensions, "_invalidate_extension_caches", AsyncMock()) as mock_inv,
    ):
        params = handlers_extensions.SetAccessPolicyParams(
            app_id="web-tools",
            mode="public",
            required_scopes=[],
            denied_roles=[],
            denied_users=[],
            guest_enabled=True,
            guest_allowed_functions=["dns_lookup", "ssl_check", "*", "dns_lookup"],
        )
        res = await handlers_extensions.fn_set_access_policy(ctx, params)
        assert res.status == "success"
        assert res.data["updated"] is True
        assert res.data["guest_enabled"] is True
        # Wildcard '*' must be stripped and duplicates removed
        assert res.data["guest_allowed_functions"] == ["dns_lookup", "ssl_check"]
        mock_inv.assert_awaited_once()

        # Attempt to enable write/delete functions for guest -> rejected!
        bad_write = handlers_extensions.SetAccessPolicyParams(
            app_id="web-tools",
            mode="public",
            guest_enabled=True,
            guest_allowed_functions=["dns_lookup", "receive_files", "forget_files"],
        )
        bad_res = await handlers_extensions.fn_set_access_policy(ctx, bad_write)
        assert bad_res.status == "error"
        assert "receive_files" in (bad_res.error or "")
        assert "forget_files" in (bad_res.error or "")

        # Attempt to enable unregistered function for guest -> rejected!
        bad_unknown = handlers_extensions.SetAccessPolicyParams(
            app_id="web-tools",
            mode="public",
            guest_enabled=True,
            guest_allowed_functions=["dns_lookup", "nonexistent_fn"],
        )
        bad_unk_res = await handlers_extensions.fn_set_access_policy(ctx, bad_unknown)
        assert bad_unk_res.status == "error"
        assert "nonexistent_fn" in (bad_unk_res.error or "")

        # Updating only guest_allowed_functions (like TagInput.on_change) must preserve guest_enabled=True
        tag_only_params = handlers_extensions.SetAccessPolicyParams(
            app_id="web-tools",
            mode="public",
            guest_allowed_functions=["dns_lookup"],
        )
        tag_res = await handlers_extensions.fn_set_access_policy(ctx, tag_only_params)
        assert tag_res.status == "success"
        assert tag_res.data["updated"] is True
        assert tag_res.data["guest_enabled"] is True
        assert tag_res.data["guest_allowed_functions"] == ["dns_lookup"]

        get_res = await handlers_extensions.fn_get_access_policy(
            ctx, handlers_extensions.AppIdParams(app_id="web-tools")
        )
        assert get_res.status == "success"
        assert get_res.data["guest_enabled"] is True
        assert get_res.data["guest_allowed_functions"] == ["dns_lookup"]
        guest_row = next(r for r in get_res.data["role_resolution"] if r["role"] == "guest")
        assert guest_row["allowed"] is True
        assert guest_row["allowed_functions"] == ["dns_lookup"]
        assert guest_row["status"] == "PARTIAL (1 fns)"


@pytest.mark.asyncio
async def test_fetch_app_functions_filters_only_read_actions_and_tag_input_omits_stale_guest_enabled():
    class FakeResp:
        status_code = 200

        def json(self):
            return {
                "tools": [
                    {"name": "read_files", "action_type": "read"},
                    {"name": "file_overview", "action_type": "read"},
                    {"name": "receive_files", "action_type": "write"},
                    {"name": "forget_files", "action_type": "delete"},
                    {"name": "skeleton_refresh", "action_type": None},
                ]
            }

    with patch.object(panels_ext_access_policy, "_registry_get", AsyncMock(return_value=FakeResp())):
        fns = await panels_ext_access_policy._fetch_app_functions("file-reader")
        assert fns == ["file_overview", "read_files"]

    class DummyCtx:
        user_id = "imp_u_admin"
        user = {"imperal_id": "imp_u_admin", "role": "admin"}

    with (
        patch.object(panels_ext_access_policy, "_resolve_app_id", AsyncMock(return_value="file-reader")),
        patch.object(
            panels_ext_access_policy,
            "_fetch_policy",
            AsyncMock(return_value={"mode": "public", "guest_enabled": False, "guest_allowed_functions": ["read_files"]}),
        ),
        patch.object(panels_ext_access_policy, "_fetch_scopes", AsyncMock(return_value=[])),
        patch.object(panels_ext_access_policy, "_fetch_roles", AsyncMock(return_value=[])),
        patch.object(
            panels_ext_access_policy,
            "_fetch_app_functions",
            AsyncMock(return_value=["read_files", "file_overview"]),
        ),
    ):
        panel = await build_ext_access_policy(DummyCtx(), app_id="file-reader")
        dumped = _serialize_node(panel)
        text = json.dumps(dumped)
        assert '"param_name": "guest_allowed_functions"' in text

        def _find_tag_input(obj):
            if isinstance(obj, dict):
                if obj.get("param_name") == "guest_allowed_functions":
                    return obj
                for v in obj.values():
                    found = _find_tag_input(v)
                    if found:
                        return found
            elif isinstance(obj, list):
                for item in obj:
                    found = _find_tag_input(item)
                    if found:
                        return found
            return None

        tag_node = _find_tag_input(dumped)
        assert tag_node is not None
        on_change_str = json.dumps(tag_node.get("on_change") or {})
        assert "guest_enabled" not in on_change_str
        assert '"mode"' not in on_change_str


def test_clean_guest_functions_rejects_wildcards_and_empty():
    cleaned = handlers_extensions._clean_guest_functions(
        [" domain_full_check ", "", "*", "dns:*", "ssl_check", "domain_full_check"]
    )
    assert cleaned == ["domain_full_check", "ssl_check"]
    assert (
        handlers_extensions._resolve_guest_role_status(
            {"mode": "public", "guest_enabled": True, "guest_allowed_functions": []}
        )
        == "DENIED (guest deny-by-default)"
    )
    assert (
        handlers_extensions._resolve_guest_role_status(
            {"mode": "public", "guest_enabled": True, "guest_allowed_functions": ["dns_lookup"]}
        )
        == "PARTIAL (1 fns)"
    )


@pytest.mark.asyncio
async def test_set_access_policy_fails_closed_when_registry_unavailable():
    class DummyUser:
        imperal_id = "imp_u_admin"

    class DummyCtx:
        user = DummyUser()
        tenant_id = "default"

    ctx = DummyCtx()
    with (
        patch.object(
            handlers_extensions, "_resolve_app_id", autospec=True, return_value="web-tools"
        ),
        patch.object(
            handlers_extensions,
            "_fetch_registered_read_functions",
            autospec=True,
            return_value=None,
        ),
        patch.object(handlers_extensions, "_gw_request", autospec=True) as gw_mock,
    ):
        res = await handlers_extensions.fn_set_access_policy(
            ctx,
            handlers_extensions.SetAccessPolicyParams(
                app_id="web-tools",
                mode="public",
                guest_enabled=True,
                guest_allowed_functions=["dns_lookup"],
            ),
        )
        assert res.status == "error"
        assert "Cannot verify registered read-only functions" in (res.error or "")
        gw_mock.assert_not_called()

    # Toggle-only guest_enabled=True when stored cur_policy contains a non-read function -> rejected
    with (
        patch.object(
            handlers_extensions, "_resolve_app_id", autospec=True, return_value="file-reader"
        ),
        patch.object(
            handlers_extensions,
            "_fetch_registered_read_functions",
            autospec=True,
            return_value={"read_files", "file_overview"},
        ),
        patch.object(
            handlers_extensions,
            "_gw_request",
            autospec=True,
            return_value={
                "config": {
                    "access_policy": {
                        "mode": "public",
                        "guest_enabled": False,
                        "guest_allowed_functions": ["read_files", "receive_files"],
                    }
                }
            },
        ) as gw_mock2,
    ):
        res_toggle = await handlers_extensions.fn_set_access_policy(
            ctx,
            handlers_extensions.SetAccessPolicyParams(
                app_id="file-reader",
                mode="public",
                guest_enabled=True,
            ),
        )
        assert res_toggle.status == "error"
        assert "receive_files" in (res_toggle.error or "")
        assert gw_mock2.call_count == 1


def test_registry_settings_shape_resolves_action_type_from_manifest(tmp_path, monkeypatch):
    ext_root = tmp_path / "extensions"
    app_dir = ext_root / "web-tools"
    app_dir.mkdir(parents=True)
    (app_dir / "imperal.json").write_text(
        json.dumps(
            {
                "app_id": "web-tools",
                "version": "1.11.0",
                "tools": [
                    {"name": "dns_lookup", "action_type": "read"},
                    {"name": "ssl_check", "action_type": "read"},
                    {"name": "create_monitor", "action_type": "write"},
                    {"name": "delete_monitor", "action_type": "destructive"},
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EXTENSIONS_DIR", str(ext_root))

    # Real Registry GET /v1/apps/{id}/settings shape: activity_name + title-cased name, no action_type
    registry_payload = {
        "tools": [
            {"activity_name": "tool_dns_lookup", "name": "Dns Lookup", "description": "DNS", "domains": []},
            {"activity_name": "tool_ssl_check", "name": "Ssl Check", "description": "SSL", "domains": []},
            {"activity_name": "tool_create_monitor", "name": "Create Monitor", "description": "Write", "domains": []},
            {"activity_name": "tool_delete_monitor", "name": "Delete Monitor", "description": "Delete", "domains": []},
        ]
    }
    read_fns = handlers_extensions._extract_read_only_functions("web-tools", registry_payload)
    assert read_fns == {"dns_lookup", "ssl_check"}

    # Fails closed (None) if neither Registry nor on-disk manifest has action_type
    assert handlers_extensions._extract_read_only_functions("missing-app", registry_payload) is None


def test_admin_imperal_json_rebuilt_with_guest_fields():
    from pathlib import Path

    manifest_path = Path(__file__).resolve().parent.parent / "imperal.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["version"] == "5.16.0"
    tools_by_name = {t["name"]: t for t in manifest.get("tools", [])}
    set_pol = tools_by_name["set_access_policy"]
    props = set_pol["params_schema"]["properties"]
    assert "guest_enabled" in props
    assert "guest_allowed_functions" in props
    ret_props = set_pol["return_schema"]["properties"]
    assert "guest_enabled" in ret_props
    assert "guest_allowed_functions" in ret_props
    get_pol = tools_by_name["get_access_policy"]
    get_ret_props = get_pol["return_schema"]["properties"]
    assert "guest_enabled" in get_ret_props
    assert "guest_allowed_functions" in get_ret_props





def test_manifest_lookup_refuses_a_path_like_app_id(tmp_path, monkeypatch):
    monkeypatch.setenv("EXTENSIONS_DIR", str(tmp_path))
    (tmp_path / "evil").mkdir()
    (tmp_path / "evil" / "imperal.json").write_text('{"tools": [{"name": "x", "action_type": "read"}]}')
    assert handlers_extensions._extract_read_only_functions("../evil", {"tools": []}) is None
    assert handlers_extensions._extract_read_only_functions("evil", {"tools": []}) == {"x"}
