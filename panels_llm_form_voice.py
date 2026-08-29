"""Admin · Voice / STT (Whisper) panel section (2026-08-29).

Owner report: "у нас есть в системе нашей возможность voice ... для этого
функционала у нас подключен whisper ai, но в llm configs вообще нету
настройки провайдера под это, понимаешь? А это важно!"

Persisted at ``imperal:config:llm`` (Redis Config Store, same store every
other per-purpose model override in this form already writes to) as flat
``stt_provider`` / ``stt_model`` keys — read by the auth-gateway's
``app.voice.service.transcribe()`` through ``get_llm_config()``. A blank
model means "use the platform default" (currently OpenAI's whisper-1) —
same "blank = inherit" convention as every other model field in this form.

Only OpenAI is wired to an actual STT client on the gateway today, so the
provider Select currently offers one real choice — but it is a REAL field
(not hardcoded), so a future non-OpenAI STT engine is a read-side addition
only, never a schema migration or a second admin form.
"""
from __future__ import annotations

from imperal_sdk import ui

_STT_PROVIDERS = [
    {"value": "openai", "label": "OpenAI (Whisper)"},
]


def build_voice_section(defaults: dict) -> object:
    """Return the Voice / STT ui.Section, pre-populated from `defaults`.

    `defaults` MUST carry `stt_provider` / `stt_model` (blank string = unset,
    i.e. "use the platform default").
    """
    return ui.Section(title="\U0001f399\ufe0f Voice / Speech-to-Text (Whisper)", collapsible=True, children=[
        ui.Text(
            "Which engine transcribes voice messages sent to Webbee (panel mic "
            "and Telegram voice notes). This does not affect spoken replies "
            "(TTS) — only speech-to-text.",
            variant="caption",
        ),
        ui.Text("STT Provider", variant="caption"),
        ui.Select(
            options=_STT_PROVIDERS,
            value=defaults.get("stt_provider", "") or "openai",
            param_name="stt_provider",
        ),
        ui.Text(
            "STT Model — blank keeps the platform default (whisper-1).",
            variant="caption",
        ),
        ui.Input(
            placeholder="whisper-1 (default)",
            param_name="stt_model",
            value=defaults.get("stt_model", ""),
        ),
    ])
