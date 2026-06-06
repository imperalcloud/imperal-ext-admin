"""Dynamic LLM model catalogue — fetched live from the providers' APIs.

No hardcoded model list. The models offered in LLM Config come from the
providers' own `/v1/models` endpoints (keys from env), filtered to
chat-capable text models, cached in Redis (1h). A tiny static fallback is
used ONLY if every live + cache path fails, so the form never breaks.

Public API:
  - provider_for_model(model)        -> "anthropic" | "openai" | "google" | ""
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

log = logging.getLogger("admin")

_CACHE_KEY = "imperal:config:llm:model_catalog"
_CACHE_TTL = 3600  # seconds (1h) — providers add models rarely

# Provider inference by model-id prefix (rule-based, not an enumerated list).
_PROVIDER_PREFIXES: tuple[tuple[str, str], ...] = (
    ("claude", "anthropic"),
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
}


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


async def _fetch_anthropic(key: str) -> list[str]:
    async with httpx.AsyncClient(timeout=12.0) as c:
        r = await c.get(
            "https://api.anthropic.com/v1/models",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
        )
        r.raise_for_status()
        return _filter_anthropic([m.get("id", "") for m in r.json().get("data", [])])


async def _fetch_openai(key: str) -> list[str]:
    async with httpx.AsyncClient(timeout=12.0) as c:
        r = await c.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {key}"},
        )
        r.raise_for_status()
        return _filter_openai([m.get("id", "") for m in r.json().get("data", [])])


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
            log.warning("model_catalog: anthropic fetch failed: %s", e)
    if ok:
        try:
            catalog["openai"] = await _fetch_openai(ok)
        except Exception as e:
            log.warning("model_catalog: openai fetch failed: %s", e)

    catalog = {p: m for p, m in catalog.items() if m}
    if not catalog:
        if r is not None:
            try:
                await r.aclose()
            except Exception:
                pass
        log.warning("model_catalog: all live fetches empty — using fallback")
        return {p: list(v) for p, v in FALLBACK_CATALOG.items()}

    # 3. Cache the live result
    if r is not None:
        try:
            await r.set(_CACHE_KEY, json.dumps(catalog), ex=_CACHE_TTL)
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
