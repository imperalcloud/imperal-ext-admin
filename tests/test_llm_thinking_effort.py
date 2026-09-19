import inspect
import pytest
from models_llm_config import SaveLlmConfigParams
from panels_llm_form import build_llm_form
from panels_llm_form_tiers import build_tiers_section

def _call_form(**overrides):
    required = dict(
        provider="openai", model="gpt-4o", base_url="",
        routing_model="",
        execution_model="", navigate_model="", chain_narrative_model="",
        judge_model="",
    )
    kwargs = {}
    for name, p in inspect.signature(build_llm_form).parameters.items():
        if name in required:
            kwargs[name] = required[name]
        elif p.default is inspect._empty:
            kwargs[name] = ""
    kwargs.update(overrides)
    return build_llm_form(**kwargs)

def test_thinking_effort_fields_validation():
    # Valid params with new thinking effort & budget fields
    params = SaveLlmConfigParams(
        thinking_mode="on",
        thinking_effort="high",
        thinking_budget=16000,
        code_thinking_effort="max",
        code_thinking_budget=32000,
        panel_thinking_effort="max",
        panel_thinking_budget=64000,
        webbeesmart_thinking_effort="medium",
        webbeesmart_thinking_budget=8000,
        supersmart_thinking_effort="high",
        supersmart_thinking_budget=16000,
        ultrasmart_thinking_effort="max",
        ultrasmart_thinking_budget=32000,
    )
    assert params.thinking_effort == "high"
    assert params.code_thinking_effort == "max"
    assert params.panel_thinking_effort == "max"
    assert params.ultrasmart_thinking_effort == "max"
    assert params.ultrasmart_thinking_budget == 32000

def test_panels_llm_form_thinking_defaults():
    td = {
        "thinking_mode": "on",
        "thinking_effort": "high",
        "thinking_budget": 16000,
        "panel_thinking_effort": "max",
        "code_thinking_effort": "max",
    }
    form = _call_form(tenant_defaults=td)
    assert form is not None

def test_tiers_section_thinking_effort_inputs():
    defaults = {
        "webbeesmart_model": "claude-3-5-haiku",
        "webbeesmart_thinking_effort": "low",
        "webbeesmart_thinking_budget": 4000,
        "ultrasmart_model": "claude-3-7-sonnet",
        "ultrasmart_thinking_effort": "max",
        "ultrasmart_thinking_budget": 32000,
    }
    section = build_tiers_section(defaults=defaults, all_models=[{"label": "Sonnet", "value": "claude-sonnet"}])
    assert section is not None
