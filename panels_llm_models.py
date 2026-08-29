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
    "qwen": ["qwen3-max", "qwen3-coder-plus", "qwen-max", "qwen-plus", "qwen-turbo", "qwen-flash"],
    # Provider dropdown has always offered "google" (_env_providers in
    # panels_llm.py, gated on GOOGLE_API_KEY/GEMINI_API_KEY) and the kernel
    # fully resolves it (llm/provider.py _GOOGLE_BASE_URL + param-support
    # set) -- but the catalogue had no fetcher and no fallback list, so
    # picking Google always left the Model Select empty. Static ids here are
    # the provider's own; _fetch_google below replaces this with the live
    # list as soon as a key is configured.
    "google": ["gemini-3-pro", "gemini-3-flash", "gemini-2.5-pro", "gemini-2.5-flash"],
    # Kimi (Moonshot) and GLM (Zhipu z.ai) — first-class system providers
    # (2026-08-30). Static ids are each vendor's own; the live fetchers below
    # replace them with the key's real /models answer as soon as a key exists.
    "kimi": ["kimi-k3", "kimi-k2.7-code", "kimi-k2.7-code-highspeed", "kimi-k2.6"],
    "zhipu": ["glm-5.3", "glm-5.3-flash", "glm-5.2", "glm-5.1", "glm-5", "glm-4.7", "glm-4.6", "glm-4.5", "glm-4.5-air"],
}

_QWEN_DEFAULT_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
# First-class provider endpoints (OpenAI-compatible). The kernel resolver
# (llm/provider.py) carries the SAME constants — one endpoint per vendor,
# catalogue and runtime calls hit it identically.
_KIMI_BASE_URL = "https://api.moonshot.ai/v1"
_ZHIPU_BASE_URL = "https://api.z.ai/api/paas/v4"
# Same OpenAI-compatible surface the kernel resolver targets for provider
# "google" (llm/provider.py:_GOOGLE_BASE_URL) -- one source of truth for the
# endpoint shape, catalogue and runtime calls both hit it the same way.
_GOOGLE_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


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


async def _fetch_qwen(key: str, base_url: str = "") -> list[str]:
    """DashScope OpenAI-compatible /models (key admin-entered via the panel)."""
    url = (base_url or _QWEN_DEFAULT_BASE_URL).rstrip("/") + "/models"
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


def _filter_kimi(ids: list[str]) -> list[str]:
    """Keep kimi-* chat models; the vendor's endpoint only lists its own
    family, so this is a prefix guard, not a curation."""
    return sorted({i for i in ids if i.lower().startswith(("kimi", "moonshot"))})


def _filter_zhipu(ids: list[str]) -> list[str]:
    """Keep glm-* chat models; the vendor's endpoint only lists its own
    family, so this is a prefix guard, not a curation."""
    return sorted({i for i in ids if i.lower().startswith("glm")})


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


async def _store_key_for(provider: str) -> str:
    """The panel-entered key for a first-class provider, or "".

    kimi/zhipu keys are entered in the PANEL (never env), exactly like qwen's.
    Precedence mirrors the kernel's config_from_store: the dedicated
    ``{provider}_api_key`` slot first, then the shared ``api_key`` slot iff
    the configured provider IS this one (the one API Key input serves
    whichever provider is selected). Fernet-wrapped values are unwrapped with
    the same env keys the kernel uses; a missing crypto key degrades to ""
    (the provider simply has no LIVE models to list — the static backfill in
    fetch_model_catalog still offers it), never raises.
    """
    r = await _redis()
    if r is None:
        return ""
    try:
        raw = await r.get("imperal:config:llm") or "{}"
        cfg = json.loads(raw)
    except Exception:
        return ""
    finally:
        try:
            await r.aclose()
        except Exception:
            pass
    key = str(cfg.get(f"{provider}_api_key") or "")
    if not key and cfg.get("provider") == provider:
        key = str(cfg.get("api_key") or "")
    if not key:
        return ""
    if key.startswith("gAAAAA"):  # Fernet-wrapped — mirror kernel llm/secrets.py
        try:
            from cryptography.fernet import Fernet
            fkey = os.getenv("IMPERAL_ENCRYPTION_KEY", "") or os.getenv("IMAP_ENCRYPTION_KEY", "")
            if fkey:
                key = Fernet(fkey.encode()).decrypt(key.encode()).decode()
        except Exception:
            return ""
    return key


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
    # Kimi (Moonshot) + GLM (Zhipu z.ai): first-class system providers, keys
    # PANEL-entered like qwen's (2026-08-30). Each fetcher hits the vendor's
    # OWN endpoint, so the catalogue can only ever list that vendor's models.
    kk = await _store_key_for("kimi")
    if kk:
        try:
            catalog["kimi"] = await _fetch_kimi(kk)
        except Exception as e:
            log.warning(
                "model_catalog: kimi fetch failed: %s: %s",
                type(e).__name__, e or "(no detail)",
            )
    zk = await _store_key_for("zhipu")
    if zk:
        try:
            catalog["zhipu"] = await _fetch_zhipu(zk)
        except Exception as e:
            log.warning(
                "model_catalog: zhipu fetch failed: %s: %s",
                type(e).__name__, e or "(no detail)",
            )
    gk = os.getenv("GOOGLE_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")
    if gk:
        try:
            catalog["google"] = await _fetch_google(gk)
        except Exception as e:
            log.warning(
                "model_catalog: google fetch failed: %s: %s",
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
    expected = {p for p, key in (("anthropic", ak), ("openai", ok), ("qwen", qk), ("google", gk), ("kimi", kk), ("zhipu", zk)) if key}
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
    # Kimi + Zhipu are panel-keyed exactly like qwen (2026-08-30): same
    # unconditional backfill so the admin can pick their models in the SAME
    # save that enters the key. The kernel still refuses a keyless config.
    for _p in ("kimi", "zhipu"):
        if _p not in catalog:
            catalog[_p] = list(FALLBACK_CATALOG.get(_p, []))

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
