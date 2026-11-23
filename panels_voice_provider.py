# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors.
# Licensed under the AGPL-3.0 License.
"""Admin · Voice · provider cards.

One card per voice function (speech to text, text to speech, the spoken-form
model): the wire format, the base URL, the model and - for the voice - its
voices and style. The gateway keeps these settings in one database row.

The API key is not on this page. It is this extension's app secret
``voice_api_key`` (declared in handlers_voice.py with the SDK), kept in Imperal
Vault and typed in the Secrets manager; the page shows whether it is set and
links there. A function may have its own key in ``voice_<function>_api_key``.

The model list is the provider's own, read live by the gateway with the saved
key (GET /v1/internal/billing/voice-config/models). With no key, or when the
provider refuses, the field is a plain input and the reason is shown.
"""
from __future__ import annotations

import asyncio
import logging

from imperal_sdk import ui
from imperal_sdk._shared_http import shared_http

from app import AUTH_GW, AUTH_SERVICE_TOKEN, _acting, _gw_request

log = logging.getLogger("admin")

CONFIG_PATH = "/v1/internal/billing/voice-config"
FUNCTIONS = ("stt", "tts", "speechify")

API_OPTIONS = [
    {"value": "openai", "label": "OpenAI-compatible (OpenAI, OpenRouter, Groq, your own server)"},
    {"value": "gemini", "label": "Gemini API (Google)"},
]

_TITLES = {
    "stt": "Speech to text",
    "tts": "Text to speech - the voice",
    "speechify": "Spoken-form model",
}
_WHAT = {
    "stt": "Transcribes voice messages: the panel microphone and Telegram voice notes.",
    "tts": "Speaks Webbee's replies in the panel and in Telegram.",
    "speechify": "Rewrites an answer for speaking (numbers, markdown, links) before it is voiced.",
}
_BASE_HINT = {
    "openai": "blank = api.openai.com; OpenRouter: https://openrouter.ai/api/v1",
    "gemini": "blank = generativelanguage.googleapis.com",
}


async def _post(path: str, body: dict, acting: str, timeout: float) -> dict:
    """POST with a timeout the three provider calls of a voice check fit in."""
    headers: dict = {"X-Service-Token": AUTH_SERVICE_TOKEN}
    if acting:
        headers["X-Acting-User"] = acting
    try:
        async with shared_http(timeout=timeout) as c:
            r = await c.post(f"{AUTH_GW.rstrip('/')}{path}", json=body, headers=headers)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    if r.status_code != 200:
        return {"error": f"HTTP {r.status_code}: {(r.text or '')[:300]}"}
    try:
        return r.json()
    except Exception as e:
        return {"error": f"non-JSON reply: {type(e).__name__}: {e}"}


async def _models(fn: str, acting: str) -> dict:
    try:
        res = await _gw_request("GET", f"{CONFIG_PATH}/models?function={fn}", acting=acting)
        return res if isinstance(res, dict) else {}
    except Exception as e:
        return {"models": [], "error": f"{type(e).__name__}: {e}"}


def _model_fields(sec: dict, listing: dict) -> list:
    current = sec.get("model") or ""
    models = [m for m in (listing.get("models") or []) if isinstance(m, str)]
    if not models:
        why = listing.get("error") or ("set the voice key to see the provider's own models"
                                       if not sec.get("key_set") else "the provider listed no models")
        return [
            ui.Text(f"Model - type its id ({why}).", variant="caption"),
            ui.Input(param_name="model", value=current, placeholder="model id"),
        ]
    if current and current not in models:
        models = [current] + models
    return [
        ui.Text(f"Model - {len(models)} offered by this provider for this function.", variant="caption"),
        ui.Select(options=[{"value": m, "label": m} for m in models], value=current, param_name="model"),
        ui.Text("...or a model id that is not in the list (overrides the choice above).", variant="caption"),
        ui.Input(param_name="custom_model", value="", placeholder="model id (optional)"),
    ]


_KEY_LINE = {
    "own": "Key: this function's own secret ({secret}).",
    "shared": "Key: the voice key (voice_api_key).",
    "none": "NO KEY: set the voice key first - this function does not work without it.",
}


def _secrets_link(owner: str, secret: str) -> object:
    return ui.Navigate(path=f"/ext/{owner}/secrets#{secret}")


def _key_card(cfg: dict) -> object:
    """Where the voice key is and the way to set it."""
    owner = cfg.get("secret_owner") or "admin"
    shared = cfg.get("shared_key_secret") or "voice_api_key"
    is_set = bool(cfg.get("shared_key_set"))
    return ui.Card(
        title=f"Voice API key  ·  {'set' if is_set else 'NOT SET'}",
        content=ui.Stack(direction="v", gap=1, children=[
            ui.Text(f"One key for every voice function: the secret '{shared}' of the Admin extension, "
                    "kept in Imperal Vault. It is typed in the Secrets manager and is never shown again.",
                    variant="caption"),
            ui.Button(label="Change the voice key" if is_set else "Set the voice key",
                      variant="secondary" if is_set else "primary",
                      on_click=_secrets_link(owner, shared)),
        ]),
    )


def _function_card(fn: str, sec: dict, listing: dict, owner: str = "admin") -> object:
    api = sec.get("api") or "openai"
    source = sec.get("key_source") or ("shared" if sec.get("key_set") else "none")
    own_secret = sec.get("key_secret") or f"voice_{fn}_api_key"
    off = fn == "speechify" and sec.get("enabled") is False
    children: list = [
        ui.Text(_WHAT[fn], variant="caption"),
    ]
    if fn == "speechify":
        children += [
            ui.Text("This step is optional. Off = replies are spoken exactly as written: nothing is "
                    "called and nothing is paid for it, and the reply starts sooner. Leave it on when "
                    "answers with tables, code, links or long numbers must sound natural.", variant="caption"),
            ui.Toggle(label="Rewrite replies for speaking", value=not off, param_name="enabled"),
        ]
    children += [
        ui.Text(_KEY_LINE[source].format(secret=own_secret), variant="caption"),
        ui.Text("Provider format", variant="caption"),
        ui.Select(options=API_OPTIONS, value=api, param_name="api"),
        ui.Text(f"Base URL ({_BASE_HINT.get(api, '')}).", variant="caption"),
        ui.Input(param_name="base_url", value=sec.get("base_url") or "", placeholder="https://..."),
    ]
    children += _model_fields(sec, listing)
    if fn == "tts":
        voices = [v for v in (sec.get("voices") or []) if isinstance(v, str)]
        children += [
            ui.Text("Voices users may choose (panel settings, Telegram /voice). Remove all to get "
                    "the format's own list back.", variant="caption"),
            ui.TagInput(values=voices, suggestions=voices, placeholder="voice name",
                        param_name="voices"),
            ui.Text("Default voice", variant="caption"),
            ui.Select(options=[{"value": v, "label": v} for v in voices],
                      value=sec.get("default_voice") or (voices[0] if voices else ""),
                      param_name="default_voice"),
            ui.Text("Speaking style - sent to the provider with every reply.", variant="caption"),
            ui.TextArea(param_name="style", value=sec.get("style") or "",
                        placeholder="e.g. warm, clear, confident"),
        ]
    state = "OFF" if off else ("key set" if sec.get("key_set") else "NO KEY")
    return ui.Card(
        title=f"{_TITLES[fn]}  ·  {api} / {sec.get('model') or 'no model'}  ·  {state}",
        content=ui.Stack(direction="v", gap=1, children=[
            ui.Form(
                action="save_voice_provider",
                submit_label=f"Save {_TITLES[fn].split(' - ')[0]}",
                defaults={"function": fn},
                children=children,
            ),
            ui.Button(label=f"Another key for this function only ({own_secret})", variant="ghost",
                      on_click=_secrets_link(owner, own_secret)),
        ]),
    )


def _check_alerts(result: dict) -> list:
    if result.get("error"):
        return [ui.Alert(title="Voice check did not run", message=str(result["error"]), type="error")]
    out = []
    for fn in ("speechify", "tts", "stt"):
        r = result.get(fn) or {}
        ok = bool(r.get("ok"))
        if ok:
            got = r.get("text") if "text" in r else f"{r.get('bytes', 0)} bytes of audio"
            msg = f"OK in {r.get('ms', 0)} ms: {got}"
        else:
            msg = str(r.get("error") or "no answer")
        out.append(ui.Alert(title=f"Check · {_TITLES[fn]}", message=msg, type="success" if ok else "error"))
    return out


async def build_voice_provider(ctx, run_test: str = "") -> list:
    """The provider part of the Voice page: an optional check result, three cards, the check button."""
    acting = _acting(ctx)
    cfg = await _gw_request("GET", CONFIG_PATH, acting=acting)
    if not isinstance(cfg, dict):
        return [ui.Alert(title="Voice provider settings unavailable", message=str(cfg), type="error")]
    if cfg.get("error"):
        return [ui.Alert(title="Voice provider settings unavailable", message=str(cfg["error"]), type="error")]
    listings = await asyncio.gather(*[
        _models(fn, acting) if (cfg.get(fn) or {}).get("key_set") else asyncio.sleep(0, result={})
        for fn in FUNCTIONS
    ])
    out: list = []
    if run_test:
        out += _check_alerts(await _post(f"{CONFIG_PATH}/test", {}, acting, timeout=120.0))
    out.append(_key_card(cfg))
    out.append(ui.Text(
        "Each voice function has its own provider and model. All of them use the voice key above "
        "unless a function has a key of its own.", variant="caption"))
    for fn, listing in zip(FUNCTIONS, listings):
        out.append(_function_card(fn, cfg.get(fn) or {}, listing or {}, cfg.get("secret_owner") or "admin"))
    out.append(ui.Button(
        label="Check voice now (one real call per function)", variant="ghost",
        on_click=ui.Call("__panel__tools", section="voice", run_test="1"),
    ))
    return out
