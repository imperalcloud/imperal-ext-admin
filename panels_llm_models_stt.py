"""Dynamic STT (speech-to-text) model catalogue — fetched live using the
admin's own BYOK key (2026-08-29, owner report pass 2: "чтобы я свой ключ от
любого провайдера мог юзать ... автоматически подгружать доступные ... модели
для STT").

Mirrors panels_llm_models.py's pattern (Redis-stored key → Fernet decrypt →
live provider fetch → Redis cache → static fallback) but filtered for
TRANSCRIPTION-capable models (whisper/transcribe families) instead of chat
models — the two catalogues answer different questions from the same kind
of /v1/models endpoint.

Public API:
  - STT_PROVIDERS               -> ui.Select options for the provider dropdown
  - STT_PROVIDER_DEFAULT_BASE   -> {provider: default_base_url}
  - async fetch_stt_model_catalog(provider) -> [model_id, ...] for that provider,
                                    using the BYOK key stored in the LLM Config
                                    Store (imperal:config:llm.stt)
  - STT_FALLBACK                -> resilience-only minimal per-provider list
"""
from __future__ import annotations

import json
import logging
import os

from imperal_sdk._shared_http import shared_http

log = logging.getLogger("admin")

_CACHE_KEY = "imperal:config:llm:stt_model_catalog"
_CACHE_TTL = 3600        # 1h — providers add STT models rarely
_CACHE_TTL_DEGRADED = 120  # 2m — retry sooner after a transient fetch failure

# Any OpenAI-Whisper-API-compatible endpoint works for "custom" — base_url is
# admin-supplied and required for that choice. openai/groq get a sane preset
# default so the admin only has to type a base_url for something truly custom.
STT_PROVIDERS: list[dict] = [
    {"value": "openai", "label": "OpenAI (Whisper)"},
    {"value": "groq", "label": "Groq (Whisper large-v3, fast + cheap)"},
    {"value": "custom", "label": "Custom (any OpenAI-Whisper-API-compatible)"},
]

STT_PROVIDER_DEFAULT_BASE: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "groq": "https://api.groq.com/openai/v1",
}

# Resilience-only fallback (used iff BOTH live fetch and cache fail).
STT_FALLBACK: dict[str, list[str]] = {
    "openai": ["whisper-1", "gpt-4o-transcribe", "gpt-4o-mini-transcribe"],
    "groq": ["whisper-large-v3", "whisper-large-v3-turbo", "distil-whisper-large-v3-en"],
    "custom": [],
}


def _decrypt_stt_key(key: str) -> str:
    """Unwrap a Fernet-wrapped key using the SAME env keys the kernel/gateway
    use. Mirrors panels_llm_models.py's inline Qwen unwrap block exactly."""
    if not key or not (key.startswith("gAAAAA") and len(key) > 60):
        return key
    try:
        from cryptography.fernet import Fernet
        fkey = os.getenv("IMPERAL_ENCRYPTION_KEY", "") or os.getenv("IMAP_ENCRYPTION_KEY", "")
        if fkey:
            return Fernet(fkey.encode()).decrypt(key.encode()).decode()
    except Exception:
        pass
    return ""


async def _redis():
    url = os.getenv("REDIS_URL", "")
    if not url:
        return None
    try:
        import redis.asyncio as aioredis
        return aioredis.from_url(url, decode_responses=True)
    except Exception as e:  # pragma: no cover - defensive
        log.warning("stt_model_catalog: redis unavailable: %s", e)
        return None


async def _stt_key_from_store() -> tuple[str, str, str]:
    """(provider, key, base_url) for STT from the LLM Config Store's nested
    `stt` dict, or ("", "", "") if never configured. A masked value (contains
    the bullet char, i.e. the panel never got a real fresh key from Redis
    directly -- shouldn't normally happen since this reads Redis, not a GET
    response, but guarded defensively) yields no usable key."""
    r = await _redis()
    if r is None:
        return "", "", ""
    try:
        raw = await r.get("imperal:config:llm") or "{}"
        cfg = json.loads(raw)
    except Exception:
        return "", "", ""
    finally:
        try:
            await r.aclose()
        except Exception:
            pass
    stt = cfg.get("stt") if isinstance(cfg.get("stt"), dict) else {}
    provider = str(stt.get("provider") or "openai")
    key = str(stt.get("api_key") or "")
    if "\u2022" in key:
        return provider, "", ""
    key = _decrypt_stt_key(key)
    base_url = str(stt.get("base_url") or "")
    return provider, key, base_url


async def fetch_stt_model_catalog() -> list[str]:
    """Return the live model list for the CURRENTLY configured STT provider.

    cache -> live fetch (using the admin's own BYOK key) -> static fallback.
    Never raises -- a fetch failure just means the section falls back to a
    plain text Model input instead of a populated dropdown.
    """
    provider, key, base_url = await _stt_key_from_store()
    if not key:
        # No BYOK key saved yet — nothing to call live with. Offer the
        # resilience-only static list for whatever provider is selected so
        # the dropdown is never completely empty pre-save.
        return list(STT_FALLBACK.get(provider, []))

    r = await _redis()
    cache_key = f"{_CACHE_KEY}:{provider}"
    if r is not None:
        try:
            cached = await r.get(cache_key)
            if cached:
                await r.aclose()
                return json.loads(cached)
        except Exception as e:
            log.warning("stt_model_catalog: cache read failed: %s", e)

    base = base_url or STT_PROVIDER_DEFAULT_BASE.get(provider, "")
    if not base:
        # "custom" with no base_url yet -- can't call anything live.
        if r is not None:
            try:
                await r.aclose()
            except Exception:
                pass
        return list(STT_FALLBACK.get(provider, []))

    models: list[str] = []
    degraded = False
    try:
        url = base.rstrip("/") + "/models"
        async with shared_http(timeout=12.0) as c:
            resp = await c.get(url, headers={"Authorization": f"Bearer {key}"})
            resp.raise_for_status()
            models = sorted({m.get("id", "") for m in resp.json().get("data", []) if m.get("id")})
    except Exception as e:
        log.warning(
            "stt_model_catalog: %s fetch failed: %s: %s",
            provider, type(e).__name__, e or "(no detail)",
        )
        degraded = True

    if not models:
        models = list(STT_FALLBACK.get(provider, []))
        degraded = True

    if r is not None:
        try:
            ttl = _CACHE_TTL_DEGRADED if degraded else _CACHE_TTL
            await r.set(cache_key, json.dumps(models), ex=ttl)
        except Exception as e:
            log.warning("stt_model_catalog: cache write failed: %s", e)
        try:
            await r.aclose()
        except Exception:
            pass

    return models
