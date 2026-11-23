"""LLM provider keys are secrets of this extension, kept in Imperal Vault.

Owner, 2026-11-23: "Все ключи строго из него должны доставаться, никакого
редиса". Until that day the keys were fields of the LLM Config page, stored in
the Redis config row, and three providers were keyed from the environment.
"""
from __future__ import annotations

import asyncio
import pathlib

import llm_keys
import panels_llm as PL
import panels_llm_models as plm
from app import ext
from panels_llm_form import _key_status

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _plain(node):
    if hasattr(node, "to_dict"):
        return node.to_dict()
    return node


def _texts(node, out=None):
    out = [] if out is None else out
    node = _plain(node)
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, str) and k in ("content", "text", "label", "title", "message", "path"):
                out.append(v)
            else:
                _texts(v, out)
    elif isinstance(node, (list, tuple)):
        for v in node:
            _texts(v, out)
    return out


class _Secrets:
    def __init__(self, values=None, fail=False):
        self.values, self.fail = dict(values or {}), fail

    async def get(self, name):
        if self.fail:
            raise RuntimeError("store away")
        return self.values.get(name)

    async def is_set(self, name):
        if self.fail:
            raise RuntimeError("store away")
        return name in self.values


class _Ctx:
    def __init__(self, values=None, fail=False):
        self.secrets = _Secrets(values, fail)


def test_every_provider_key_is_a_declared_app_secret():
    declared = ext.secrets
    assert len(llm_keys.PROVIDERS) == 8
    for prov in llm_keys.PROVIDERS:
        name = llm_keys.secret_name(prov)
        assert name == f"llm_{prov}_api_key" and name in declared, name
        spec = declared[name]
        assert getattr(spec, "scope", None) == "app"
    assert llm_keys.secret_name("custom") == "llm_openai_compatible_api_key"
    assert llm_keys.secrets_path("openrouter") == "/ext/admin/secrets#llm_openrouter_api_key"


def test_key_reads_go_through_ctx_secrets():
    ctx = _Ctx({"llm_kimi_api_key": "k"})
    assert asyncio.run(llm_keys.key_for(ctx, "kimi")) == "k"
    assert asyncio.run(llm_keys.key_for(ctx, "openai")) == ""
    assert asyncio.run(llm_keys.key_for(ctx, "nobody")) == ""
    assert asyncio.run(llm_keys.key_for(object(), "kimi")) == "", "a ctx without secrets has no key"
    has = asyncio.run(llm_keys.keys_set(ctx))
    assert has["kimi"] is True and has["openai"] is False and len(has) == 8
    assert asyncio.run(llm_keys.keys_set(_Ctx(fail=True))) is None, "unknown is not 'not set'"


def test_the_form_says_where_the_key_is_and_links_to_secrets():
    text = " | ".join(_texts(_key_status("openrouter", {"openrouter": True})))
    assert "API key of OpenRouter: set." in text and "llm_openrouter_api_key" in text
    assert "/ext/admin/secrets#llm_openrouter_api_key" in text and "Change the key" in text
    text = " | ".join(_texts(_key_status("kimi", {"kimi": False})))
    assert "NOT SET" in text and "Set the key" in text
    assert "unknown" in " | ".join(_texts(_key_status("kimi", None)))
    assert _key_status("", {}) == []


def test_the_keys_view_lists_every_provider():
    text = " | ".join(_texts(PL._build_keys_view({"openrouter": True})))
    for label in llm_keys.PROVIDERS.values():
        assert label in text
    assert "OpenRouter  ·  set" in text and "Kimi  ·  NOT SET" in text
    unknown = " | ".join(_texts(PL._build_keys_view(None)))
    assert "Key status unknown" in unknown and "NOT SET" not in unknown
    assert ("provider-keys", "Provider keys") in PL.EXTRA_VIEWS


def test_the_catalogue_takes_its_keys_from_the_secrets(monkeypatch):
    async def _none():
        return None
    monkeypatch.setattr(plm, "_redis", _none)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    seen = {}

    async def _openrouter(key, base_url=""):
        seen["openrouter"] = key
        return ["a/b"]

    async def _explode(*a, **kw):
        raise AssertionError("a provider without a secret is not fetched")
    monkeypatch.setattr(plm, "_fetch_openrouter", _openrouter)
    for name in ("_fetch_openai", "_fetch_anthropic", "_fetch_google", "_fetch_qwen", "_fetch_kimi", "_fetch_zhipu"):
        monkeypatch.setattr(plm, name, _explode)
    catalog = asyncio.run(plm.fetch_model_catalog(_Ctx({"llm_openrouter_api_key": "k-or"})))
    assert seen == {"openrouter": "k-or"} and catalog["openrouter"] == ["a/b"]
    assert "openai" not in catalog


def test_a_store_failure_leaves_the_catalogue_on_its_fallback(monkeypatch):
    async def _none():
        return None
    monkeypatch.setattr(plm, "_redis", _none)
    catalog = asyncio.run(plm.fetch_model_catalog(_Ctx(fail=True)))
    assert catalog == {p: list(v) for p, v in plm.FALLBACK_CATALOG.items()}


def test_no_extension_code_reads_an_llm_key_from_env_or_the_config_store():
    bad = []
    for path in sorted(ROOT.glob("*.py")):
        src = path.read_text(encoding="utf-8")
        for needle in ('getenv("ANTHROPIC_API_KEY"', 'getenv("OPENAI_API_KEY"', 'getenv("GOOGLE_API_KEY"',
                       'getenv("GEMINI_API_KEY"', 'get("api_key")', 'get("failover_api_key")',
                       'get("qwen_api_key")', 'param_name="api_key"', 'param_name="failover_api_key"'):
            if needle in src:
                bad.append(f"{path.name}: {needle}")
    assert not bad, bad


def test_a_key_never_follows_a_saved_base_url_in_the_catalogue(monkeypatch):
    """Every fetcher that takes a key is called for the provider's own address:
    the catalogue takes no address from the config (security review 2026-11-23)."""
    import inspect
    assert list(inspect.signature(plm.fetch_model_catalog).parameters) == ["ctx"]

    async def _none():
        return None
    monkeypatch.setattr(plm, "_redis", _none)
    seen = []

    async def _qwen(key, base_url=""):
        seen.append(("qwen", base_url))
        return ["qwen3-max"]

    async def _openrouter(key, base_url=""):
        seen.append(("openrouter", base_url))
        return ["a/b"]
    monkeypatch.setattr(plm, "_fetch_qwen", _qwen)
    monkeypatch.setattr(plm, "_fetch_openrouter", _openrouter)
    asyncio.run(plm.fetch_model_catalog(_Ctx({"llm_qwen_api_key": "kq", "llm_openrouter_api_key": "ko"})))
    assert sorted(seen) == [("openrouter", ""), ("qwen", "")]
