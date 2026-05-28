"""Admin · Shared data fetchers, formatters, and system panel builder.

Management (users) panel lives in panels_users.py.
Dashboard is in panels_dashboard.py. LLM is in panels_llm.py.
"""
from __future__ import annotations
import asyncio
import time

import json
import logging
import os

import httpx
from imperal_sdk import ui

from app import _gw_request, _registry_get, AUTH_GW, REGISTRY_URL

log = logging.getLogger("admin")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# ── In-memory TTL cache (cross-panel, cleared on write actions) ───────

_cache: dict[str, tuple[float, object]] = {}
_CACHE_TTL = 10  # seconds — short enough to see changes quickly


async def _cached(key: str, factory):
    """Return cached result if <TTL, otherwise call factory and cache.

    Empty / falsy results are NOT cached — every fetcher in this module
    swallows exceptions and falls back to `{}` / `[]`, so caching that
    fallback would pin the UI to inline `.get("x", default)` defaults for
    a full TTL window after every transient Auth-GW blip. Re-fetching on
    the next render is cheap and lets the UI self-heal.
    """
    now = time.monotonic()
    if key in _cache:
        ts, val = _cache[key]
        if now - ts < _CACHE_TTL:
            return val
    val = await factory()
    if val:
        _cache[key] = (now, val)
    return val


def _invalidate_panel_cache():
    """Call after write actions to force fresh data on next render."""
    _cache.clear()



# ── Formatting helpers ────────────────────────────────────────────────


def _fmt_tokens(n) -> str:
    if n is None:
        return "\u2014"
    n = int(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _fmt_latency(ms) -> str:
    if ms is None:
        return "\u2014"
    return f"{float(ms) / 1000:.2f}s"


# ── Data fetchers (safe, never raise) ─────────────────────────────────


async def _fetch_users_raw() -> list[dict]:
    try:
        raw = await _gw_request("GET", "/v1/users?include_inactive=true")
        users = raw.get("items", raw) if isinstance(raw, dict) else raw
        return users if isinstance(users, list) else []
    except Exception as e:
        log.warning("Panel: fetch users failed: %s", e)
        return []


async def _fetch_users() -> list[dict]:
    return await _cached("users", _fetch_users_raw)


async def _fetch_roles_raw() -> list[dict]:
    try:
        roles = await _gw_request("GET", "/v1/roles")
        return roles if isinstance(roles, list) else []
    except Exception as e:
        log.warning("Panel: fetch roles failed: %s", e)
        return []


async def _fetch_roles() -> list[dict]:
    return await _cached("roles", _fetch_roles_raw)


async def _fetch_extensions_raw() -> list[dict]:
    try:
        r = await _registry_get("/v1/apps?status=active")
        if r.status_code == 200:
            apps = r.json()
            return apps if isinstance(apps, list) else []
        return []
    except Exception as e:
        log.warning("Panel: fetch extensions failed: %s", e)
        return []


async def _fetch_extensions() -> list[dict]:
    return await _cached("extensions", _fetch_extensions_raw)


async def _fetch_scopes_raw() -> list[dict]:
    """Fetch all scopes (full objects) from Auth GW."""
    try:
        scopes = await _gw_request("GET", "/v1/scopes")
        return scopes if isinstance(scopes, list) else []
    except Exception:
        return []


async def _fetch_scopes() -> list[dict]:
    return await _cached("scopes", _fetch_scopes_raw)


async def _fetch_scope_names() -> list[str]:
    """Convenience: just scope name strings."""
    scopes = await _fetch_scopes()
    return [s.get("name", "") for s in scopes if s.get("name")]


async def _fetch_user_extensions_raw(user_id: str) -> list[dict]:
    """Fetch per-user extension access list from Auth GW."""
    try:
        result = await _gw_request("GET", f"/v1/users/{user_id}/extensions")
        if isinstance(result, dict):
            return result.get("extensions", [])
        return result if isinstance(result, list) else []
    except Exception:
        return []


async def _fetch_user_extensions(user_id: str) -> list[dict]:
    return await _cached(
        f"user_ext:{user_id}",
        lambda: _fetch_user_extensions_raw(user_id),
    )


async def _fetch_llm_usage_raw() -> dict:
    """Fetch LLM usage from Auth GW, transform to UI-compatible names."""
    try:
        raw = await _gw_request("GET", "/v1/internal/config/llm/usage")
        if not isinstance(raw, dict):
            return {}
        calls = int(raw.get("calls", 0))
        latency = int(raw.get("total_latency_ms", 0))
        return {
            "total_calls": calls,
            "byollm_users": int(raw.get("byollm_calls", 0)),
            "total_tokens_in": int(raw.get("input_tokens", 0)),
            "total_tokens_out": int(raw.get("output_tokens", 0)),
            "failover_events": int(raw.get("failover_calls", 0)),
            "avg_latency_ms": round(latency / calls) if calls > 0 else 0,
        }
    except Exception:
        return {}


async def _fetch_llm_usage() -> dict:
    return await _cached("llm_usage", _fetch_llm_usage_raw)


async def _fetch_action_stats_raw() -> dict:
    try:
        return await _gw_request("GET", "/v1/internal/actions/stats?admin=true")
    except Exception:
        return {}


async def _fetch_action_stats() -> dict:
    return await _cached("action_stats", _fetch_action_stats_raw)


async def _check_health_raw(name: str, url: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.get(url)
            return "Operational" if r.status_code == 200 else "Degraded"
    except Exception:
        return "Unreachable"


async def _check_health(name: str, url: str) -> str:
    return await _cached(f"health:{name}", lambda: _check_health_raw(name, url))


# ── System ────────────────────────────────────────────────────────────

async def build_system(ctx, **kwargs):
    """System info — health + identity only.

    Context/LLM tunables moved to LLM Config tab → Token Budget Controls
    section (Phase 16, 2026-05-17). Federal rule 11: no orphan UI.
    """
    gw, reg = await asyncio.gather(
        _check_health("auth_gateway", f"{AUTH_GW}/healthz"),
        _check_health("registry", f"{REGISTRY_URL}/health"),
    )

    gw_color = "green" if gw == "Operational" else "red"
    reg_color = "green" if reg == "Operational" else "red"

    return ui.Stack(children=[
        ui.Header("System", level=3),
        ui.Stats(children=[
            ui.Stat(label="Auth Gateway", value=gw, color=gw_color),
            ui.Stat(label="Registry", value=reg, color=reg_color),
        ], columns=2),
        ui.KeyValue(items=[
            {"key": "Platform", "value": "Imperal Cloud ICNLI OS v1.0"},
            {"key": "Auth Gateway", "value": f"auth.imperal.io ({AUTH_GW})"},
            {"key": "Registry", "value": f"api-server:8098 ({REGISTRY_URL})"},
        ]),
        ui.Alert(
            title="Context & LLM tunables",
            message="Moved to the LLM Config tab → Token Budget Controls (Phase 16, 2026-05-17).",
            type="info",
        ),
    ])
