"""Admin · LLM Config: a Test button makes the call it names.

Until 2026-11-23 the four buttons printed "verified OK" after checking only
that a key string existed. Each case below is something that "passed" then.
"""
from __future__ import annotations

import asyncio

import llm_probe as LP
import panels_llm as PL


class _Resp:
    def __init__(self, status=200, body=None, text=""):
        self.status_code, self._body, self.text = status, body, text

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


def _http(monkeypatch, resp=None, exc=None):
    calls = []

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            calls.append({"url": url, "json": json, "headers": headers})
            if exc:
                raise exc
            return resp
    monkeypatch.setattr(LP, "shared_http", lambda timeout=None: _Client())
    return calls


def _probe(**kw):
    return asyncio.run(LP.probe(**kw))


OK = _Resp(body={"model": "m-served", "choices": [{"message": {"content": "ok"}}]})


def test_a_connection_test_makes_one_real_chat_request(monkeypatch):
    calls = _http(monkeypatch, OK)
    out = _probe(provider="openrouter", model="google/gemini-3.6-flash", key="sk-secret")
    assert out["ok"] and "answered a real request" in out["message"] and "m-served" in out["message"]
    assert len(calls) == 1
    assert calls[0]["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert calls[0]["json"]["model"] == "google/gemini-3.6-flash"
    assert calls[0]["headers"] == {"Authorization": "Bearer sk-secret"}


def test_a_model_the_provider_refuses_fails_with_the_providers_words(monkeypatch):
    """The owner's case: a ':batch' model that cannot answer live requests."""
    _http(monkeypatch, _Resp(404, {"error": {"message": "This model cannot be used with the chat/completions endpoint"}}))
    out = _probe(provider="openrouter", model="google/gemini-3.6-flash:batch", key="k")
    assert not out["ok"] and "HTTP 404" in out["message"] and "cannot be used" in out["message"]


def test_a_wrong_key_fails_and_the_key_is_never_shown(monkeypatch):
    _http(monkeypatch, _Resp(401, {"error": {"message": "Incorrect API key provided: sk-secret-123"}}))
    out = _probe(provider="openai", model="gpt-x", key="sk-secret-123")
    assert not out["ok"] and "HTTP 401" in out["message"]
    assert "sk-secret-123" not in out["message"] and "***" in out["message"]


def test_no_key_or_no_base_url_calls_nothing_and_says_so(monkeypatch):
    calls = _http(monkeypatch, OK)
    assert "nothing was called" in _probe(provider="openai", model="m", key="")["message"]
    assert "nothing was called" in _probe(provider="custom", model="m", key="", base_url="")["message"]
    assert not _probe(provider="openai", model="", key="k")["ok"]
    assert calls == []


def test_a_provider_that_does_not_answer_is_a_failure(monkeypatch):
    _http(monkeypatch, exc=TimeoutError())
    out = _probe(provider="kimi", model="m", key="k")
    assert not out["ok"] and "no answer" in out["message"] and "TimeoutError" in out["message"]


def test_tool_use_passes_only_when_the_tool_is_called(monkeypatch):
    calls = _http(monkeypatch, _Resp(body={"choices": [{"message": {"tool_calls": [{"id": "1"}]}}]}))
    out = _probe(provider="openai", model="m", key="k", tools=True)
    assert out["ok"] and "called the offered tool" in out["message"]
    assert calls[0]["json"]["tools"][0]["function"]["name"] == "ping"

    _http(monkeypatch, OK)                      # answered in text, no tool call
    out = _probe(provider="openai", model="m", key="k", tools=True)
    assert not out["ok"] and "did NOT call" in out["message"]


def test_anthropic_is_asked_in_its_own_format(monkeypatch):
    calls = _http(monkeypatch, _Resp(body={"model": "claude-x", "content": [{"type": "tool_use", "name": "ping"}]}))
    out = _probe(provider="anthropic", model="claude-x", key="k", tools=True)
    assert out["ok"]
    assert calls[0]["url"] == "https://api.anthropic.com/v1/messages"
    assert calls[0]["headers"]["x-api-key"] == "k" and "input_schema" in calls[0]["json"]["tools"][0]


class _Secrets:
    """The extension's secret client: name -> value, None when not typed."""

    def __init__(self, values=None):
        self.values, self.asked = dict(values or {}), []

    async def get(self, name):
        self.asked.append(name)
        return self.values.get(name)


class _Ctx:
    def __init__(self, values=None):
        self.secrets = _Secrets(values)


def _probe_calls(monkeypatch):
    seen = []

    async def _fake(provider, model, key, base_url="", tools=False):
        seen.append((provider, model, key, base_url, tools))
        return {"ok": True, "message": "x"}
    monkeypatch.setattr(LP, "probe", _fake)
    return seen


def test_the_buttons_test_the_saved_slot_with_the_providers_secret(monkeypatch):
    seen = _probe_calls(monkeypatch)
    ctx = _Ctx({"llm_openrouter_api_key": "k1", "llm_openai_api_key": "k2"})
    # a config row written before 2026-11-23 may still carry key slots: not read
    cfg = {"provider": "openrouter", "model": "a/b", "api_key": "sk-old", "base_url": "https://openrouter.ai/api/v1",
           "failover_provider": "openai", "failover_model": "gpt-x", "failover_api_key": "sk-old2"}
    asyncio.run(PL._run_test(ctx, cfg, "main"))
    asyncio.run(PL._run_test(ctx, cfg, "failover_compat"))
    assert seen == [("openrouter", "a/b", "k1", "https://openrouter.ai/api/v1", False),
                    ("openai", "gpt-x", "k2", "", True)]
    assert ctx.secrets.asked == ["llm_openrouter_api_key", "llm_openai_api_key"]


def test_a_provider_key_goes_only_to_the_providers_own_address(monkeypatch):
    """A Base URL of another host must never receive the provider's key."""
    assert LP.may_send_key_to("openai", "")
    assert LP.may_send_key_to("openai", "https://api.openai.com/v1/")
    assert not LP.may_send_key_to("openai", "https://evil.example/v1")
    assert LP.may_send_key_to("custom", "http://10.0.0.5:11434/v1"), "custom: the address the admin saved"

    seen = _probe_calls(monkeypatch)
    ctx = _Ctx({"llm_openai_api_key": "sk-platform"})
    out = asyncio.run(PL._run_test(ctx, {"provider": "openai", "model": "m", "base_url": "https://evil.example/v1"}, "main"))
    assert not out["ok"] and "Nothing was called" in out["message"]
    assert seen == [] and ctx.secrets.asked == [], "the key was not even read"


def test_a_provider_without_a_secret_is_not_called_and_env_is_not_a_source(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    seen = _probe_calls(monkeypatch)
    out = asyncio.run(PL._run_test(_Ctx(), {"provider": "openai", "model": "m"}, "main"))
    assert not out["ok"] and "llm_openai_api_key" in out["message"] and seen == []


def test_custom_runs_with_its_secret_or_with_none(monkeypatch):
    seen = _probe_calls(monkeypatch)
    cfg = {"provider": "custom", "model": "llama", "base_url": "http://10.0.0.5:11434/v1"}
    asyncio.run(PL._run_test(_Ctx(), cfg, "main"))
    asyncio.run(PL._run_test(_Ctx({"llm_openai_compatible_api_key": "kc"}), cfg, "main"))
    assert [c[2] for c in seen] == ["", "kc"]


def test_a_secret_store_failure_is_said_not_guessed(monkeypatch):
    seen = _probe_calls(monkeypatch)

    class _Down:
        async def get(self, name):
            raise RuntimeError("vault away")
    ctx = _Ctx()
    ctx.secrets = _Down()
    out = asyncio.run(PL._run_test(ctx, {"provider": "openai", "model": "m"}, "main"))
    assert not out["ok"] and "vault away" in out["message"] and seen == []


def test_a_base_url_that_is_not_http_is_not_called(monkeypatch):
    calls = _http(monkeypatch, OK)
    out = _probe(provider="custom", model="m", key="k", base_url="file:///etc/passwd")
    assert not out["ok"] and "nothing was called" in out["message"] and calls == []
