"""Regression suite: the 2-step confirmation toggle must move the REAL store.

WHY THIS FILE EXISTS
--------------------
``set_user_confirmation`` used to write ``users.attributes.confirmation_enabled``
via ``PATCH /v1/users/{id}``, and ``get_user_confirmation`` read it back from the
same place. But the value that actually governs the destructive/write gate lives
in ``unified_config`` (scope=user) ``user_settings.confirmation_enabled`` — the
row the Auth GW serves to the kernel every turn
(``kernel_resolve._resolve_settings`` -> ``kctx.confirmation_enabled``).

Measured on live prod before the fix: 0/38 active users had the attribute set at
all, while 13/13 resolvable users tracked ``unified_config`` exactly; replaying
the old write path returned HTTP 200 and left the gate untouched. So an admin
could "enable" 2-step for a user and the gate stayed OFF — silently, in the
dangerous direction — while the reader reported "inherit" for everyone, hiding
the misconfiguration.

The confirmation gate is mandatory safety machinery, so these tests assert the
ENDPOINT each handler talks to, not merely that it returned success. A test that
only checked ``result.status == "success"`` would pass against the buggy version
and is therefore worthless here.
"""
from __future__ import annotations

import pytest

import handlers_system as hs
# Both param models are defined IN handlers_system; importing them from
# anywhere else risks testing a different class than the handler validates.
from handlers_system import UserConfirmationParams, UserIdParams

SETTINGS = "/v1/internal/users/"   # + {id}/settings  -> the store the kernel reads
USERS = "/v1/users/"               # legacy attributes store (display mirror only)
UID = "imp_u_TESTUSER"


def _settings(enabled, **extra):
    return {"user_id": UID, "settings": {"confirmation_enabled": enabled, **extra}}


# ─── set_user_confirmation: writes the authoritative store ──────────── #


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
async def test_set_writes_the_store_the_kernel_reads(monkeypatch, ctx, spy, enabled):
    """The write MUST go to the internal settings endpoint (unified_config).

    Guards the exact regression: writing only ``users.attributes`` leaves the
    gate untouched, so an admin 'enabling' 2-step would change nothing.
    """
    gw = spy(responses={("GET", SETTINGS): _settings(enabled)})
    monkeypatch.setattr(hs, "_gw_request", gw)

    result = await hs.fn_set_user_confirmation(
        ctx, UserConfirmationParams(user_id=UID, enabled=enabled, skip_read=False))

    assert result.status == "success", getattr(result, "error", None)

    writes = gw.calls_to(f"{SETTINGS}{UID}/settings", "PATCH")
    assert writes, f"no PATCH to the authoritative store; calls were: {gw.summary}"
    assert writes[0]["data"]["confirmation_enabled"] is enabled

    # the settings write must not be a side effect of the attributes mirror
    attr_writes = gw.calls_to(f"{USERS}{UID}", "PATCH")
    assert all(SETTINGS not in c["path"] for c in attr_writes)


@pytest.mark.asyncio
async def test_set_sends_skip_read_to_the_authoritative_store(monkeypatch, ctx, spy):
    """skip_read must ride along on the settings write, not only the mirror."""
    gw = spy(responses={("GET", SETTINGS): _settings(True)})
    monkeypatch.setattr(hs, "_gw_request", gw)

    await hs.fn_set_user_confirmation(
        ctx, UserConfirmationParams(user_id=UID, enabled=True, skip_read=True))

    body = gw.calls_to(f"{SETTINGS}{UID}/settings", "PATCH")[0]["data"]
    assert body["confirmation_skip_read"] is True


@pytest.mark.asyncio
async def test_set_fails_loudly_when_the_write_did_not_persist(monkeypatch, ctx, spy):
    """Never report success on an unconfirmed write.

    If the gateway accepts the PATCH but still serves the old value, the admin
    must be told — a false 'enabled' on a safety gate is the dangerous outcome.
    """
    gw = spy(responses={("GET", SETTINGS): _settings(False)})  # asked True, still False
    monkeypatch.setattr(hs, "_gw_request", gw)

    result = await hs.fn_set_user_confirmation(
        ctx, UserConfirmationParams(user_id=UID, enabled=True, skip_read=False))

    assert result.status == "error"
    assert "did not persist" in (result.error or "")


@pytest.mark.asyncio
async def test_set_surfaces_gateway_error_and_never_mirrors(monkeypatch, ctx, spy):
    """A failed authoritative write must abort — no mirror, no success."""
    gw = spy(responses={("PATCH", SETTINGS): {"error": "HTTP 503: upstream down"}})
    monkeypatch.setattr(hs, "_gw_request", gw)

    result = await hs.fn_set_user_confirmation(
        ctx, UserConfirmationParams(user_id=UID, enabled=True, skip_read=False))

    assert result.status == "error"
    assert "503" in (result.error or "")
    assert not gw.hit(f"{USERS}{UID}", "PATCH"), \
        "mirrored a value the authoritative store rejected"


@pytest.mark.asyncio
async def test_set_survives_a_failing_display_mirror(monkeypatch, ctx, spy):
    """The mirror is cosmetic: its failure must not fail the real change."""
    gw = spy(responses={
        ("GET", SETTINGS): _settings(True),
        ("PATCH", f"{USERS}{UID}"): {"error": "HTTP 500: attributes write failed"},
    })
    monkeypatch.setattr(hs, "_gw_request", gw)

    result = await hs.fn_set_user_confirmation(
        ctx, UserConfirmationParams(user_id=UID, enabled=True, skip_read=False))

    assert result.status == "success"
    assert gw.hit(f"{SETTINGS}{UID}/settings", "PATCH")


# ─── get_user_confirmation: reports the EFFECTIVE value ─────────────── #


@pytest.mark.asyncio
@pytest.mark.parametrize("effective", [True, False])
async def test_get_reports_the_effective_value_not_the_attribute(
        monkeypatch, ctx, spy, effective):
    """The reader must answer from the store the kernel reads.

    The attributes mirror is deliberately set to the OPPOSITE value: a reader
    that still trusts ``users.attributes`` returns the wrong answer and fails.
    """
    gw = spy(responses={
        ("GET", f"{SETTINGS}{UID}/settings"): _settings(effective),
        ("GET", f"{USERS}{UID}"): {
            "email": "user@example.com", "role": "user",
            "attributes": {"confirmation_enabled": not effective},
        },
    })
    monkeypatch.setattr(hs, "_gw_request", gw)

    result = await hs.fn_get_user_confirmation(ctx, UserIdParams(user_id=UID))

    assert result.status == "success"
    assert result.data["enabled"] is effective
    assert gw.hit(f"{SETTINGS}{UID}/settings", "GET"), \
        f"never consulted the authoritative store; calls: {gw.summary}"


@pytest.mark.asyncio
async def test_get_falls_back_to_the_attribute_when_settings_unreachable(
        monkeypatch, ctx, spy):
    """If the settings endpoint is down, fall back rather than claim 'off'.

    Reporting a confident ``False`` for an unreachable store would tell an
    admin the gate is disabled when it may well be armed.
    """
    gw = spy(responses={
        ("GET", f"{SETTINGS}{UID}/settings"): {"error": "HTTP 502: gateway"},
        ("GET", f"{USERS}{UID}"): {
            "email": "user@example.com", "role": "user",
            "attributes": {"confirmation_enabled": True},
        },
    })
    monkeypatch.setattr(hs, "_gw_request", gw)

    result = await hs.fn_get_user_confirmation(ctx, UserIdParams(user_id=UID))

    assert result.status == "success"
    assert result.data["enabled"] is True


@pytest.mark.asyncio
async def test_get_reports_none_when_no_explicit_value_anywhere(monkeypatch, ctx, spy):
    """No stored value -> 'unknown', never a fabricated False."""
    gw = spy(responses={
        ("GET", f"{SETTINGS}{UID}/settings"): {"user_id": UID, "settings": {}},
        ("GET", f"{USERS}{UID}"): {
            "email": "user@example.com", "role": "user", "attributes": {},
        },
    })
    monkeypatch.setattr(hs, "_gw_request", gw)

    result = await hs.fn_get_user_confirmation(ctx, UserIdParams(user_id=UID))

    assert result.status == "success"
    assert result.data["enabled"] is None
    assert "unknown" in (result.summary or "")


@pytest.mark.asyncio
async def test_get_surfaces_a_missing_user(monkeypatch, ctx, spy):
    gw = spy(responses={("GET", f"{USERS}{UID}"): {"error": "HTTP 404: user not found"}})
    monkeypatch.setattr(hs, "_gw_request", gw)

    result = await hs.fn_get_user_confirmation(ctx, UserIdParams(user_id=UID))

    assert result.status == "error"
    assert "404" in (result.error or "")


# ─── round-trip ─────────────────────────────────────────────────────── #


@pytest.mark.asyncio
async def test_set_then_get_agree_through_the_same_store(monkeypatch, ctx, spy):
    """What the admin sets is what the next read reports — via one store."""
    state = {"confirmation_enabled": False}

    class Stateful(spy):
        async def __call__(self, method, path, data=None, acting=None):
            self.calls.append({"method": method.upper(), "path": path,
                               "data": data, "acting": acting})
            if "/settings" in path:
                if method.upper() == "PATCH":
                    state.update(
                        {k: v for k, v in (data or {}).items()
                         if k == "confirmation_enabled"})
                return {"user_id": UID, "settings": dict(state)}
            if method.upper() == "GET":
                return {"email": "user@example.com", "role": "user", "attributes": {}}
            return {}

    gw = Stateful()
    monkeypatch.setattr(hs, "_gw_request", gw)

    await hs.fn_set_user_confirmation(
        ctx, UserConfirmationParams(user_id=UID, enabled=True, skip_read=False))
    result = await hs.fn_get_user_confirmation(ctx, UserIdParams(user_id=UID))

    assert result.data["enabled"] is True, \
        "set and get disagree — they are not sharing one store"
