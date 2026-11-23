"""The models an admin may pick - each provider's own list, read live.

The rule (owner, 2026-11-23: "Я хочу видеть все совместимые модели во всех
списках, где ключ доступен ... Но я НЕ хочу видеть модели, которые я не могу
использовать"):

  * a provider is listed only when its key is typed (llm_keys.py: this
    extension's secrets in Imperal Vault) and only from its OWN address;
  * every model of that list that can do the job is offered - no "top N", no
    favourite vendors, no hardcoded list;
  * a model that cannot do the job is not offered. The job of every slot in
    this extension is a chat call that may carry tools, so: text out, tools
    accepted, served on the chat endpoint. OpenRouter says all three per
    model. The other providers' /models answers carry ids only, so for them
    the non-chat families are dropped by the family's name;
  * a provider whose listing failed offers nothing and the page says why -
    there is no stand-in list of models that may not exist.

The answer is cached in Redis for an hour (two minutes when a provider failed).

Public API:
  - provider_for_model(model)         -> provider id, "" if unknown
  - async fetch_model_listing(ctx)    -> ({provider: [model_id, ...]}, {provider: why it is not listed})
  - async fetch_model_catalog(ctx)    -> the first half of the above
  - catalog_to_options(catalog)       -> (all_models, provider_models)  # ui.Select options
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re

import httpx
from imperal_sdk._shared_http import shared_http

log = logging.getLogger("admin")

_CACHE_KEY = "imperal:config:llm:model_listing"
_CACHE_TTL = 3600  # seconds (1h) — providers add models rarely
# A listing in which a keyed provider failed is kept only briefly, so the next
# render asks that provider again.
_CACHE_TTL_DEGRADED = 120  # seconds (2m)

# Provider inference by model-id prefix (rule-based, not an enumerated list).
_PROVIDER_PREFIXES: tuple[tuple[str, str], ...] = (
    ("claude", "anthropic"),
    ("qwen", "qwen"),
    ("qwq", "qwen"),
    # Kimi (Moonshot) and GLM (Zhipu z.ai) are FIRST-CLASS system providers
    # with their own keys and endpoints (2026-08-30). A kimi-* id resolves to
    # the Moonshot key, a glm-* id to the z.ai key — NEVER to the DashScope
    # key that merely re-hosts those families. One key = one vendor's models.
    ("kimi", "kimi"),
    ("moonshot", "kimi"),
    ("glm", "zhipu"),
    ("zhipu", "zhipu"),
    ("gpt", "openai"),
    ("o1", "openai"),
    ("o3", "openai"),
    ("o4", "openai"),
    ("sol", "openai"),
    ("fable", "openai"),
    ("chatgpt", "openai"),
    ("gemini", "google"),
    # OpenRouter multi-vendor router (model format vendor/model-id, e.g. z-ai/glm-5.3)
    ("openrouter", "openrouter"),
    ("z-ai/", "openrouter"),
    ("anthropic/", "openrouter"),
    ("openai/", "openrouter"),
    ("google/", "openrouter"),
    ("meta-llama/", "openrouter"),
    ("mistralai/", "openrouter"),
    ("deepseek/", "openrouter"),
    ("qwen/", "openrouter"),
)

# OpenAI exposes 120+ models incl. non-chat families. Exclude by substring.
_OPENAI_EXCLUDE = (
    "transcribe", "tts", "audio", "image", "realtime", "search", "codex",
    "deep-research", "moderation", "embedding", "whisper", "diarize", "instruct",
    "chat-latest",
)
# Dated snapshots (gpt-4.1-2025-04-14 / gpt-4-0613 / ...-20251001) — keep the
# stable alias, drop the pinned snapshot. Applied to OpenAI only (Anthropic ids
# are themselves canonical, e.g. claude-haiku-4-5-20251001).
_OPENAI_DATE_SUFFIX = re.compile(r"-(\d{4}-\d{2}-\d{2}|\d{8}|\d{4})$")

_OPENAI_EXPERIMENTAL_SUFFIXES = ("-luna", "-sol", "-terra", "-astra", "-live")

_QWEN_DEFAULT_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
# First-class provider endpoints (OpenAI-compatible). The kernel resolver
# (llm/provider.py) carries the SAME constants — one endpoint per vendor,
# catalogue and runtime calls hit it identically.
_KIMI_BASE_URL = "https://api.moonshot.ai/v1"
_ZHIPU_BASE_URL = "https://api.z.ai/api/paas/v4"
_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
# Same OpenAI-compatible surface the kernel resolver targets for provider
# "google" (llm/provider.py:_GOOGLE_BASE_URL) -- one source of truth for the
# endpoint shape, catalogue and runtime calls both hit it the same way.
_GOOGLE_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


def provider_for_model(model: str) -> str:
    """Infer the provider from a model id by prefix. '' if unknown."""
    m = (model or "").lower()
    if m.startswith("models/"):          # Google's own listing spells ids this way
        m = m[len("models/"):]
    # "vendor/model" is the OpenRouter id shape and is decided FIRST. The table
    # below was read top-down, so "qwen/qwen3.5-plus" met ("qwen", "qwen") and
    # "moonshotai/kimi-k3" met ("moonshot", "kimi") before any "vendor/" row:
    # an OpenRouter model was paired with the direct provider's key and
    # address. Vendors the table does not name (x-ai/, minimax/ ...) got no
    # provider at all. Found 2026-11-23.
    if "/" in m:
        return "openrouter"
    for prefix, prov in _PROVIDER_PREFIXES:
        if m.startswith(prefix):
            return prov
    return ""


def _filter_openai(ids: list[str]) -> list[str]:
    """Keep chat-capable text models; drop non-chat families + dated snapshots."""
    out: set[str] = set()
    for i in ids:
        if not (i.startswith("gpt-") or i.startswith(("o1", "o3", "o4"))):
            continue
        if any(tok in i for tok in _OPENAI_EXCLUDE):
            continue
        if any(i.endswith(suf) for suf in _OPENAI_EXPERIMENTAL_SUFFIXES):
            continue
        if _OPENAI_DATE_SUFFIX.search(i):
            continue
        out.add(i)
    # Sort prioritizing modern flagships (gpt-5, o3, o1, gpt-4o, gpt-4.1)
    priority = ["gpt-5", "o3", "o1", "gpt-4o", "gpt-4.1", "gpt-4"]

    def sort_key(m: str):
        for idx, pref in enumerate(priority):
            if m.startswith(pref):
                return (idx, m)
        return (len(priority), m)

    return sorted(out, key=sort_key)


def _filter_anthropic(ids: list[str]) -> list[str]:
    """All claude-* models are chat-capable; the newest families first."""
    out = {i for i in ids if i.startswith("claude-")}
    priority = ["claude-opus-5", "claude-sonnet-5", "claude-opus-4", "claude-sonnet-4", "claude-3-7-sonnet", "claude-haiku-4"]

    def sort_key(m: str):
        for idx, pref in enumerate(priority):
            if m.startswith(pref):
                return (idx, m)
        return (len(priority), m)

    return sorted(out, key=sort_key)


# DashScope lists 160+ ids incl. vision/audio/embedding/rerank families.
# Non-chat Qwen families (vision/audio/speech/translation/embedding/image-gen).
# Everything else the key can see IS offered — the catalogue is the provider's
# own /models answer, not a curated list.
_QWEN_EXCLUDE = (
    "vl", "audio", "tts", "asr", "ocr", "embedding", "rerank", "mt-",
    "image", "video", "wan", "math", "omni", "livetranslate", "s2s",
    "character", "captioner", "tingwu",
)
# Pinned snapshots (qwen-plus-2025-09-11, qwen3-max-2026-01-23, ...): dropped
# only when the undated alias is ALSO listed — a dated id with no alias is a
# distinct model and stays.
_QWEN_DATE_SUFFIX = re.compile(r"-\d{4}-\d{2}-\d{2}$")

# DashScope hosts ONLY the qwen family for us (2026-08-30): the admin's rule
# is one key = one vendor's models, so the deepseek/glm/kimi re-hosts that
# DashScope also lists behind the same key are deliberately NOT offered here —
# kimi-* and glm-* are first-class providers with their own keys now.
_QWEN_HOSTED_PREFIXES = ("qwen", "qwq")


def _filter_qwen(ids: list[str]) -> list[str]:
    """Keep chat-capable text models visible to this DashScope key.

    The provider's /models answer is the source of truth; we only drop
    non-chat families and redundant dated snapshots.
    """
    id_set = {i for i in ids if i}
    out: set[str] = set()
    for i in id_set:
        low = i.lower()
        # Vendor-namespaced ids ("ZHIPU/GLM-5.3", "kimi/kimi-k3") are NOT
        # qwen-family models: the namespace is another vendor re-hosted on
        # DashScope, and the admin's rule (2026-08-30) is one key = one
        # vendor's models. Those families are first-class providers with
        # their own keys now, so a slash id never enters the qwen list.
        if "/" in low:
            continue
        if not low.startswith(_QWEN_HOSTED_PREFIXES):
            continue
        if any(tok in low for tok in _QWEN_EXCLUDE):
            continue
        m = _QWEN_DATE_SUFFIX.search(low)
        if m and low[: m.start()] in {x.lower() for x in id_set}:
            continue
        out.add(i)
    return sorted(out)


# Google's OpenAI-compatible /models answer also lists embedding/imagen/veo/
# TTS ids alongside the gemini-* chat family.
_GOOGLE_EXCLUDE = (
    "embedding", "imagen", "veo", "tts", "aqa", "learnlm", "gemma",
)


def _filter_google(ids: list[str]) -> list[str]:
    """Keep chat-capable gemini-* models; drop embedding/image/video/audio ids."""
    out: set[str] = set()
    for i in ids:
        low = i.lower().removeprefix("models/")
        if not low.startswith("gemini"):
            continue
        if any(tok in low for tok in _GOOGLE_EXCLUDE):
            continue
        out.add(low)
    return sorted(out)


async def _fetch_anthropic(key: str) -> list[str]:
    async with shared_http(timeout=12.0) as c:
        r = await c.get(
            "https://api.anthropic.com/v1/models",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
        )
        r.raise_for_status()
        return _filter_anthropic([m.get("id", "") for m in r.json().get("data", [])])


async def _fetch_openai(key: str) -> list[str]:
    async with shared_http(timeout=12.0) as c:
        r = await c.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {key}"},
        )
        r.raise_for_status()
        return _filter_openai([m.get("id", "") for m in r.json().get("data", [])])


async def _fetch_qwen(key: str) -> list[str]:
    """DashScope OpenAI-compatible /models, at DashScope's own address."""
    url = _QWEN_DEFAULT_BASE_URL.rstrip("/") + "/models"
    async with shared_http(timeout=12.0) as c:
        r = await c.get(url, headers={"Authorization": f"Bearer {key}"})
        r.raise_for_status()
        return _filter_qwen([m.get("id", "") for m in r.json().get("data", [])])


async def _fetch_google(key: str) -> list[str]:
    """Google's OpenAI-compatible /models -- same endpoint shape as the
    kernel resolver targets for provider "google" (llm/provider.py:
    _GOOGLE_BASE_URL), so a live-fetched id is guaranteed to also resolve
    at runtime."""
    url = _GOOGLE_BASE_URL.rstrip("/") + "/models"
    async with shared_http(timeout=12.0) as c:
        r = await c.get(url, headers={"Authorization": f"Bearer {key}"})
        r.raise_for_status()
        return _filter_google([m.get("id", "") for m in r.json().get("data", [])])


async def _fetch_kimi(key: str) -> list[str]:
    """Moonshot (Kimi) OpenAI-compatible /models — the vendor's OWN endpoint,
    so every id it returns is by definition a kimi-family model this key can
    actually run. One key = one vendor's models (2026-08-30)."""
    url = _KIMI_BASE_URL.rstrip("/") + "/models"
    async with shared_http(timeout=12.0) as c:
        r = await c.get(url, headers={"Authorization": f"Bearer {key}"})
        r.raise_for_status()
        return _filter_kimi([m.get("id", "") for m in r.json().get("data", [])])


async def _fetch_zhipu(key: str) -> list[str]:
    """Zhipu (z.ai) OpenAI-compatible /models — the vendor's OWN endpoint, so
    every id it returns is by definition a glm-family model this key can
    actually run. One key = one vendor's models (2026-08-30)."""
    url = _ZHIPU_BASE_URL.rstrip("/") + "/models"
    async with shared_http(timeout=12.0) as c:
        r = await c.get(url, headers={"Authorization": f"Bearer {key}"})
        r.raise_for_status()
        return _filter_zhipu([m.get("id", "") for m in r.json().get("data", [])])


async def _fetch_openrouter(key: str) -> list[str]:
    """OpenRouter /models, read with the platform's key at OpenRouter's own address."""
    url = _OPENROUTER_BASE_URL.rstrip("/") + "/models"
    async with shared_http(timeout=12.0) as c:
        r = await c.get(url, headers={"Authorization": f"Bearer {key}"})
        r.raise_for_status()
        return _pick_openrouter(r.json().get("data", []))


# Measured on the public list 2026-11-23: 477 models. 19 of them answer with an
# image, audio or video; 50 of the text ones accept no tools; 92 are ":batch"
# variants served only on /api/v1/batches. 318 are left - all of them offered.
_CHAT_ENDPOINT = "chat/completions"


def openrouter_usable(m: dict) -> bool:
    """Whether an OpenRouter model can serve a slot of this extension: it
    answers with text only, accepts tools and is served on the chat endpoint.
    A field OpenRouter did not send is not held against the model."""
    arch = m.get("architecture") if isinstance(m.get("architecture"), dict) else {}
    out, params, endpoints = arch.get("output_modalities"), m.get("supported_parameters"), m.get("endpoints")
    if isinstance(out, list) and [str(x) for x in out] != ["text"]:
        return False
    if isinstance(params, list) and "tools" not in params:
        return False
    if isinstance(endpoints, list) and not any(_CHAT_ENDPOINT in str(e) for e in endpoints):
        return False
    return True


def _pick_openrouter(models: list[dict]) -> list[str]:
    """Every usable OpenRouter model: vendors in alphabetical order, the newest
    model of a vendor first."""
    usable = [m for m in models if isinstance(m, dict) and str(m.get("id") or "").strip() and openrouter_usable(m)]

    def order(m: dict):
        mid = str(m["id"]).strip()
        return (mid.lstrip("~").split("/", 1)[0].lower(), -(m.get("created") or 0), mid.lower())
    return list(dict.fromkeys(str(m["id"]).strip() for m in sorted(usable, key=order)))


def _filter_kimi(ids: list[str]) -> list[str]:
    """Keep kimi-* chat models; the vendor's endpoint only lists its own
    family, so this is a prefix guard, not a curation."""
    return sorted({i for i in ids if i.lower().startswith(("kimi", "moonshot"))})


def _filter_zhipu(ids: list[str]) -> list[str]:
    """Keep glm-* chat models; the vendor's endpoint only lists its own
    family, so this is a prefix guard, not a curation."""
    return sorted({i for i in ids if i.lower().startswith("glm")})


async def _redis():
    url = os.getenv("REDIS_URL", "")
    if not url:
        return None
    try:
        import redis.asyncio as aioredis
        return aioredis.from_url(url, decode_responses=True)
    except Exception as e:  # pragma: no cover - defensive
        log.warning("model_catalog: redis unavailable: %s", e)
        return None


# The providers that can be listed; each has a ``_fetch_<provider>(key)`` above.
LISTED = ("anthropic", "openai", "google", "openrouter", "qwen", "kimi", "zhipu")
STORE_NOTE = "*"        # the key of a note about the secret store itself


def _why(e: Exception) -> str:
    """One line a person can act on. httpx timeouts stringify to ""."""
    if isinstance(e, httpx.HTTPStatusError):
        code = e.response.status_code
        return f"the provider answered HTTP {code}" + (" - it does not accept the key" if code in (401, 403) else "")
    return f"{type(e).__name__}: {e}" if str(e) else type(e).__name__


async def fetch_model_listing(ctx=None, keyed: dict | None = None) -> tuple[dict[str, list[str]], dict[str, str]]:
    """(catalogue, notes): {provider: [model_id, ...]} for every provider that
    has a key and answered, and {provider: why} for a keyed provider that is
    not listed. ``keyed`` is llm_keys.keys_set(ctx) when the caller has it.

    Every provider is asked at its OWN address and at no other: a key never
    follows a Base URL saved in the config (security review 2026-11-23)."""
    from llm_keys import key_for, keys_set
    if keyed is None:
        keyed = await keys_set(ctx)
    if keyed is None:
        return {}, {STORE_NOTE: "the secret store did not answer, so no provider key could be read"}
    wanted = sorted(p for p in LISTED if keyed.get(p))
    if not wanted:
        return {}, {}

    cache_key = f"{_CACHE_KEY}:{'+'.join(wanted)}"       # a key typed or removed is a new listing
    r = await _redis()
    if r is not None:
        try:
            cached = await r.get(cache_key)
            if cached:
                got = json.loads(cached)
                await r.aclose()
                return got.get("catalog") or {}, got.get("notes") or {}
        except Exception as e:
            log.warning("model listing: cache read failed: %s", e)

    async def one(prov: str):
        try:
            key = await key_for(ctx, prov)
        except Exception as e:
            return prov, [], f"its key could not be read ({_why(e)})"
        if not key:
            return prov, [], "its key is empty"
        try:
            models = await globals()[f"_fetch_{prov}"](key)
        except Exception as e:
            log.warning("model listing: %s failed: %s", prov, _why(e))
            return prov, [], _why(e)
        return prov, models, "" if models else "the provider listed no model this page can use"

    catalog: dict[str, list[str]] = {}
    notes: dict[str, str] = {}
    for prov, models, why in await asyncio.gather(*[one(p) for p in wanted]):
        if models:
            catalog[prov] = models
        if why:
            notes[prov] = why

    if r is not None:
        try:
            await r.set(cache_key, json.dumps({"catalog": catalog, "notes": notes}),
                        ex=_CACHE_TTL_DEGRADED if notes else _CACHE_TTL)
            await r.aclose()
        except Exception as e:
            log.warning("model listing: cache write failed: %s", e)
    return catalog, notes


async def fetch_model_catalog(ctx=None, keyed: dict | None = None) -> dict[str, list[str]]:
    """{provider: [model_id, ...]} - see fetch_model_listing."""
    return (await fetch_model_listing(ctx, keyed))[0]


def catalog_to_options(catalog: dict[str, list[str]]) -> tuple[list[dict], list[dict]]:
    """Build ui.Select option lists from a catalogue.

    Returns (all_models, provider_models):
      - all_models    leads with a "— Same as default —" sentinel (per-purpose
                      overrides; empty value == inherit)
      - provider_models has no sentinel (default-provider + failover selects)
    """
    all_models: list[dict] = [{"value": "", "label": "— Same as default —"}]
    provider_models: list[dict] = []
    for prov in sorted(catalog or {}):
        for m in catalog[prov]:
            opt = {"value": m, "label": f"{m} ({prov})"}
            all_models.append(dict(opt))
            provider_models.append(dict(opt))
    return all_models, provider_models
