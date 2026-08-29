"""Owner report (2026-08-29), two passes:

  1. 'у нас подключен whisper ai, но в llm configs вообще нету настройки
     провайдера под это, понимаешь? А это важно!' (model override only).
  2. 'SST Provider можно было настроить, чтобы я свой ключ от любого
     провайдера мог юзать ... автоматически подкружать доступные ... модели
     для STT' (full bring-your-own-key + live model discovery).

Pins the Voice / STT (Whisper) BYOK section: it renders with a real
provider dropdown (not hardcoded to one provider), pre-fills from the saved
config, and handlers_llm.py's DEDICATED stt-merge block (NOT the generic
flat-field save loop) persists provider/model/api_key/base_url as one
nested `stt` dict under imperal:config:llm -- the same nesting trick that
lets the gateway's existing recursive api_key encrypt/mask helpers protect
stt.api_key for free, with zero new crypto code.
"""
from __future__ import annotations

import panels_llm_form_voice as voice_section
from panels_llm_models_stt import STT_PROVIDERS
from handlers_llm import fn_save_llm_config
from models_llm_config import SaveLlmConfigParams


def test_voice_section_renders_with_defaults():
    node = voice_section.build_voice_section({})
    assert node is not None


def test_voice_section_offers_more_than_one_provider():
    """BYOK means a real provider choice, not a single hardcoded option."""
    values = {opt["value"] for opt in STT_PROVIDERS}
    assert "openai" in values
    assert len(values) > 1


def test_voice_section_prefills_saved_values():
    node = voice_section.build_voice_section(
        {"stt_provider": "groq", "stt_model": "whisper-large-v3",
         "stt_base_url": "https://api.groq.com/openai/v1"}
    )
    rendered = repr(node)
    assert "whisper-large-v3" in rendered
    assert "groq" in rendered


def test_voice_section_falls_back_to_text_input_without_catalog():
    """No live catalog (never fetched / fetch failed) -> still usable."""
    node = voice_section.build_voice_section(
        {"stt_provider": "openai", "stt_model": "whisper-1"}, model_catalog=None
    )
    assert "whisper-1" in repr(node)


def test_voice_section_uses_live_catalog_when_available():
    node = voice_section.build_voice_section(
        {"stt_provider": "openai"}, model_catalog=["whisper-1", "gpt-4o-transcribe"]
    )
    assert "gpt-4o-transcribe" in repr(node)


def test_stt_fields_ARE_skipped_by_the_generic_save_loop():
    """stt_provider/model/api_key/base_url are handled by the DEDICATED
    nested-dict merge block (so stt.api_key gets the same encrypt/mask
    treatment as the top-level api_key) -- they must be excluded from the
    generic flat-field loop, or a save would double-write / clobber them
    as flat top-level keys instead of inside the nested `stt` dict."""
    import inspect

    src = inspect.getsource(fn_save_llm_config)
    start = src.index("skip_fields = {")
    end = src.index("}", start) + 1
    skip_block = src[start:end]
    for name in ("stt_provider", "stt_model", "stt_api_key", "stt_base_url"):
        assert name in skip_block, f"{name} must be routed via the nested stt merge block"


def test_stt_merge_block_exists_and_builds_nested_dict():
    """The dedicated merge block writes current['stt'] as one dict, not
    flat stt_* keys, so the gateway's recursive api_key protection applies."""
    import inspect

    src = inspect.getsource(fn_save_llm_config)
    assert 'current["stt"] = _stt' in src
    assert '_stt["api_key"] = params.stt_api_key' in src
    # Masked echo (bullet char) must NOT overwrite the stored real key.
    assert "\\u2022" in src or "•" in src


def test_save_llm_config_params_declares_all_four_stt_fields():
    fields = SaveLlmConfigParams.model_fields
    for name in ("stt_provider", "stt_model", "stt_api_key", "stt_base_url"):
        assert name in fields
