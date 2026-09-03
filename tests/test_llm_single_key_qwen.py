"""Contract test: ONE API Key field serves the selected provider (2026-08-28).

WHY THIS TEST EXISTS
--------------------
The LLM Config form used to carry a SECOND key input ("Qwen (DashScope) API
Key") next to the normal one, because the kernel resolver gave a dedicated
``qwen_api_key`` slot precedence over the shared ``api_key`` slot. The admin
objection was correct and structural: the panel must not ask for the same
thing twice, and nothing here is Qwen-specific in principle -- every provider
in the select is "the provider selected above".

So the field was retired. The single API Key input now writes ``api_key`` for
whichever provider is selected, and the kernel reads it for Qwen too
(``config_resolver.config_from_store``: dedicated legacy slot first, shared
slot otherwise). The rules below are what keeps that collapse honest; if one
breaks, an admin's key silently lands in a slot nothing reads.
"""
from __future__ import annotations

import inspect

import pytest

import handlers_llm
import panels_llm_models as plm
from models_llm_config import SaveLlmConfigParams
from panels_llm_form import build_llm_form


def _plain(node):
    for method in ("model_dump", "dict", "to_dict"):
        if hasattr(node, method):
            return getattr(node, method)()
    raise AssertionError(f"cannot serialize: {type(node).__name__}")


def _controls(node, found=None):
    """Every control in the form tree that is bound to a param_name."""
    if found is None:
        found = {}
    if isinstance(node, dict):
        pn = node.get("param_name")
        if pn:
            found.setdefault(pn, []).append(node)
        for value in node.values():
            _controls(value, found)
    elif isinstance(node, (list, tuple)):
        for value in node:
            _controls(value, found)
    return found


def _form() -> dict:
    required = dict(
        provider="qwen", model="qwen3-max", base_url="", routing_model="",
        execution_model="", navigate_model="", chain_narrative_model="",
        judge_model="",
    )
    kwargs = {}
    for name, param in inspect.signature(build_llm_form).parameters.items():
        if name in required:
            kwargs[name] = required[name]
        elif param.default is inspect._empty:
            kwargs[name] = ""
    return _plain(build_llm_form(**kwargs))


# ── 1. The redundant field is GONE, from both the model and the form ───────

def test_no_dedicated_qwen_key_param():
    assert "qwen_api_key" not in SaveLlmConfigParams.model_fields, (
        "The panel must not ask for a second Qwen key: the single API Key "
        "input serves whichever provider is selected."
    )


def test_no_dedicated_kimi_or_zhipu_key_param():
    """One key = one vendor's models, but ONE field per pair (2026-08-30):
    kimi/zhipu are first-class providers, yet their keys are entered through
    the SAME single API Key input (or Failover API Key) as every other
    provider — never a dedicated per-vendor field."""
    assert "kimi_api_key" not in SaveLlmConfigParams.model_fields
    assert "zhipu_api_key" not in SaveLlmConfigParams.model_fields


def test_form_renders_no_qwen_key_control():
    controls = _controls(_form())
    assert "qwen_api_key" not in controls, (
        "A qwen_api_key control would write a store slot the kernel only "
        "reads for back-compat -- a dead field by then."
    )


def test_form_renders_no_kimi_or_zhipu_key_control():
    controls = _controls(_form())
    assert "kimi_api_key" not in controls
    assert "zhipu_api_key" not in controls


def test_form_renders_exactly_one_key_input_per_pair():
    """One shared key for the default pair, one for the failover pair."""
    controls = _controls(_form())
    assert len(controls.get("api_key", [])) == 1
    assert len(controls.get("failover_api_key", [])) == 1


# ── 2. The kernel's read side still accepts what an OLD store holds ────────

def test_legacy_slot_still_read_by_the_catalogue():
    """A store saved by the retired field must keep working, not go dark."""
    src = inspect.getsource(plm._qwen_key_from_store)
    assert "qwen_api_key" in src, (
        "_qwen_key_from_store must keep reading the legacy dedicated slot "
        "first, so an existing Qwen key never disappears from the panel."
    )


# ── 3. Qwen is selectable BEFORE its key exists (single-save setup) ────────

@pytest.fixture
def no_redis_catalog(monkeypatch):
    """No cache, no store, no env keys -- a fresh install's view of the world."""
    async def _none():
        return None
    monkeypatch.setattr(plm, "_redis", _none)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


@pytest.mark.asyncio
async def test_qwen_offered_without_any_key(monkeypatch, no_redis_catalog):
    """A provisioned deployment with NO qwen key still lists qwen; openai, with
    no env key, stays out. That asymmetry is the whole point: qwen's key is
    panel-entered, so the admin must be able to pick provider AND model in the
    same save that types the key in -- the only way qwen ever gets configured.
    (When NOTHING can be fetched the pre-existing total-failure path serves the
    entire static catalogue, which is a different, older guarantee.)
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ak-test")

    async def fake_anthropic(key):
        return ["claude-opus-4-6"]
    monkeypatch.setattr(plm, "_fetch_anthropic", fake_anthropic)

    async def no_key():
        return "", ""
    monkeypatch.setattr(plm, "_qwen_key_from_store", no_key)

    async def explode(*a, **kw):
        raise AssertionError("no live fetch may run without a key")
    monkeypatch.setattr(plm, "_fetch_openai", explode)
    monkeypatch.setattr(plm, "_fetch_qwen", explode)

    catalog = await plm.fetch_model_catalog()
    assert catalog["anthropic"] == ["claude-opus-4-6"]
    assert catalog["qwen"] == plm.FALLBACK_CATALOG["qwen"]
    assert "openai" not in catalog and "google" not in catalog


# ── 4. Saving must not leave a stale catalogue behind ─────────────────────

def test_save_drops_the_model_catalogue_cache():
    """A saved key must surface its provider's models on the NEXT render.

    The catalogue is derived from the keys in the store it reads, so caching
    it for an hour across a save would show the admin the old dropdowns.
    """
    src = inspect.getsource(handlers_llm)
    assert f'delete("{plm._CACHE_KEY}")' in src, (
        f"fn_save_llm_config must delete {plm._CACHE_KEY} after writing "
        "imperal:config:llm"
    )


# ── 5. The failover pair's provider follows its model ─────────────────────

def test_failover_provider_is_inferred_from_its_model():
    """Pick qwen-plus as the failover model while the default is openai and
    the stored failover_provider must become qwen -- otherwise the kernel
    pairs an openai provider with a qwen model and every failover 404s."""
    src = inspect.getsource(handlers_llm.fn_save_llm_config)
    assert '"failover",' in src, (
        '"failover" must be in the provider-inference loop tuple (the loop '
        "keys off f'{purpose}_model'/'{purpose}_provider', which is exactly "
        'the failover pair\'s flat key names)'
    )


def test_failover_pair_keys_survive_a_blank_model():
    """A blank failover model means 'no failover' -> the pair is cleared."""
    fields = SaveLlmConfigParams.model_fields
    for name in ("failover_model", "failover_provider", "failover_api_key",
                 "failover_enabled"):
        assert name in fields, f"{name} must stay writable from the panel"


def test_blank_failover_provider_stays_unselected():
    """An absent fallback must not render as an implicit OpenAI fallback."""
    controls = _controls(_form())
    failover = controls["failover_provider"]
    assert len(failover) == 1
    assert failover[0].get("value") == ""


def test_failover_base_url_remains_a_panel_writable_field():
    """The endpoint belongs to the fallback pair and must remain configurable."""
    assert "failover_base_url" in SaveLlmConfigParams.model_fields
    controls = _controls(_form())
    assert len(controls.get("failover_base_url", [])) == 1


def test_explicitly_blank_urls_remove_stale_endpoints():
    """URLs are routing configuration, unlike masked write-only API keys."""
    src = inspect.getsource(handlers_llm.fn_save_llm_config)
    assert 'for _url_key in ("base_url", "failover_base_url"):' in src
    assert "_url_key in params.model_fields_set" in src
    assert "current.pop(_url_key, None)" in src
