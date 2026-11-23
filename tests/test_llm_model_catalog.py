"""Tests for the live LLM model catalogue (panels_llm_models).

The rule since 2026-11-23 (owner): every usable model of every provider that
has a key, and nothing else - no top-N cut, no built-in stand-in list. A
provider that failed offers nothing, the page says why, and that answer is
cached only briefly (the older incident: one failed OpenAI fetch was cached
for an hour).
"""
from __future__ import annotations

import json

import pytest

import panels_llm_models as plm


class _FakeRedis:
    """Minimal async stub of the redis client surface used by the module."""

    def __init__(self, initial: str | None = None):
        self.store: dict[str, str] = {}
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


class _Secrets:
    def __init__(self, values):
        self.values = dict(values)

    async def get(self, name):
        return self.values.get(name)

    async def is_set(self, name):
        return bool(self.values.get(name))


class _Ctx:
    """A ctx whose secrets hold the given provider keys. They are the ONLY
    source of a key: never the environment, never the config store."""

    def __init__(self, anthropic="ak-test", openai="ok-test", **more):
        keys = {"anthropic": anthropic, "openai": openai, **more}
        self.secrets = _Secrets({f"llm_{p}_api_key": k for p, k in keys.items() if k})


def _stub_fetches(monkeypatch, **by_provider):
    """Every provider's fetch: a list answers, an exception raises, and a
    provider not named here must not be asked at all."""
    for prov in plm.LISTED:
        answer = by_provider.get(prov, AssertionError(f"{prov} has no key and must not be asked"))

        async def fake(key, _answer=answer, _prov=prov):
            if isinstance(_answer, Exception):
                raise _answer
            assert key == by_provider.get(f"{_prov}_key", key)
            return list(_answer)
        monkeypatch.setattr(plm, f"_fetch_{prov}", fake)


def _with_redis(monkeypatch, fake):
    async def _fake_redis():
        return fake
    monkeypatch.setattr(plm, "_redis", _fake_redis)


# ------------------------------------------------- a provider that fails

@pytest.mark.asyncio
async def test_a_failed_provider_offers_nothing_and_says_why(monkeypatch, no_redis):
    """Owner 2026-11-23: no model in a list that cannot be used. A provider
    that did not answer has no stand-in list; the page gets the reason."""
    _stub_fetches(monkeypatch, anthropic=["claude-opus-4-6", "claude-sonnet-4-6"], openai=TimeoutError())

    catalog, notes = await plm.fetch_model_listing(_Ctx())

    assert catalog == {"anthropic": ["claude-opus-4-6", "claude-sonnet-4-6"]}
    assert list(notes) == ["openai"] and "TimeoutError" in notes["openai"]


@pytest.mark.asyncio
async def test_a_rejected_key_is_named_as_such(monkeypatch, no_redis):
    import httpx
    req = httpx.Request("GET", "https://api.openai.com/v1/models")
    rejected = httpx.HTTPStatusError("401", request=req, response=httpx.Response(401, request=req))
    _stub_fetches(monkeypatch, anthropic=["claude-opus-4-6"], openai=rejected)

    catalog, notes = await plm.fetch_model_listing(_Ctx())

    assert "openai" not in catalog
    assert notes["openai"] == "the provider answered HTTP 401 - it does not accept the key"


@pytest.mark.asyncio
async def test_every_provider_failing_leaves_no_models(monkeypatch, no_redis):
    _stub_fetches(monkeypatch, anthropic=RuntimeError("boom"), openai=RuntimeError("boom"))

    catalog, notes = await plm.fetch_model_listing(_Ctx())

    assert catalog == {} and sorted(notes) == ["anthropic", "openai"]
    assert not hasattr(plm, "FALLBACK_CATALOG"), "there is no built-in list of models"


@pytest.mark.asyncio
async def test_a_failed_listing_is_cached_only_briefly(monkeypatch):
    fake = _FakeRedis()
    _with_redis(monkeypatch, fake)
    _stub_fetches(monkeypatch, anthropic=["claude-opus-4-6"], openai=TimeoutError())

    await plm.fetch_model_listing(_Ctx())

    key, _, ttl = fake.set_calls[-1]
    assert key == f"{plm._CACHE_KEY}:anthropic+openai"
    assert ttl == plm._CACHE_TTL_DEGRADED < plm._CACHE_TTL


@pytest.mark.asyncio
async def test_a_whole_listing_keeps_the_full_ttl(monkeypatch):
    fake = _FakeRedis()
    _with_redis(monkeypatch, fake)
    _stub_fetches(monkeypatch, anthropic=["claude-opus-4-6"], openai=["gpt-5"])

    await plm.fetch_model_listing(_Ctx())

    assert fake.set_calls[-1][2] == plm._CACHE_TTL


# ------------------------------------------------- only where a key is

@pytest.mark.asyncio
async def test_a_provider_without_a_key_is_neither_asked_nor_listed(monkeypatch, no_redis):
    """Every provider alike: qwen, kimi, zhipu and openrouter used to be
    offered from a built-in list before their key existed."""
    monkeypatch.setenv("GOOGLE_API_KEY", "goog-from-env")        # not a source of keys
    _stub_fetches(monkeypatch, anthropic=["claude-opus-4-6"])

    catalog, notes = await plm.fetch_model_listing(_Ctx(openai=None))

    assert catalog == {"anthropic": ["claude-opus-4-6"]} and notes == {}


@pytest.mark.asyncio
async def test_no_key_at_all_is_an_empty_listing(monkeypatch, no_redis):
    _stub_fetches(monkeypatch)
    assert await plm.fetch_model_listing(_Ctx(anthropic=None, openai=None)) == ({}, {})


@pytest.mark.asyncio
async def test_each_provider_is_asked_with_its_own_secret(monkeypatch, no_redis):
    _stub_fetches(monkeypatch, qwen=["qwen3-max"], google=["gemini-3-pro"], openrouter=["a/b"],
                  qwen_key="sk-qw", google_key="goog", openrouter_key="sk-or")
    ctx = _Ctx(anthropic=None, openai=None, qwen="sk-qw", google="goog", openrouter="sk-or")

    assert await plm.fetch_model_catalog(ctx) == {
        "qwen": ["qwen3-max"], "google": ["gemini-3-pro"], "openrouter": ["a/b"]}


@pytest.mark.asyncio
async def test_a_store_that_does_not_answer_is_said_so(monkeypatch, no_redis):
    class _Away:
        async def get(self, name):
            raise RuntimeError("store away")
        is_set = get
    ctx = _Ctx()
    ctx.secrets = _Away()
    _stub_fetches(monkeypatch)

    catalog, notes = await plm.fetch_model_listing(ctx)

    assert catalog == {} and list(notes) == [plm.STORE_NOTE]


# ------------------------------------------------- the cache

@pytest.mark.asyncio
async def test_cache_hit_short_circuits(monkeypatch):
    fake = _FakeRedis()
    fake.store[f"{plm._CACHE_KEY}:anthropic+openai"] = json.dumps(
        {"catalog": {"anthropic": ["claude-x"], "openai": ["gpt-x"]}, "notes": {}})
    _with_redis(monkeypatch, fake)
    _stub_fetches(monkeypatch)                                   # any live fetch fails the test

    assert await plm.fetch_model_catalog(_Ctx()) == {"anthropic": ["claude-x"], "openai": ["gpt-x"]}


@pytest.mark.asyncio
async def test_a_key_typed_or_removed_is_a_new_listing(monkeypatch):
    """The cached answer belongs to the set of providers that had a key: a new
    key shows its models on the next render, not an hour later."""
    fake = _FakeRedis()
    fake.store[f"{plm._CACHE_KEY}:anthropic+openai"] = json.dumps(
        {"catalog": {"anthropic": ["claude-x"], "openai": ["gpt-x"]}, "notes": {}})
    _with_redis(monkeypatch, fake)
    _stub_fetches(monkeypatch, anthropic=["claude-y"], openai=["gpt-y"], kimi=["kimi-k3"])

    catalog = await plm.fetch_model_catalog(_Ctx(kimi="sk-kimi"))

    assert catalog["kimi"] == ["kimi-k3"] and catalog["openai"] == ["gpt-y"]


# ------------------------------------------------- nothing is cut

def test_no_provider_list_is_cut_to_a_top_n():
    """Until 2026-11-23: 16 OpenAI, 10 Anthropic and 20 Qwen models at most."""
    assert len(plm._filter_openai([f"gpt-5.{i}" for i in range(40)])) == 40
    assert len(plm._filter_anthropic([f"claude-opus-5-{i}" for i in range(30)])) == 30
    assert len(plm._filter_qwen([f"qwen-new-{i}" for i in range(50)])) == 50


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
    assert plm.provider_for_model("qwen3-max") == "qwen"
    assert plm.provider_for_model("qwen-plus") == "qwen"
    # Kimi (Moonshot) and GLM (Zhipu z.ai) are FIRST-CLASS providers with
    # their own keys (2026-08-30) — one key = one vendor's models, so a
    # kimi-* id resolves to the Moonshot key and a glm-* id to the z.ai key,
    # NEVER to the DashScope key that merely re-hosts those families.
    assert plm.provider_for_model("kimi-k3") == "kimi"
    assert plm.provider_for_model("kimi-k2.7-code") == "kimi"
    assert plm.provider_for_model("glm-5.3") == "zhipu"
    assert plm.provider_for_model("glm-4.5-air") == "zhipu"
    # deepseek has no first-class provider slot — it is not offered anywhere.
    assert plm.provider_for_model("deepseek-v4-pro") == ""
    assert plm.provider_for_model("mystery-model") == ""


# ------------------------------------------------------------- qwen (DashScope)

def test_qwen_filter_keeps_chat_models_only():
    ids = [
        "qwen3-max", "qwen-max", "qwen-plus", "qwen-turbo",
        "qwen3-coder-plus", "qwen-vl-max", "qwen-audio-turbo",
        "text-embedding-v3", "gte-rerank", "wan2.1-t2v-turbo",
        "qwen2.5-math-72b-instruct",
    ]
    kept = plm._filter_qwen(ids)
    assert "qwen3-max" in kept and "qwen-plus" in kept
    assert "qwen3-coder-plus" in kept  # chat model, NOT excluded
    assert "qwen-vl-max" not in kept
    assert "qwen-audio-turbo" not in kept
    assert "text-embedding-v3" not in kept
    assert "wan2.1-t2v-turbo" not in kept


def test_qwen_filter_keeps_only_qwen_family():
    """One key = one vendor's models (2026-08-30): the DashScope key offers
    ONLY the qwen/qwq family. deepseek/glm/kimi are first-class providers
    with their own keys now, and vendor-NAMESPACED ids (ZHIPU/GLM-5.3,
    kimi/kimi-k3) are another vendor re-hosted on DashScope — never offered
    under the qwen key."""
    ids = [
        "deepseek-v4-pro", "deepseek-v4-flash", "glm-5.2", "glm-5.1",
        "kimi-k3", "kimi-k2.7-code", "qwen3-max", "qwq-plus",
        "ccai-pro", "ZHIPU/GLM-5.3", "kimi/kimi-k3",
    ]
    kept = plm._filter_qwen(ids)
    assert kept == ["qwen3-max", "qwq-plus"]


def test_qwen_filter_still_drops_unknown_namespaces_and_nonchat():
    """A namespace we don't host through this key stays out, and a namespaced
    non-chat family is still excluded after the namespace is stripped."""
    ids = ["META/llama-3-70b", "ZHIPU/GLM-audio-tts", "qwen3-max"]
    kept = plm._filter_qwen(ids)
    assert kept == ["qwen3-max"]


def test_qwen_filter_drops_dated_snapshot_only_when_alias_exists():
    ids = [
        "qwen-plus", "qwen-plus-2025-09-11",   # alias exists -> snapshot dropped
        "qwen3-max-2026-01-23",                 # no alias -> snapshot KEPT
    ]
    kept = plm._filter_qwen(ids)
    assert "qwen-plus" in kept
    assert "qwen-plus-2025-09-11" not in kept
    assert "qwen3-max-2026-01-23" in kept


def test_kimi_and_zhipu_filters_keep_only_their_own_family():
    """Each first-class provider's filter is a prefix guard on the vendor's
    OWN /models answer — one key = one vendor's models (2026-08-30)."""
    kimi_ids = ["kimi-k3", "kimi-k2.7-code", "kimi-k2.7-code-highspeed", "kimi-k2.6", "glm-5.3", "qwen3-max"]
    assert plm._filter_kimi(kimi_ids) == ["kimi-k2.6", "kimi-k2.7-code", "kimi-k2.7-code-highspeed", "kimi-k3"]
    zhipu_ids = ["glm-5.3", "glm-5.3-flash", "glm-4.5", "glm-4.5-air", "kimi-k3", "qwen3-max"]
    assert plm._filter_zhipu(zhipu_ids) == ["glm-4.5", "glm-4.5-air", "glm-5.3", "glm-5.3-flash"]


# ------------------------------------------------------------------- google

def test_google_filter_keeps_chat_gemini_only():
    ids = [
        "models/gemini-3-pro", "models/gemini-3-flash", "gemini-2.5-flash",
        "gemini-embedding-001", "imagen-4.0-generate", "veo-3.0-generate",
        "gemini-2.5-flash-tts", "aqa", "learnlm-2.0-flash", "gemma-3-27b-it",
    ]
    kept = plm._filter_google(ids)
    assert "gemini-3-pro" in kept
    assert "gemini-3-flash" in kept
    assert "gemini-2.5-flash" in kept
    assert "gemini-embedding-001" not in kept
    assert "imagen-4.0-generate" not in kept
    assert "veo-3.0-generate" not in kept
    assert "gemini-2.5-flash-tts" not in kept
    assert "aqa" not in kept
    assert "learnlm-2.0-flash" not in kept
    assert "gemma-3-27b-it" not in kept


def test_google_filter_strips_models_prefix():
    """Google's API returns ids as 'models/gemini-x' -- the prefix must not leak."""
    kept = plm._filter_google(["models/gemini-2.5-pro"])
    assert kept == ["gemini-2.5-pro"]
