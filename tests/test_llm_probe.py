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


def test_a_wrapped_key_that_cannot_be_unwrapped_is_not_sent(monkeypatch):
    monkeypatch.delenv("IMPERAL_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("IMAP_ENCRYPTION_KEY", raising=False)
    assert LP.unwrap_key("gAAAAAwrapped") == ""
    assert LP.unwrap_key("sk-plain") == "sk-plain"


def test_the_buttons_test_the_stored_slot(monkeypatch):
    seen = []

    async def _fake(provider, model, key, base_url="", tools=False):
        seen.append((provider, model, key, base_url, tools))
        return {"ok": True, "message": "x"}
    monkeypatch.setattr(LP, "probe", _fake)
    cfg = {"provider": "openrouter", "model": "a/b", "api_key": "k1", "base_url": "https://or/v1",
           "failover_provider": "openai", "failover_model": "gpt-x", "failover_api_key": "k2"}
    asyncio.run(PL._run_test(cfg, "main"))
    asyncio.run(PL._run_test(cfg, "failover_compat"))
    assert seen == [("openrouter", "a/b", "k1", "https://or/v1", False),
                    ("openai", "gpt-x", "k2", "", True)]
