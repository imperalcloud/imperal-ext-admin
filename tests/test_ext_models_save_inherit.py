"""Admin · AI Models save path — "blank means inherit" is the whole point.

The bug this suite pins down: the AI Models form used to type temperature /
max_tokens / thinking_mode as Pydantic float/int/str WITH DEFAULTS (0.7 / 2048
/ "auto"). Pydantic therefore materialised a value even when the admin touched
nothing, and the handler wrote all three on EVERY save. The result was an
app-scope override on every extension that had ever had its settings opened —
silently shadowing the platform cascade forever, and billing at whatever that
pinned config implied.

The sampling params (top_p / presence_penalty / frequency_penalty) always got
this right: blank string -> key omitted -> real inherit. These tests assert the
two halves now behave identically, and that a save can genuinely REMOVE a pin
rather than only ever adding one.
"""
from __future__ import annotations

import pytest
from imperal_sdk.testing import MockContext

import handlers_ext_settings as H


class _SaveSpy:
    """Captures the section payload handed to the Registry save helper."""

    def __init__(self, status: str = "success"):
        self.status = status
        self.calls: list[dict] = []

    async def __call__(self, app_id: str, section: str, data: dict):
        self.calls.append({"app_id": app_id, "section": section, "data": data})
        from imperal_sdk import ActionResult
        if self.status == "success":
            return ActionResult.success(data={"app_id": app_id, "updated": True},
                                        summary=f"{section} saved")
        return ActionResult.error("save failed")

    @property
    def payload(self) -> dict:
        assert self.calls, "the handler never called the save helper"
        return self.calls[-1]["data"]


class _AdminPutSpy:
    def __init__(self):
        self.calls: list[dict] = []

    async def __call__(self, path: str, body: dict, acting: str = "", timeout: float = 5.0):
        self.calls.append({"path": path, "body": body})

        class _R:
            status_code = 200

            @staticmethod
            def json():
                return {}
        return _R()


@pytest.fixture
def save_spy(monkeypatch):
    spy = _SaveSpy()
    monkeypatch.setattr(H, "_save_section", spy)
    return spy


@pytest.fixture
def admin_put_spy(monkeypatch):
    spy = _AdminPutSpy()
    monkeypatch.setattr(H, "_admin_put", spy)
    monkeypatch.setattr(H, "AUTH_GW", "http://gw.test")
    monkeypatch.setattr(H, "AUTH_SERVICE_TOKEN", "tok")

    async def _resolve(app_id):
        return app_id
    monkeypatch.setattr(H, "_resolve_app_id", _resolve)
    return spy


def _params(**over):
    data = {"app_id": "demo-app"}
    data.update(over)
    return H.SaveModelsParams(**data)


# ── the regression itself ─────────────────────────────────────────────── #

@pytest.mark.asyncio
async def test_untouched_form_pins_absolutely_nothing(save_spy, admin_put_spy):
    """Opening the tab and hitting Save must not create ANY override.

    This is the exact user-visible complaint: a freshly deployed app showed a
    model as if it had been chosen. With every field left blank the payload
    must carry no model slot values and none of the three sampling keys.
    """
    await H.fn_save_ext_models(MockContext(), _params())

    payload = save_spy.payload
    for key in ("temperature", "max_tokens", "thinking_mode"):
        assert key not in payload, f"{key} was written despite being blank"
    for key in ("top_p", "presence_penalty", "frequency_penalty"):
        assert key not in payload
    # Model slots are always present, but blank == "— Inherit —".
    for slot in ("primary_model", "intake_model", "analysis_model", "router_model"):
        assert payload[slot] == ""


@pytest.mark.asyncio
async def test_blank_matches_the_sampling_params_exactly(save_spy, admin_put_spy):
    """The two halves of the form must be symmetric — that asymmetry WAS the bug."""
    await H.fn_save_ext_models(MockContext(), _params())
    payload = save_spy.payload
    forced = {k for k in ("temperature", "max_tokens", "thinking_mode") if k in payload}
    sampling = {k for k in ("top_p", "presence_penalty", "frequency_penalty") if k in payload}
    assert forced == sampling == set()


@pytest.mark.asyncio
async def test_explicit_values_are_still_saved(save_spy, admin_put_spy):
    """Inherit-by-default must not cost the admin the ability to pin on purpose."""
    await H.fn_save_ext_models(MockContext(), _params(
        primary_model="gpt-5",
        temperature="1.2",
        max_tokens="4096",
        thinking_mode="off",
        top_p="0.9",
    ))
    payload = save_spy.payload
    assert payload["primary_model"] == "gpt-5"
    assert payload["temperature"] == 1.2
    assert payload["max_tokens"] == 4096
    assert payload["thinking_mode"] == "off"
    assert payload["top_p"] == 0.9


@pytest.mark.asyncio
async def test_zero_temperature_survives(save_spy, admin_put_spy):
    """0 is falsy in Python — a naive `if value:` guard would silently drop it."""
    await H.fn_save_ext_models(MockContext(), _params(temperature="0"))
    assert save_spy.payload["temperature"] == 0.0


# ── validation moved out of Pydantic ──────────────────────────────────── #

@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [
    ("temperature", "5"),          # above max
    ("temperature", "-1"),         # below min
    ("temperature", "hot"),        # unparsable
    ("max_tokens", "10"),          # below min
    ("max_tokens", "999999"),      # above max
    ("max_tokens", "lots"),        # unparsable
    ("thinking_mode", "maybe"),    # not an allowed mode
])
async def test_out_of_range_values_are_refused_not_coerced(save_spy, admin_put_spy, field, value):
    """Switching to strings removed Pydantic's ge/le — the handler must still guard.

    Silently coercing (or silently dropping) a bad number would store a value
    the admin never asked for, which is the same class of bug being fixed.
    """
    result = await H.fn_save_ext_models(MockContext(), _params(**{field: value}))
    assert result.status == "error"
    assert field in (result.error or "")
    assert not save_spy.calls, "a rejected save must not reach the store"


# ── the prune ─────────────────────────────────────────────────────────── #

@pytest.mark.asyncio
async def test_save_prunes_so_an_omitted_key_actually_disappears(save_spy, admin_put_spy):
    """Omitting a key only inherits if the store stops holding the old value.

    Registry and Gateway both DEEP-MERGE a settings section, so an omitted key
    would keep its previous value and the admin could never un-pin anything.
    The handler must therefore follow the save with an explicit replace_paths
    write for the models subtree.
    """
    await H.fn_save_ext_models(MockContext(), _params())

    assert admin_put_spy.calls, "no prune write was issued"
    body = admin_put_spy.calls[-1]["body"]
    assert body.get("replace_paths") == ["models"]
    assert "models" in body.get("config", {})


@pytest.mark.asyncio
async def test_prune_failure_does_not_fail_the_save(save_spy, monkeypatch):
    """The Registry write is authoritative; a best-effort prune must not mask it."""
    async def _boom(*a, **k):
        raise RuntimeError("gateway unreachable")

    monkeypatch.setattr(H, "_admin_put", _boom)
    monkeypatch.setattr(H, "AUTH_GW", "http://gw.test")
    monkeypatch.setattr(H, "AUTH_SERVICE_TOKEN", "tok")

    async def _resolve(app_id):
        return app_id
    monkeypatch.setattr(H, "_resolve_app_id", _resolve)

    result = await H.fn_save_ext_models(MockContext(), _params())
    assert result.status == "success"


@pytest.mark.asyncio
async def test_no_prune_attempted_without_gateway_credentials(save_spy, monkeypatch):
    """Without a service token the prune would 403 — don't even try."""
    spy = _AdminPutSpy()
    monkeypatch.setattr(H, "_admin_put", spy)
    monkeypatch.setattr(H, "AUTH_SERVICE_TOKEN", "")

    result = await H.fn_save_ext_models(MockContext(), _params())
    assert result.status == "success"
    assert not spy.calls
