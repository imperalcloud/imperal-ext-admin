"""Dynamic LLM model catalogue — fetched live from the providers' APIs.

No hardcoded model list. The models offered in LLM Config come from the
providers' own `/v1/models` endpoints (keys from env), filtered to
chat-capable text models, cached in Redis (1h). A tiny static fallback is
used ONLY if every live + cache path fails, so the form never breaks.

Public API:
  - provider_for_model(model)        -> "anthropic" | "openai" | "qwen" | "google" | ""
  - async fetch_model_catalog()      -> {provider: [model_id, ...]}
  - catalog_to_options(catalog)      -> (all_models, provider_models)  # ui Select opts
  - FALLBACK_CATALOG                 -> resilience-only minimal catalogue
"""
from __future__ import annotations

import json
import logging
import os
import re

import httpx
from imperal_sdk._shared_http import shared_http

log = logging.getLogger("admin")

_CACHE_KEY = "imperal:config:llm:model_catalog"
_CACHE_TTL = 3600  # seconds (1h) — providers add models rarely
# A catalogue missing a configured provider must NOT be cached for the full
# hour: one transient network blip would erase that provider from the LLM
# Config dropdowns until the TTL expired. Degraded results get a short TTL so
# the next render retries the provider instead of serving a truncated form.
_CACHE_TTL_DEGRADED = 120  # seconds (2m)

# Provider inference by model-id prefix (rule-based, not an enumerated list).
_PROVIDER_PREFIXES: tuple[tuple[str, str], ...] = (
    ("claude", "anthropic"),
    ("qwen", "qwen"),
    ("gpt", "openai"),
    ("o1", "openai"),
    ("o3", "openai"),
    ("o4", "openai"),
    ("chatgpt", "openai"),
    ("gemini", "google"),
)

# OpenAI exposes 120+ models incl. non-chat families. Exclude by substring.
_OPENAI_EXCLUDE = (
    "transcribe", "tts", "audio", "image", "realtime", "search", "codex",
    "deep-research", "moderation", "embedding", "whisper", "diarize", "instruct",
)
# Dated snapshots (gpt-4.1-2025-04-14 / gpt-4-0613 / ...-20251001) — keep the
# stable alias, drop the pinned snapshot. Applied to OpenAI only (Anthropic ids
# are themselves canonical, e.g. claude-haiku-4-5-20251001).
_OPENAI_DATE_SUFFIX = re.compile(r"-(\d{4}-\d{2}-\d{2}|\d{8}|\d{4})$")

# Resilience-only fallback (used iff BOTH live fetch and cache fail).
FALLBACK_CATALOG: dict[str, list[str]] = {
    "anthropic": ["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
    "openai": ["gpt-5", "gpt-5-mini", "gpt-4.1", "gpt-4o", "gpt-4o-mini", "o3"],
    "qwen": ["qwen3-max", "qwen-max", "qwen-plus", "qwen-turbo"],
}

_QWEN_DEFAULT_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"


def provider_for_model(model: str) -> str:
    """Infer the provider from a model id by prefix. '' if unknown."""
    m = (model or "").lower()
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
        if _OPENAI_DATE_SUFFIX.search(i):
            continue
        out.add(i)
    return sorted(out)


def _filter_anthropic(ids: list[str]) -> list[str]:
    """All claude-* models are chat-capable."""
    return sorted({i for i in ids if i.startswith("claude-")})


# DashScope lists 160+ ids incl. vision/audio/embedding/rerank families.
_QWEN_EXCLUDE = (
    "vl", "audio", "tts", "asr", "ocr", "embedding", "rerank", "mt-",
    "image", "video", "wan", "math",
)


def _filter_qwen(ids: list[str]) -> list[str]:
    """Keep chat-capable qwen text models (incl. qwen3-coder, a chat model)."""
    out: set[str] = set()
    for i in ids:
        low = i.lower()
        if not low.startswith("qwen"):
            continue
        if any(tok in low for tok in _QWEN_EXCLUDE):
            continue
        out.add(i)
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


async def _fetch_qwen(key: str, base_url: str = "") -> list[str]:
    """DashScope OpenAI-compatible /models (key admin-entered via the panel)."""
    url = (base_url or _QWEN_DEFAULT_BASE_URL).rstrip("/") + "/models"
    async with shared_http(timeout=12.0) as c:
        r = await c.get(url, headers={"Authorization": f"Bearer {key}"})
        r.raise_for_status()
        return _filter_qwen([m.get("id", "") for m in r.json().get("data", [])])


async def _qwen_key_from_store() -> tuple[str, str]:
    """(key, base_url) for Qwen from the LLM Config Store, or ("", "").

    The Qwen key is entered in the PANEL (never env), so the catalogue
    reads it from Redis with the SAME precedence the kernel's
    config_from_store uses: a dedicated qwen_api_key slot first (legacy
    stores — the panel's separate Qwen field was retired 2026-08-28), then
    the shared api_key slot iff the configured provider IS qwen (the one
    API Key input now serves whichever provider is selected). Fernet-wrapped
    values are unwrapped with the same env keys the kernel uses; a missing
    crypto key degrades to "" (qwen simply has no LIVE models to list — the
    static backfill in fetch_model_catalog still offers it), never raises.
    """
    r = await _redis()
    if r is None:
        return "", ""
    try:
        raw = await r.get("imperal:config:llm") or "{}"
        cfg = json.loads(raw)
    except Exception:
        return "", ""
    finally:
        try:
            await r.aclose()
        except Exception:
            pass
    key = str(cfg.get("qwen_api_key") or "")
    if not key and cfg.get("provider") == "qwen":
        key = str(cfg.get("api_key") or "")
    if not key:
        return "", ""
    if key.startswith("gAAAAA"):  # Fernet-wrapped — mirror kernel llm/secrets.py
        try:
            from cryptography.fernet import Fernet
            fkey = os.getenv("IMPERAL_ENCRYPTION_KEY", "") or os.getenv("IMAP_ENCRYPTION_KEY", "")
            if fkey:
                key = Fernet(fkey.encode()).decrypt(key.encode()).decode()
        except Exception:
            return "", ""
    base = str(cfg.get("base_url") or "") if cfg.get("provider") == "qwen" else ""
    return key, base


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


async def fetch_model_catalog() -> dict[str, list[str]]:
    """Return {provider: [model_id, ...]}.  cache → live → static fallback."""
    r = await _redis()
    # 1. Cache hit
    if r is not None:
        try:
            cached = await r.get(_CACHE_KEY)
            if cached:
                await r.aclose()
                return json.loads(cached)
        except Exception as e:
            log.warning("model_catalog: cache read failed: %s", e)

    # 2. Live fetch per provider (each best-effort, isolated failure)
    catalog: dict[str, list[str]] = {}
    ak, ok = os.getenv("ANTHROPIC_API_KEY", ""), os.getenv("OPENAI_API_KEY", "")
    if ak:
        try:
            catalog["anthropic"] = await _fetch_anthropic(ak)
        except Exception as e:
            # Include the exception TYPE: httpx timeouts stringify to "", which
            # produced log lines with no cause at all ("fetch failed: ").
            log.warning(
                "model_catalog: anthropic fetch failed: %s: %s",
                type(e).__name__, e or "(no detail)",
            )
    if ok:
        try:
            catalog["openai"] = await _fetch_openai(ok)
        except Exception as e:
            log.warning(
                "model_catalog: openai fetch failed: %s: %s",
                type(e).__name__, e or "(no detail)",
            )
    # Qwen: key is PANEL-entered (lives in the LLM Config Store, not env).
    qk, qbase = await _qwen_key_from_store()
    if qk:
        try:
            catalog["qwen"] = await _fetch_qwen(qk, qbase)
        except Exception as e:
            log.warning(
                "model_catalog: qwen fetch failed: %s: %s",
                type(e).__name__, e or "(no detail)",
            )

    catalog = {p: m for p, m in catalog.items() if m}
    if not catalog:
        if r is not None:
            try:
                await r.aclose()
            except Exception:
                pass
        log.warning("model_catalog: all live fetches empty — using fallback")
        return {p: list(v) for p, v in FALLBACK_CATALOG.items()}

    # 2b. Partial failure: a provider IS configured (key present) but its fetch
    # failed or returned nothing. Without this, a single blip drops that whole
    # provider from the LLM Config dropdowns — the admin sees e.g. only
    # Anthropic and cannot pick a GPT model at all. Backfill from the static
    # fallback so every configured provider stays selectable, and mark the
    # result degraded so it is cached briefly instead of for an hour.
    expected = {p for p, key in (("anthropic", ak), ("openai", ok), ("qwen", qk)) if key}
    missing = sorted(expected - set(catalog))
    for prov in missing:
        fb = FALLBACK_CATALOG.get(prov)
        if fb:
            catalog[prov] = list(fb)
            log.warning(
                "model_catalog: %s unavailable — serving fallback list (%d models)",
                prov, len(fb),
            )

    # 2c. QWEN IS THE ONLY provider offered without a key. Its key is
    # PANEL-entered (the LLM Config Store, never env), so on a fresh install
    # the admin must be able to pick "Qwen (DashScope)" AND one of its models
    # in the SAME save that enters the key; refusing to list them made Qwen
    # unselectable until a second save -- the exact asymmetry the provider
    # select already avoids with its unconditional "qwen" entry here. The
    # static ids are the provider's own, and the kernel still refuses to build
    # a config with no key, so an early pick degrades safely instead of
    # mis-routing. fn_save_llm_config drops this cache on every save, so the
    # LIVE list replaces the static one as soon as the key exists.
    #
    # Env-keyed providers are deliberately NOT backfilled: no env key means
    # the deployment switched that provider off on purpose (federal
    # test_unconfigured_provider_is_not_backfilled).
    if "qwen" not in catalog:
        catalog["qwen"] = list(FALLBACK_CATALOG.get("qwen", []))

    # 3. Cache the live result (short TTL when degraded, so we retry soon)
    if r is not None:
        try:
            ttl = _CACHE_TTL_DEGRADED if missing else _CACHE_TTL
            await r.set(_CACHE_KEY, json.dumps(catalog), ex=ttl)
            await r.aclose()
        except Exception as e:
            log.warning("model_catalog: cache write failed: %s", e)
    return catalog


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
