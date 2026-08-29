"""Admin · Voice / STT (Whisper) panel section (2026-08-29).

Owner report, two passes:
  1. "у нас есть в системе нашей возможность voice ... для этого функционала
     у нас подключен whisper ai, но в llm configs вообще нету настройки
     провайдера под это, понимаешь? А это важно!" (model override only).
  2. "SST Provider можно было настроить, чтобы я свой ключ от любого
     провайдера мог юзать ... автоматически подкружать доступные ... модели
     для STT" (full bring-your-own-key + live model discovery).

Persisted at ``imperal:config:llm.stt`` (a NESTED dict, not flat top-level
keys) — the auth-gateway's existing recursive api_key encrypt/mask helpers
key off the literal name "api_key" at ANY depth, so nesting under "stt" gets
stt.api_key encrypted at rest and masked on read automatically, exactly like
the top-level provider's own api_key. See handlers_llm.py's dedicated
stt-merge block (write side) and panels_llm.py's `_stt_cfg` read (read side).

api_key is write-only: the value shown here is either "" (never set) or a
masked echo (first-6•••last-3) from the gateway's read path — never the real
secret. Leaving it untouched and re-saving round-trips that mask back, and
the merge block on the write side recognises the bullet char and keeps the
existing stored key rather than overwriting it with garbage.

Model options come from panels_llm_models_stt.fetch_stt_model_catalog(),
fetched LIVE from the configured provider's own /v1/models endpoint using
this BYOK key — the same cache→live→fallback pattern the main LLM Config's
per-purpose Model selects already use (panels_llm_models.fetch_model_catalog).
No hardcoded model list: a blank/failed catalogue falls back to a plain text
Input so the section still functions with zero live data.
"""
from __future__ import annotations

from imperal_sdk import ui
from panels_llm_models_stt import STT_PROVIDERS, STT_PROVIDER_DEFAULT_BASE


def build_voice_section(defaults: dict, model_catalog: list[str] | None = None) -> object:
    """Return the Voice / STT ui.Section, pre-populated from `defaults`.

    `defaults` MUST carry `stt_provider` / `stt_model` / `stt_api_key` /
    `stt_base_url` (blank string = unset). `model_catalog` is the live
    model list for the CURRENTLY configured provider (or None/empty to fall
    back to a free-text Model input).
    """
    provider = defaults.get("stt_provider", "") or "openai"
    model_value = defaults.get("stt_model", "")

    model_field: object
    if model_catalog:
        options = [{"value": "", "label": "\u2014 platform default (whisper-1) \u2014"}]
        options += [{"value": m, "label": m} for m in model_catalog]
        model_field = ui.Select(options=options, value=model_value, param_name="stt_model")
    else:
        model_field = ui.Input(
            placeholder="whisper-1 (default)",
            param_name="stt_model",
            value=model_value,
        )

    base_url_hint = STT_PROVIDER_DEFAULT_BASE.get(provider, "")
    base_url_placeholder = (
        "Required for Custom — e.g. https://your-endpoint/v1"
        if provider == "custom"
        else f"{base_url_hint} (default — leave blank to use it)"
    )

    return ui.Section(title="\U0001f399\ufe0f Voice / Speech-to-Text (Whisper)", collapsible=True, children=[
        ui.Text(
            "Which engine transcribes voice messages sent to Webbee (panel mic "
            "and Telegram voice notes). Bring your own key for any OpenAI-"
            "Whisper-API-compatible provider. This does not affect spoken "
            "replies (TTS) — only speech-to-text.",
            variant="caption",
        ),
        ui.Text("STT Provider", variant="caption"),
        ui.Select(
            options=STT_PROVIDERS,
            value=provider,
            param_name="stt_provider",
        ),
        ui.Text(
            "STT API Key — YOUR OWN key for the provider selected above "
            "(write-only, leave blank to keep the current key).",
            variant="caption",
        ),
        ui.Input(
            placeholder="sk-\u2026  (leave blank to keep current)",
            param_name="stt_api_key",
            value=defaults.get("stt_api_key", ""),
        ),
        ui.Text(
            "Base URL — the provider's OpenAI-compatible endpoint. "
            + base_url_placeholder,
            variant="caption",
        ),
        ui.Input(
            placeholder=base_url_placeholder,
            param_name="stt_base_url",
            value=defaults.get("stt_base_url", ""),
        ),
        ui.Text(
            "STT Model — blank keeps the platform default (whisper-1). "
            "Live-fetched from the key above once saved.",
            variant="caption",
        ),
        model_field,
    ])
