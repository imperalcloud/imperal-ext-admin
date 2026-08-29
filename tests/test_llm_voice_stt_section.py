"""Owner report (2026-08-29): 'у нас подключен whisper ai, но в llm configs
вообще нету настройки провайдера под это, понимаешь? А это важно!'

Pins the new Voice / STT (Whisper) section: it renders, pre-fills from the
saved config, and the generic save loop in handlers_llm.py actually
persists stt_provider/stt_model to imperal:config:llm (they are not in
skip_fields, so the field-name contract is what makes this real -- not a
special-cased write path).
"""
from __future__ import annotations

import panels_llm_form_voice as voice_section
from handlers_llm import fn_save_llm_config
from models_llm_config import SaveLlmConfigParams


def test_voice_section_renders_with_defaults():
    node = voice_section.build_voice_section({})
    assert node is not None


def test_voice_section_prefills_saved_values():
    node = voice_section.build_voice_section(
        {"stt_provider": "openai", "stt_model": "gpt-4o-transcribe"}
    )
    # ui.Section stores its rendered children; find the Input for stt_model.
    rendered = repr(node)
    assert "gpt-4o-transcribe" in rendered


def test_stt_fields_are_not_skipped_by_the_generic_save_loop():
    """The generic save loop in fn_save_llm_config skips a fixed set of
    fields (routed elsewhere, e.g. tenant-defaults). stt_provider/stt_model
    must NOT be in that skip set, or a save would silently drop them."""
    import inspect

    src = inspect.getsource(fn_save_llm_config)
    # Extract the skip_fields literal set body.
    start = src.index("skip_fields = {")
    end = src.index("}", start) + 1
    skip_block = src[start:end]
    assert "stt_provider" not in skip_block
    assert "stt_model" not in skip_block


def test_save_llm_config_params_declares_stt_fields():
    fields = SaveLlmConfigParams.model_fields
    assert "stt_provider" in fields
    assert "stt_model" in fields
