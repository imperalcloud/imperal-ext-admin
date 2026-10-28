"""The admin's master switch for Webbee's proactivity writes the store the kernel's living matrix reads.

Asserts the ENDPOINT, the body and the acting admin of each call (the gateway refuses a lock without an admin in
X-Acting-User) -- not merely a success result.
"""
from __future__ import annotations

import pytest

import handlers_proactivity as hp
from handlers_proactivity import ProactivityReadParams, TenantProactivityParams, UserProactivityParams

TENANT = "/v1/admin/tenant-defaults"
USER = "/v1/internal/users/"
UID = "imp_u_TARGET"


@pytest.mark.asyncio
async def test_tenant_default_and_lock_go_to_tenant_defaults_as_the_admin(monkeypatch, ctx, spy):
    gw = spy(responses={("GET", TENANT): {"settings": {"proactivity_enabled": True, "proactivity_lock": "on"}}})
    monkeypatch.setattr(hp, "_gw_request", gw)
    out = await hp.fn_set_proactivity(ctx, TenantProactivityParams(enabled=True, lock="on"))
    assert out.status == "success", getattr(out, "error", None)
    (patch,) = gw.calls_to(TENANT, "PATCH")
    assert patch["data"] == {"proactivity_enabled": True, "proactivity_lock": "on"}
    assert patch["acting"] == "imp_u_TESTUSER"


@pytest.mark.asyncio
async def test_a_tenant_write_that_did_not_land_is_an_error(monkeypatch, ctx, spy):
    gw = spy(responses={("GET", TENANT): {"settings": {"proactivity_enabled": False}}})
    monkeypatch.setattr(hp, "_gw_request", gw)
    out = await hp.fn_set_proactivity(ctx, TenantProactivityParams(enabled=True))
    assert out.status == "error"


@pytest.mark.asyncio
async def test_one_users_lock_goes_to_their_settings_as_the_admin(monkeypatch, ctx, spy):
    gw = spy(responses={("GET", USER): {"settings": {"proactivity_enabled": False, "proactivity_lock": "off",
                                                     "_proactivity_user_can_change": False}}})
    monkeypatch.setattr(hp, "_gw_request", gw)
    out = await hp.fn_set_user_proactivity(ctx, UserProactivityParams(user_id=UID, lock="off"))
    assert out.status == "success", getattr(out, "error", None)
    (patch,) = gw.calls_to(f"{USER}{UID}/settings", "PATCH")
    assert patch["data"] == {"proactivity_lock": "off"} and patch["acting"] == "imp_u_TESTUSER"


@pytest.mark.asyncio
async def test_bad_lock_and_empty_call_touch_nothing(monkeypatch, ctx, spy):
    gw = spy()
    monkeypatch.setattr(hp, "_gw_request", gw)
    assert (await hp.fn_set_user_proactivity(ctx, UserProactivityParams(user_id=UID, lock="always"))).status == "error"
    assert (await hp.fn_set_proactivity(ctx, TenantProactivityParams())).status == "error"
    assert gw.calls == []


@pytest.mark.asyncio
async def test_read_shows_the_tenant_and_the_users_effective_value(monkeypatch, ctx, spy):
    gw = spy(responses={("GET", TENANT): {"settings": {"proactivity_enabled": True, "proactivity_lock": ""}},
                        ("GET", USER): {"settings": {"proactivity_enabled": False,
                                                     "_proactivity_user_can_change": True}}})
    monkeypatch.setattr(hp, "_gw_request", gw)
    out = await hp.fn_get_proactivity(ctx, ProactivityReadParams(user_id=UID))
    assert out.status == "success"
    assert out.data["tenant_enabled"] is True and out.data["enabled"] is False and out.data["user_can_change"] is True
