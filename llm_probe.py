"""Admin · one real call to an LLM provider, for the Test buttons of LLM Config.

Until 2026-11-23 all four Test buttons answered "verified OK" without calling
anything: they checked that a key string existed and printed success. A wrong
key, a model the provider does not serve (a ``:batch`` variant, a retired id)
or a wrong base URL all "passed". This module makes the call the button names
and reports what the provider said.

Two checks:
  * connection - one short chat request with the configured model;
  * tool use   - the same request with one tool offered; it passes only when
                 the model answers with a call of that tool.

The key never appears in a result: a provider that echoes it is masked.
"""
from __future__ import annotations

import time

from imperal_sdk._shared_http import shared_http

from panels_llm_models import (
    _GOOGLE_BASE_URL, _KIMI_BASE_URL, _OPENROUTER_BASE_URL, _QWEN_DEFAULT_BASE_URL,
    _ZHIPU_BASE_URL,
)

PROBE_TIMEOUT_S = 45.0

# OpenAI-compatible endpoints of the first-class providers (the same constants
# the model catalogue uses); "custom" has none and needs the Base URL field.
_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "google": _GOOGLE_BASE_URL,
    "qwen": _QWEN_DEFAULT_BASE_URL,
    "kimi": _KIMI_BASE_URL,
    "zhipu": _ZHIPU_BASE_URL,
    "openrouter": _OPENROUTER_BASE_URL,
}
_ASK = "Reply with the single word: ok"
_ASK_TOOL = "Call the ping tool now."
_TOOL_DESC = "Answers pong. Call it when asked to ping."


def _own_endpoint(provider: str, base_url: str) -> bool:
    """True when the request goes to the provider's own address: no Base URL
    typed, or the typed one is that address."""
    typed = str(base_url or "").strip().rstrip("/")
    if not typed:
        return True
    own = "https://api.anthropic.com/v1" if provider == "anthropic" else _BASE_URLS.get(provider, "")
    return bool(own) and typed == own.rstrip("/")


def may_send_key_to(provider: str, base_url: str) -> bool:
    """Whether the provider's stored key may go to this address.

    A provider with an address of its own gets its key only there: with some
    other Base URL saved, a test would hand the platform key to whatever host
    that is (security review 2026-11-23). "custom" has no address of its own -
    its key belongs to the address the admin saved for it."""
    if str(provider or "").strip().lower() in ("custom", "openai_compatible"):
        return True
    return _own_endpoint(provider, base_url)


async def key_for_test(ctx, provider: str, base_url: str = "") -> str:
    """The key a Test button runs with: the provider's secret (llm_keys.py:
    Imperal Vault), and only toward an address it may be sent to."""
    from llm_keys import key_for
    if not may_send_key_to(provider, base_url):
        return ""
    return await key_for(ctx, provider)


def _said(resp, key: str) -> str:
    """The provider's refusal in its own words, short, with the key masked."""
    try:
        body = resp.json()
        err = body.get("error", body) if isinstance(body, dict) else body
        text = (err.get("message") if isinstance(err, dict) else None) or str(err)
    except Exception:
        text = resp.text or "(empty body)"
    text = " ".join(str(text).split())[:300]
    return text.replace(key, "***") if key else text


async def probe(provider: str, model: str, key: str, base_url: str = "",
                tools: bool = False) -> dict:
    """One real request. Returns ``{"ok": bool, "message": str}``."""
    provider, model = str(provider or "").strip(), str(model or "").strip()
    if not provider:
        return {"ok": False, "message": "No provider is configured for this slot."}
    if not model:
        return {"ok": False, "message": f"No model is configured for {provider}."}
    if not key and provider != "custom":
        return {"ok": False, "message": f"No API key for {provider}; nothing was called."}

    ask = _ASK_TOOL if tools else _ASK
    if provider == "anthropic":
        url = "https://api.anthropic.com/v1/messages"
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
        body: dict = {"model": model, "max_tokens": 256,
                      "messages": [{"role": "user", "content": ask}]}
        if tools:
            body["tools"] = [{"name": "ping", "description": _TOOL_DESC,
                              "input_schema": {"type": "object", "properties": {}}}]
    else:
        base = str(base_url or "").strip() or _BASE_URLS.get(provider, "")
        if not base:
            return {"ok": False, "message": f"{provider} needs a Base URL; nothing was called."}
        if not base.lower().startswith(("https://", "http://")):
            return {"ok": False, "message": "The Base URL must start with https:// or http://; nothing was called."}
        url = base.rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        # no token cap: providers disagree on its name (max_tokens vs
        # max_completion_tokens) and the question asks for one word
        body = {"model": model, "messages": [{"role": "user", "content": ask}]}
        if tools:
            body["tools"] = [{"type": "function", "function": {
                "name": "ping", "description": _TOOL_DESC,
                "parameters": {"type": "object", "properties": {}}}}]

    started = time.monotonic()
    try:
        async with shared_http(timeout=PROBE_TIMEOUT_S) as c:
            resp = await c.post(url, json=body, headers=headers)
    except Exception as e:
        return {"ok": False, "message": f"{provider}/{model}: no answer from {url} "
                                        f"({type(e).__name__}: {str(e)[:160] or 'no detail'})"}
    took = time.monotonic() - started
    if resp.status_code != 200:
        return {"ok": False, "message": f"{provider}/{model}: HTTP {resp.status_code} - {_said(resp, key)}"}
    try:
        data = resp.json()
    except Exception:
        return {"ok": False, "message": f"{provider}/{model}: HTTP 200 with a body that is not JSON"}

    if provider == "anthropic":
        blocks = data.get("content") or []
        called = any(isinstance(b, dict) and b.get("type") == "tool_use" for b in blocks)
        answered = bool(blocks)
    else:
        msg = ((data.get("choices") or [{}])[0] or {}).get("message") or {}
        called = bool(msg.get("tool_calls"))
        answered = bool(msg.get("content") or called)
    served = str(data.get("model") or model)

    if tools:
        if called:
            return {"ok": True, "message": f"{provider}/{served} called the offered tool in {took:.1f} s."}
        return {"ok": False, "message": f"{provider}/{served} answered in {took:.1f} s but did NOT call "
                                        "the offered tool: it cannot drive tools as configured."}
    if not answered:
        return {"ok": False, "message": f"{provider}/{served}: HTTP 200 with an empty answer."}
    return {"ok": True, "message": f"{provider}/{served} answered a real request in {took:.1f} s."}
