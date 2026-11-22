"""Admin > Voice > provider: the settings go to the gateway's voice-config door
as the acting admin; the key is this extension's app secret (declared with the
SDK, kept in Imperal Vault) and is never a parameter, a form field or an echo."""
from __future__ import annotations

import json

import pytest

import handlers_voice as hv
import panels_voice_provider as pvp
from handlers_voice import SaveVoiceProviderParams

PATH = "/v1/internal/billing/voice-config"


class _Resp:
    def __init__(self, status=200, body=None, text=""):
        self.status_code = status
        self._body = body
        self.text = text or json.dumps(body or {})

    def json(self):
        return self._body


def _put_spy(resp):
    calls = []

    async def _put(path, body, acting="", timeout=5.0):
        calls.append({"path": path, "body": body, "acting": acting})
        return resp
    return _put, calls


def _plain(node) -> str:
    """Everything a rendered node carries, as text."""
    return json.dumps(node, default=lambda o: getattr(o, "__dict__", str(o)), ensure_ascii=False)


def test_the_voice_keys_are_declared_as_app_secrets_with_the_sdk():
    from app import ext
    declared = ext.secrets
    for name in ("voice_api_key", "voice_stt_api_key", "voice_tts_api_key", "voice_speechify_api_key"):
        assert name in declared, f"{name} is not declared with @ext.secret"
        assert declared[name].scope == "app"          # one key for the platform, not per user
        assert declared[name].write_mode == "user"    # typed by an admin, never written by code
    assert hv.VOICE_SHARED_SECRET == "voice_api_key"


def test_a_key_is_not_a_parameter_of_the_save():
    fields = SaveVoiceProviderParams.model_fields
    assert not [f for f in fields if "key" in f], "a key must only go through the Secrets manager"


@pytest.mark.asyncio
async def test_save_sends_one_functions_settings_to_the_voice_config_door_as_the_admin(monkeypatch, ctx):
    put, calls = _put_spy(_Resp(body={"stt": {"api": "openai", "base_url": "https://openrouter.ai/api/v1",
                                              "model": "openai/gpt-transcribe", "key_set": True}}))
    monkeypatch.setattr(hv, "_admin_put", put)
    out = await hv.fn_save_voice_provider(ctx, SaveVoiceProviderParams(
        function="stt", api="openai", base_url=" https://openrouter.ai/api/v1 ", model="openai/gpt-transcribe"))
    assert out.status == "success", getattr(out, "error", None)
    (call,) = calls
    assert call["path"] == PATH
    assert call["acting"] == "imp_u_TESTUSER"
    assert call["body"] == {"stt": {"api": "openai", "base_url": "https://openrouter.ai/api/v1",
                                    "model": "openai/gpt-transcribe"}}


@pytest.mark.asyncio
async def test_a_typed_model_id_overrides_the_list_choice_and_tts_carries_its_voices(monkeypatch, ctx):
    put, calls = _put_spy(_Resp(body={"tts": {"api": "gemini", "model": "gemini-3.8-flash-tts", "key_set": True}}))
    monkeypatch.setattr(hv, "_admin_put", put)
    out = await hv.fn_save_voice_provider(ctx, SaveVoiceProviderParams(
        function="tts", api="gemini", model="from-list", custom_model="gemini-3.8-flash-tts",
        voices=["Kore", " Puck ", ""], default_voice="Puck", style="calm"))
    assert out.status == "success", getattr(out, "error", None)
    assert calls[0]["body"] == {"tts": {"api": "gemini", "base_url": "", "model": "gemini-3.8-flash-tts",
                                        "voices": ["Kore", "Puck"], "default_voice": "Puck", "style": "calm"}}


@pytest.mark.asyncio
async def test_a_default_voice_outside_the_list_is_not_sent(monkeypatch, ctx):
    put, calls = _put_spy(_Resp(body={"tts": {"api": "gemini", "model": "m", "key_set": True}}))
    monkeypatch.setattr(hv, "_admin_put", put)
    await hv.fn_save_voice_provider(ctx, SaveVoiceProviderParams(
        function="tts", api="gemini", model="m", voices=["Kore"], default_voice="alloy"))
    assert "default_voice" not in calls[0]["body"]["tts"]


@pytest.mark.asyncio
@pytest.mark.parametrize("resp,needle", [
    (_Resp(status=403), "admin role"),
    (_Resp(status=422, text='{"detail": "stt.model is required for the gemini format"}'), "required"),
    (_Resp(body={"stt": {"api": "openai", "model": "another-model", "key_set": True}}), "did not reflect"),
])
async def test_a_save_that_did_not_land_is_an_error(monkeypatch, ctx, resp, needle):
    put, _calls = _put_spy(resp)
    monkeypatch.setattr(hv, "_admin_put", put)
    out = await hv.fn_save_voice_provider(ctx, SaveVoiceProviderParams(function="stt", model="whisper-1"))
    assert out.status == "error"
    assert needle in _plain(out)


@pytest.mark.asyncio
async def test_a_saved_function_with_no_key_says_so(monkeypatch, ctx):
    put, _calls = _put_spy(_Resp(body={"stt": {"api": "openai", "model": "whisper-1", "key_set": False}}))
    monkeypatch.setattr(hv, "_admin_put", put)
    out = await hv.fn_save_voice_provider(ctx, SaveVoiceProviderParams(function="stt", model="whisper-1"))
    assert out.status == "success"
    assert "NO KEY" in _plain(out) and "voice_api_key" in _plain(out)


def test_only_the_three_functions_and_two_formats_are_accepted():
    for bad in ({"function": "sing"}, {"function": "stt", "api": "elevenlabs"}):
        with pytest.raises(Exception):
            SaveVoiceProviderParams(**bad)


# ── the page ─────────────────────────────────────────────────────────────────

_CFG = {
    "stt": {"api": "openai", "base_url": "https://openrouter.ai/api/v1", "model": "openai/gpt-transcribe",
            "key_set": True, "key_source": "shared", "key_secret": "voice_stt_api_key"},
    "tts": {"api": "gemini", "base_url": "", "model": "gemini-3.8-flash-tts",
            "key_set": True, "key_source": "own", "key_secret": "voice_tts_api_key",
            "voices": ["Kore", "Puck"], "default_voice": "Kore", "style": "warm"},
    "speechify": {"api": "openai", "base_url": "", "model": "gpt-4o-mini",
                  "key_set": False, "key_source": "none", "key_secret": "voice_speechify_api_key"},
    "apis": ["openai", "gemini"],
    "shared_key_secret": "voice_api_key", "shared_key_set": True, "secret_owner": "admin",
}


@pytest.mark.asyncio
async def test_page_reads_settings_and_live_models_as_the_admin_and_only_for_functions_with_a_key(monkeypatch, ctx, spy):
    gw = spy(responses={
        ("GET", f"{PATH}/models?function=stt"): {"models": ["elevenlabs/scribe-v2", "openai/gpt-transcribe"]},
        ("GET", f"{PATH}/models?function=tts"): {"models": [], "error": "status=401 bad key"},
        ("GET", PATH): _CFG,
    })
    monkeypatch.setattr(pvp, "_gw_request", gw)
    nodes = await pvp.build_voice_provider(ctx)
    text = _plain(nodes)
    assert all(c["acting"] == "imp_u_TESTUSER" for c in gw.calls)
    assert gw.hit("models?function=stt") and gw.hit("models?function=tts")
    assert not gw.hit("models?function=speechify")          # no key: nothing to ask the provider with
    assert "elevenlabs/scribe-v2" in text                    # the provider's own models are offered
    assert "status=401 bad key" in text                      # a refused list says why
    assert "NO KEY" in text and "key set" in text
    assert "save_voice_provider" in text
    # the key is set in the Secrets manager, never typed on this page
    assert "/ext/admin/secrets#voice_api_key" in text
    assert "/ext/admin/secrets#voice_tts_api_key" in text
    assert "api_key\"" not in text.replace("voice_api_key", "").replace("_api_key)", "")
    assert "this function's own secret (voice_tts_api_key)" in text
    assert "Kore" in text and "Puck" in text


@pytest.mark.asyncio
async def test_page_says_when_the_settings_cannot_be_read(monkeypatch, ctx, spy):
    monkeypatch.setattr(pvp, "_gw_request", spy(default={"error": "HTTP 403: admin role required"}))
    text = _plain(await pvp.build_voice_provider(ctx))
    assert "admin role required" in text
    assert "save_voice_provider" not in text


@pytest.mark.asyncio
async def test_the_check_button_runs_one_real_check_and_shows_each_function(monkeypatch, ctx, spy):
    monkeypatch.setattr(pvp, "_gw_request", spy(responses={("GET", PATH): _CFG}, default={"models": []}))
    posted = []

    async def _post(path, body, acting, timeout):
        posted.append((path, acting))
        return {"speechify": {"ok": True, "text": "one and a half gigabytes", "ms": 400},
                "tts": {"ok": True, "bytes": 20480, "ms": 900},
                "stt": {"ok": False, "error": "voice stt via openai model=m: status=401 bad key", "ms": 300}}
    monkeypatch.setattr(pvp, "_post", _post)
    text = _plain(await pvp.build_voice_provider(ctx, run_test="1"))
    assert posted == [(f"{PATH}/test", "imp_u_TESTUSER")]
    assert "one and a half gigabytes" in text and "20480 bytes of audio" in text
    assert "status=401 bad key" in text
    await pvp.build_voice_provider(ctx)                       # no check without the button
    assert len(posted) == 1
