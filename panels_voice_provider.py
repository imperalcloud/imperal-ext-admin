# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors.
# Licensed under the AGPL-3.0 License.
"""Admin · Voice · provider cards.

One card per voice function (speech to text, text to speech, the spoken-form
model): the wire format, the base URL, the API key, the model and - for the
voice - its voices and style. The gateway keeps the settings in one database
row and each key in its secret store behind Vault; this page is the only way
a voice key gets in. The page never receives a key back, only whether one is
set.

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
        why = listing.get("error") or ("save a key first to see the provider's own models"
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


def _function_card(fn: str, sec: dict, listing: dict) -> object:
    api = sec.get("api") or "openai"
    key_line = ("A key is set. Leave the field blank to keep it; type a new one to replace it."
                if sec.get("key_set") else
                "No key is set - this function does not work until one is saved.")
    children: list = [
        ui.Text(_WHAT[fn], variant="caption"),
        ui.Text("Provider format", variant="caption"),
        ui.Select(options=API_OPTIONS, value=api, param_name="api"),
        ui.Text(f"Base URL ({_BASE_HINT.get(api, '')}). Changing the format or the address "
                "removes the saved key: type the key of the new provider.", variant="caption"),
        ui.Input(param_name="base_url", value=sec.get("base_url") or "", placeholder="https://..."),
        ui.Text(f"API key - stored in Vault, never shown again. {key_line}", variant="caption"),
        ui.Password(param_name="api_key", placeholder="blank = keep the saved key"),
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
    state = "key set" if sec.get("key_set") else "NO KEY"
    return ui.Card(
        title=f"{_TITLES[fn]}  ·  {api} / {sec.get('model') or 'no model'}  ·  {state}",
        content=ui.Form(
            action="save_voice_provider",
            submit_label=f"Save {_TITLES[fn].split(' - ')[0]}",
            defaults={"function": fn},
            children=children,
        ),
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
    out.append(ui.Text(
        "Each voice function has its own provider. Keys are entered only here and are kept in Vault; "
        "the gateway reads no voice key from anywhere else.", variant="caption"))
    for fn, listing in zip(FUNCTIONS, listings):
        out.append(_function_card(fn, cfg.get(fn) or {}, listing or {}))
    out.append(ui.Button(
        label="Check voice now (one real call per function)", variant="ghost",
        on_click=ui.Call("__panel__tools", section="voice", run_test="1"),
    ))
    return out
