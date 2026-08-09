"""Admin · model governance must audit what an app STORED, not what it resolves to.

``GET /v1/apps/{id}/settings`` returns the RESOLVED config: Registry merges its
own DEFAULT_CONFIG into it and the Gateway merges PLATFORM_DEFAULTS. Auditing
or resetting from that view is indistinguishable from auditing the platform's
own defaults -- so every app looks like it pins claude-sonnet-4-6/gpt-4o-mini,
and a "reset" happily rewrites apps that had never stored anything at all.

That is not theoretical: the dry run taken against production before this fix
proposed changing wordpress-hub (which stores NO models section whatsoever) and
sharelock-v2, while reporting the 44 apps carrying real residue as clean.

These tests read from the unresolved app-scope row instead, and pin the
consequences: no phantom pins, real residue detected, and a reset that actually
prunes rather than only ever merging more keys in.
"""
from __future__ import annotations

import pytest

import handlers_model_governance as G


# ── the three shapes that exist in production ────────────────────────────── #

# wordpress-hub: no app-scope models section at all -> pure inherit.
OWN_NOTHING: dict = {}

# billing & 43 others: residue of the old form -- blank slots, but sampling
# params stored because the form wrote them on every save.
OWN_RESIDUE = {
    "primary_model": "", "intake_model": "", "analysis_model": "", "router_model": "",
    "temperature": 0.7, "max_tokens": 2048, "thinking_mode": "auto",
}

# admin: one deliberate pin plus a deliberately raised ceiling.
OWN_DELIBERATE = {
    "primary_model": "", "intake_model": "", "analysis_model": "claude-opus-4-6",
    "router_model": "", "temperature": 0.7, "max_tokens": 8192, "thinking_mode": "auto",
}

# What the RESOLVED endpoint hands back for an app that pinned nothing --
# the platform defaults, wearing the exact shape of a deliberate choice.
RESOLVED_LOOKS_PINNED = {
    "models": {
        "primary_model": "claude-sonnet-4-6",
        "intake_model": "gpt-4o-mini",
        "analysis_model": "claude-opus-4-6",
        "router_model": "gpt-4o-mini",
        "temperature": 0.7,
        "max_tokens": 2048,
    }
}


class _Resp:
    """Minimal stand-in for the httpx response the registry helpers return."""

    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def _wire(monkeypatch, *, own, apps=("app-1",), put_status: int = 200):
    """Point the handler at canned data and record every write.

    Returns (registry_puts, gateway_puts) so a test can assert not just the
    return value but WHERE the handler wrote -- a reset that never prunes and a
    reset that prunes correctly return identical summaries.
    """
    registry_puts: list[dict] = []
    gateway_puts: list[dict] = []

    app_list = [{"app_id": a, "display_name": a} for a in apps]

    async def fake_registry_get(path):
        if "?status=active" in path:
            return _Resp(app_list)
        return _Resp(RESOLVED_LOOKS_PINNED)

    async def fake_registry_put(path, data):
        registry_puts.append({"path": path, "data": data})
        return _Resp({"updated": True}, status_code=put_status)

    async def fake_admin_put(path, body, acting="", timeout=5.0):
        gateway_puts.append({"path": path, "body": body})
        return _Resp({"ok": True})

    async def fake_own_models(app_id):
        return own(app_id) if callable(own) else own

    async def fake_resolve(app_id):
        return app_id

    monkeypatch.setattr(G, "_registry_get", fake_registry_get)
    monkeypatch.setattr(G, "_registry_put", fake_registry_put)
    monkeypatch.setattr(G, "_admin_put", fake_admin_put)
    monkeypatch.setattr(G, "_own_models", fake_own_models)
    monkeypatch.setattr(G, "_resolve_app_id", fake_resolve)
    # The prune is gated on gateway credentials; without them the handler
    # correctly refuses to claim a completed reset. Supply them so these tests
    # exercise the prune itself rather than the missing-token guard (which has
    # its own test below).
    monkeypatch.setattr(G, "AUTH_GW", "http://gateway.test", raising=False)
    monkeypatch.setattr(G, "AUTH_SERVICE_TOKEN", "test-token", raising=False)
    return registry_puts, gateway_puts


def _audit_params(**kw):
    return G.AuditExtModelsParams(**kw)


def _reset_params(**kw):
    return G.ResetExtModelsParams(**kw)


# ── the audit ────────────────────────────────────────────────────────────── #

@pytest.mark.asyncio
async def test_audit_does_not_invent_pins_for_an_app_that_stored_nothing(ctx, monkeypatch):
    """The reported bug, at the audit layer.

    wordpress-hub stores no models section. Reading the resolved view made it
    look like it pinned all four slots.
    """
    _wire(monkeypatch, own=OWN_NOTHING)
    res = await G.fn_audit_extension_models(ctx, _audit_params())
    assert res.status == "success"
    item = res.data["items"][0]
    assert item["uses_system_defaults"] is True
    assert item["pinned_models"] == []


@pytest.mark.asyncio
async def test_audit_never_reads_the_resolved_settings_endpoint(ctx, monkeypatch):
    """Guards the fix itself, not just its output.

    A future refactor that quietly goes back to /v1/apps/{id}/settings would
    reintroduce phantom pins while every assertion above still passed, because
    the canned resolved payload and the canned own-payload can agree by luck.
    """
    seen: list[str] = []

    async def tracking_registry_get(path):
        seen.append(path)
        if "?status=active" in path:
            return _Resp([{"app_id": "app-1", "display_name": "app-1"}])
        return _Resp(RESOLVED_LOOKS_PINNED)

    _wire(monkeypatch, own=OWN_NOTHING)
    monkeypatch.setattr(G, "_registry_get", tracking_registry_get)

    await G.fn_audit_extension_models(ctx, _audit_params())
    assert not any("/settings" in p for p in seen), (
        f"audit read the resolved settings view: {seen}"
    )


@pytest.mark.asyncio
async def test_audit_still_reports_the_real_residue(ctx, monkeypatch):
    """The 44 production apps: no model pinned, but sampling params stored."""
    _wire(monkeypatch, own=OWN_RESIDUE)
    res = await G.fn_audit_extension_models(ctx, _audit_params())
    item = res.data["items"][0]
    assert item["pinned_models"] == []
    assert item["forced_params"], "the residue this cleanup exists for went unreported"


@pytest.mark.asyncio
async def test_audit_reports_a_genuine_pin(ctx, monkeypatch):
    """A real choice must still be visible -- the fix must not silence it."""
    _wire(monkeypatch, own=OWN_DELIBERATE)
    res = await G.fn_audit_extension_models(ctx, _audit_params())
    item = res.data["items"][0]
    slots = [p["slot"] for p in item["pinned_models"]]
    assert slots == ["analysis_model"]
    assert item["uses_system_defaults"] is False


@pytest.mark.asyncio
async def test_audit_says_so_when_the_config_cannot_be_read(ctx, monkeypatch):
    """Silence must never be reported as a clean bill of health."""
    _wire(monkeypatch, own=lambda _aid: None)
    res = await G.fn_audit_extension_models(ctx, _audit_params())
    assert res.status == "success"
    assert res.data.get("unreadable_app_ids"), "an unreadable app was reported as clean"


# ── the reset ────────────────────────────────────────────────────────────── #

@pytest.mark.asyncio
async def test_reset_leaves_an_already_clean_app_completely_alone(ctx, monkeypatch):
    """The dry run against production wanted to 'reset' wordpress-hub.

    It stores nothing. There is nothing to reset, and touching it would CREATE
    the very app-scope row the cleanup is meant to remove.
    """
    registry_puts, gateway_puts = _wire(monkeypatch, own=OWN_NOTHING)
    res = await G.fn_reset_extension_models(
        ctx, _reset_params(dry_run=False, confirm=True)
    )
    assert res.status == "success"
    assert res.data["unchanged"] == ["app-1"]
    assert registry_puts == [], "wrote to an app that had nothing stored"
    assert gateway_puts == [], "created an app-scope row for a clean app"


@pytest.mark.asyncio
async def test_reset_dry_run_writes_absolutely_nothing(ctx, monkeypatch):
    registry_puts, gateway_puts = _wire(monkeypatch, own=OWN_RESIDUE)
    res = await G.fn_reset_extension_models(
        ctx, _reset_params(dry_run=True, reset_sampling_params=True)
    )
    assert res.data["applied"] is False
    assert res.data["changed"], "dry run reported nothing to do"
    assert registry_puts == [] and gateway_puts == []


@pytest.mark.asyncio
async def test_reset_without_confirm_writes_nothing(ctx, monkeypatch):
    """dry_run=False alone must not be enough to touch production."""
    registry_puts, gateway_puts = _wire(monkeypatch, own=OWN_RESIDUE)
    res = await G.fn_reset_extension_models(
        ctx, _reset_params(dry_run=False, confirm=False, reset_sampling_params=True)
    )
    assert res.data["applied"] is False
    assert registry_puts == [] and gateway_puts == []


@pytest.mark.asyncio
async def test_reset_prunes_the_app_scope_row(ctx, monkeypatch):
    """Dropping a key is not enough -- both stores deep-merge.

    Without replace_paths the removed keys survive in the unified store and go
    on shadowing the cascade, so the reset would report success while changing
    nothing that matters.
    """
    registry_puts, gateway_puts = _wire(monkeypatch, own=OWN_RESIDUE)
    res = await G.fn_reset_extension_models(
        ctx, _reset_params(dry_run=False, confirm=True, reset_sampling_params=True)
    )
    assert res.data["applied"] is True
    assert registry_puts, "the authoritative Registry write never happened"
    assert gateway_puts, "the app-scope row was never pruned"
    body = gateway_puts[0]["body"]
    assert body.get("replace_paths") == ["models"]
    # And the pruned payload must genuinely omit the params, not re-pin them.
    for key in ("temperature", "max_tokens", "thinking_mode"):
        assert key not in body["config"]["models"]


@pytest.mark.asyncio
async def test_reset_failure_is_reported_not_swallowed(ctx, monkeypatch):
    registry_puts, gateway_puts = _wire(monkeypatch, own=OWN_RESIDUE, put_status=500)
    res = await G.fn_reset_extension_models(
        ctx, _reset_params(dry_run=False, confirm=True, reset_sampling_params=True)
    )
    assert res.data["failed"], "a failed write was reported as success"
    assert gateway_puts == [], "pruned the store even though the write failed"


@pytest.mark.asyncio
async def test_reset_refuses_to_claim_success_when_it_cannot_prune(ctx, monkeypatch):
    """No gateway credentials means the dropped keys are still live.

    Reporting that as a completed reset is worse than failing: the operator
    walks away believing the apps now inherit, while the stale overrides go on
    shadowing the cascade. The app must be listed as failed, not reset.
    """
    registry_puts, gateway_puts = _wire(monkeypatch, own=OWN_RESIDUE)
    monkeypatch.setattr(G, "AUTH_SERVICE_TOKEN", "", raising=False)

    res = await G.fn_reset_extension_models(
        ctx, _reset_params(dry_run=False, confirm=True, reset_sampling_params=True)
    )
    assert res.status == "success"
    assert not gateway_puts, "prune ran without credentials"
    assert res.data["failed"], "an un-pruned reset was reported as clean"
    assert not res.data["changed"], "an un-pruned app was counted as reset"


# ── the helper itself ────────────────────────────────────────────────────── #
#
# The tests above monkeypatch _own_models, so they prove how the handlers USE
# it -- not that it reads the right endpoint. That gap is exactly where the
# original bug lived, so it gets its own tests here.

class _GwSpy:
    def __init__(self, response):
        self.response = response
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, method, path, data=None, acting=None):
        self.calls.append((method.upper(), path))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


@pytest.mark.asyncio
async def test_own_models_reads_the_unresolved_app_scope_row(monkeypatch):
    """It must hit the RAW config endpoint, not /v1/apps/{id}/settings.

    The settings endpoint is the merged view; reading it is what made every app
    look pre-configured. The endpoint choice IS the fix, so it is asserted.
    """
    gw = _GwSpy({"config": {"models": {"primary_model": "claude-opus-4-6"}}})
    monkeypatch.setattr(G, "_gw_request", gw)

    got = await G._own_models("wordpress-hub")
    assert got == {"primary_model": "claude-opus-4-6"}
    assert gw.calls, "no gateway call was made"
    method, path = gw.calls[0]
    assert method == "GET"
    assert "/v1/internal/config/app/wordpress-hub" in path
    assert "/settings" not in path, "read the merged view instead of the raw row"


@pytest.mark.asyncio
async def test_own_models_returns_empty_when_the_app_stored_nothing(monkeypatch):
    """An app with no models section inherits -- that is {}, not the defaults."""
    monkeypatch.setattr(G, "_gw_request", _GwSpy({"config": {}}))
    assert await G._own_models("wordpress-hub") == {}

    monkeypatch.setattr(G, "_gw_request", _GwSpy({"config": {"models": None}}))
    assert await G._own_models("wordpress-hub") == {}


@pytest.mark.asyncio
async def test_own_models_reports_unreadable_rather_than_guessing(monkeypatch):
    """None means 'unknown'; {} would be a claim that the app inherits."""
    monkeypatch.setattr(G, "_gw_request", _GwSpy(RuntimeError("gateway down")))
    assert await G._own_models("x") is None

    monkeypatch.setattr(G, "_gw_request", _GwSpy("not a dict"))
    assert await G._own_models("x") is None


# ── deliberate pins survive a fleet-wide sweep ───────────────────────────── #
#
# The production dry run that motivated this: a sweep meant to clear residue
# from 44 apps also proposed un-pinning sharelock-v2 and admin. Reverting a
# deliberate choice is data loss to whoever made it, so a BULK run protects
# pinned apps; naming one app explicitly is still honoured.

@pytest.mark.asyncio
async def test_bulk_reset_skips_apps_with_a_deliberate_pin(ctx, monkeypatch):
    registry_puts, gateway_puts = _wire(monkeypatch, own=OWN_DELIBERATE)
    res = await G.fn_reset_extension_models(
        ctx, _reset_params(dry_run=False, confirm=True, reset_sampling_params=True)
    )
    assert res.status == "success"
    assert not registry_puts, "a deliberate pin was overwritten by a bulk sweep"
    assert not gateway_puts, "a deliberate pin was pruned by a bulk sweep"
    skipped = res.data["skipped_pinned"]
    assert [s["app_id"] for s in skipped] == ["app-1"]
    assert "analysis_model" in skipped[0]["pinned"]


@pytest.mark.asyncio
async def test_the_skip_is_visible_in_the_summary(ctx, monkeypatch):
    """A silent skip is indistinguishable from a missed app."""
    _wire(monkeypatch, own=OWN_DELIBERATE)
    res = await G.fn_reset_extension_models(
        ctx, _reset_params(dry_run=True, reset_sampling_params=True)
    )
    assert "skipped" in res.summary.lower()
    assert "include_pinned" in res.summary


@pytest.mark.asyncio
async def test_include_pinned_still_resets_them(ctx, monkeypatch):
    """The protection is a default, not a wall: opting in must work."""
    registry_puts, gateway_puts = _wire(monkeypatch, own=OWN_DELIBERATE)
    res = await G.fn_reset_extension_models(
        ctx, _reset_params(dry_run=False, confirm=True,
                           reset_sampling_params=True, include_pinned=True),
    )
    assert not res.data["skipped_pinned"]
    assert registry_puts, "include_pinned=true did not reset the pinned app"
    assert gateway_puts, "include_pinned=true did not prune the pinned app"


@pytest.mark.asyncio
async def test_naming_one_app_is_explicit_intent(ctx, monkeypatch):
    """Asking for a single app IS the confirmation -- no opt-in needed."""
    registry_puts, _ = _wire(monkeypatch, own=OWN_DELIBERATE)
    res = await G.fn_reset_extension_models(
        ctx, _reset_params(app_id="app-1", dry_run=False, confirm=True,
                           reset_sampling_params=True),
    )
    assert not res.data["skipped_pinned"], "an explicitly named app was skipped"
    assert registry_puts, "an explicitly named app was not reset"


@pytest.mark.asyncio
async def test_residue_is_still_swept_alongside_a_pinned_app(ctx, monkeypatch):
    """Protecting one app must not stop the sweep for the others."""
    def own(aid):
        return OWN_DELIBERATE if aid == "pinned-app" else OWN_RESIDUE

    registry_puts, _ = _wire(
        monkeypatch, own=own, apps=("pinned-app", "residue-app"),
    )
    res = await G.fn_reset_extension_models(
        ctx, _reset_params(dry_run=False, confirm=True, reset_sampling_params=True)
    )
    assert [s["app_id"] for s in res.data["skipped_pinned"]] == ["pinned-app"]
    assert [c["app_id"] for c in res.data["changed"]] == ["residue-app"]
    assert [p["path"] for p in registry_puts] == ["/v1/apps/residue-app/settings"]
