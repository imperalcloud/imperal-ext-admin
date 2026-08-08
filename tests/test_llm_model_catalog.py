"""Tests for the live LLM model catalogue (panels_llm_models).

Regression cover for the incident where LLM Config showed ONLY Anthropic
models: a single transient OpenAI fetch failure produced a partial catalogue
that was then cached for a full hour, so GPT models silently vanished from
every model dropdown until the TTL expired.
"""
from __future__ import annotations

import json

import pytest

import panels_llm_models as plm


class _FakeRedis:
    """Minimal async stub of the redis client surface used by the module."""

    def __init__(self, initial: str | None = None):
        self.store: dict[str, str] = {}
        if initial is not None:
            self.store[plm._CACHE_KEY] = initial
        self.set_calls: list[tuple[str, str, int]] = []
        self.closed = False

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value
        self.set_calls.append((key, value, ex))

    async def aclose(self):
        self.closed = True


@pytest.fixture
def no_redis(monkeypatch):
    async def _none():
        return None
    monkeypatch.setattr(plm, "_redis", _none)


def _set_keys(monkeypatch, *, anthropic="ak-test", openai="ok-test"):
    monkeypatch.setenv("ANTHROPIC_API_KEY", anthropic or "")
    monkeypatch.setenv("OPENAI_API_KEY", openai or "")
    if not anthropic:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    if not openai:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def _stub_fetches(monkeypatch, *, anthropic=None, openai=None):
    async def fake_anthropic(key):
        if isinstance(anthropic, Exception):
            raise anthropic
        return list(anthropic or [])

    async def fake_openai(key):
        if isinstance(openai, Exception):
            raise openai
        return list(openai or [])

    monkeypatch.setattr(plm, "_fetch_anthropic", fake_anthropic)
    monkeypatch.setattr(plm, "_fetch_openai", fake_openai)


# --------------------------------------------------------------- the incident

@pytest.mark.asyncio
async def test_openai_failure_keeps_openai_selectable(monkeypatch, no_redis):
    """THE BUG: anthropic ok + openai down must NOT erase openai."""
    _set_keys(monkeypatch)
    _stub_fetches(
        monkeypatch,
        anthropic=["claude-opus-4-6", "claude-sonnet-4-6"],
        openai=TimeoutError(),
    )

    catalog = await plm.fetch_model_catalog()

    assert "openai" in catalog, "openai vanished from the catalogue"
    assert catalog["openai"], "openai present but empty"
    assert catalog["anthropic"] == ["claude-opus-4-6", "claude-sonnet-4-6"]


@pytest.mark.asyncio
async def test_anthropic_failure_keeps_anthropic_selectable(monkeypatch, no_redis):
    """Symmetric case — the same protection must work the other way round."""
    _set_keys(monkeypatch)
    _stub_fetches(monkeypatch, anthropic=RuntimeError("boom"), openai=["gpt-5"])

    catalog = await plm.fetch_model_catalog()

    assert catalog["openai"] == ["gpt-5"]
    assert catalog["anthropic"] == plm.FALLBACK_CATALOG["anthropic"]


@pytest.mark.asyncio
async def test_degraded_catalogue_is_cached_only_briefly(monkeypatch):
    """A partial result must not be pinned for the full hour."""
    fake = _FakeRedis()

    async def _fake_redis():
        return fake
    monkeypatch.setattr(plm, "_redis", _fake_redis)
    _set_keys(monkeypatch)
    _stub_fetches(monkeypatch, anthropic=["claude-opus-4-6"], openai=TimeoutError())

    await plm.fetch_model_catalog()

    assert fake.set_calls, "nothing was cached"
    _, _, ttl = fake.set_calls[-1]
    assert ttl == plm._CACHE_TTL_DEGRADED
    assert ttl < plm._CACHE_TTL


@pytest.mark.asyncio
async def test_healthy_catalogue_keeps_full_ttl(monkeypatch):
    fake = _FakeRedis()

    async def _fake_redis():
        return fake
    monkeypatch.setattr(plm, "_redis", _fake_redis)
    _set_keys(monkeypatch)
    _stub_fetches(monkeypatch, anthropic=["claude-opus-4-6"], openai=["gpt-5"])

    await plm.fetch_model_catalog()

    _, _, ttl = fake.set_calls[-1]
    assert ttl == plm._CACHE_TTL


@pytest.mark.asyncio
async def test_unconfigured_provider_is_not_backfilled(monkeypatch, no_redis):
    """No key => provider is deliberately off; do not invent models for it."""
    _set_keys(monkeypatch, openai=None)
    _stub_fetches(monkeypatch, anthropic=["claude-opus-4-6"])

    catalog = await plm.fetch_model_catalog()

    assert "openai" not in catalog
    assert catalog["anthropic"] == ["claude-opus-4-6"]


@pytest.mark.asyncio
async def test_total_failure_falls_back_to_both_providers(monkeypatch, no_redis):
    _set_keys(monkeypatch)
    _stub_fetches(monkeypatch, anthropic=RuntimeError(), openai=RuntimeError())

    catalog = await plm.fetch_model_catalog()

    assert set(catalog) == set(plm.FALLBACK_CATALOG)


@pytest.mark.asyncio
async def test_cache_hit_short_circuits(monkeypatch):
    cached = json.dumps({"anthropic": ["claude-x"], "openai": ["gpt-x"]})
    fake = _FakeRedis(initial=cached)

    async def _fake_redis():
        return fake
    monkeypatch.setattr(plm, "_redis", _fake_redis)

    async def explode(key):
        raise AssertionError("live fetch must not run on a cache hit")
    monkeypatch.setattr(plm, "_fetch_anthropic", explode)
    monkeypatch.setattr(plm, "_fetch_openai", explode)

    catalog = await plm.fetch_model_catalog()
    assert catalog == {"anthropic": ["claude-x"], "openai": ["gpt-x"]}


# ------------------------------------------------------------- option lists

def test_catalog_to_options_marks_provider_and_inherit_sentinel():
    all_models, provider_models = plm.catalog_to_options(
        {"anthropic": ["claude-opus-4-6"], "openai": ["gpt-5"]}
    )

    assert all_models[0] == {"value": "", "label": "— Same as default —"}
    labels = [o["label"] for o in provider_models]
    assert "gpt-5 (openai)" in labels
    assert "claude-opus-4-6 (anthropic)" in labels
    assert all(o["value"] for o in provider_models)


def test_openai_models_survive_the_chat_filter():
    """The filter must not be what removes GPT models."""
    ids = [
        "gpt-5", "gpt-4o", "gpt-4o-mini", "o3", "o4-mini",
        "gpt-4o-realtime-preview", "text-embedding-3-large",
        "whisper-1", "gpt-4.1-2025-04-14", "dall-e-3",
    ]
    kept = plm._filter_openai(ids)

    assert "gpt-5" in kept and "gpt-4o" in kept and "o3" in kept
    assert "whisper-1" not in kept
    assert "text-embedding-3-large" not in kept
    assert "gpt-4o-realtime-preview" not in kept
    assert "gpt-4.1-2025-04-14" not in kept


def test_provider_inference_covers_openai_families():
    assert plm.provider_for_model("gpt-5") == "openai"
    assert plm.provider_for_model("o3-mini") == "openai"
    assert plm.provider_for_model("claude-opus-4-6") == "anthropic"
    assert plm.provider_for_model("gemini-2.0") == "google"
    assert plm.provider_for_model("mystery-model") == ""
