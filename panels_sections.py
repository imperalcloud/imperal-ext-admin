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


async def _cached(ctx, key: str, factory):
    """Return cached result if <TTL, otherwise call factory and cache."""
    now = time.monotonic()
    if key in _cache:
        ts, val = _cache[key]
        if now - ts < _CACHE_TTL:
            return val
    val = await factory(ctx)
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


async def _fetch_users_raw(ctx) -> list[dict]:
    try:
        raw = await _gw_request(ctx, "GET", "/v1/users?include_inactive=true")
        users = raw.get("items", raw) if isinstance(raw, dict) else raw
        return users if isinstance(users, list) else []
    except Exception as e:
        log.warning("Panel: fetch users failed: %s", e)
        return []


async def _fetch_users(ctx) -> list[dict]:
    return await _cached(ctx, "users", _fetch_users_raw)


async def _fetch_roles_raw(ctx) -> list[dict]:
    try:
        roles = await _gw_request(ctx, "GET", "/v1/roles")
        return roles if isinstance(roles, list) else []
    except Exception as e:
        log.warning("Panel: fetch roles failed: %s", e)
        return []


async def _fetch_roles(ctx) -> list[dict]:
    return await _cached(ctx, "roles", _fetch_roles_raw)


async def _fetch_extensions_raw(ctx) -> list[dict]:
    try:
        r = await _registry_get(ctx, "/v1/apps?status=active")
        if r.status_code == 200:
            apps = r.json()
            return apps if isinstance(apps, list) else []
        return []
    except Exception as e:
        log.warning("Panel: fetch extensions failed: %s", e)
        return []


async def _fetch_extensions(ctx) -> list[dict]:
    return await _cached(ctx, "extensions", _fetch_extensions_raw)


async def _fetch_scopes_raw(ctx) -> list[dict]:
    """Fetch all scopes (full objects) from Auth GW."""
    try:
        scopes = await _gw_request(ctx, "GET", "/v1/scopes")
        return scopes if isinstance(scopes, list) else []
    except Exception:
        return []


async def _fetch_scopes(ctx) -> list[dict]:
    return await _cached(ctx, "scopes", _fetch_scopes_raw)


async def _fetch_scope_names(ctx) -> list[str]:
    """Convenience: just scope name strings."""
    scopes = await _fetch_scopes(ctx)
    return [s.get("name", "") for s in scopes if s.get("name")]


async def _fetch_user_extensions_raw(ctx, user_id: str) -> list[dict]:
    """Fetch per-user extension access list from Auth GW."""
    try:
        result = await _gw_request(ctx, "GET", f"/v1/users/{user_id}/extensions")
        if isinstance(result, dict):
            return result.get("extensions", [])
        return result if isinstance(result, list) else []
    except Exception:
        return []


async def _fetch_user_extensions(ctx, user_id: str) -> list[dict]:
    return await _cached(ctx,
        f"user_ext:{user_id}",
        lambda ctx: _fetch_user_extensions_raw(ctx, user_id),
    )


async def _fetch_llm_usage_raw(ctx) -> dict:
    """Fetch LLM usage from Auth GW, transform to UI-compatible names."""
    try:
        raw = await _gw_request(ctx, "GET", "/v1/internal/config/llm/usage")
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


async def _fetch_llm_usage(ctx) -> dict:
    return await _cached(ctx, "llm_usage", _fetch_llm_usage_raw)


async def _fetch_action_stats_raw(ctx) -> dict:
    try:
        return await _gw_request(ctx, "GET", "/v1/internal/actions/stats?admin=true")
    except Exception:
        return {}


async def _fetch_action_stats(ctx) -> dict:
    return await _cached(ctx, "action_stats", _fetch_action_stats_raw)


async def _check_health_raw(ctx, name: str, url: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.get(url)
            return "Operational" if r.status_code == 200 else "Degraded"
    except Exception:
        return "Unreachable"


async def _check_health(ctx, name: str, url: str) -> str:
    return await _cached(ctx, f"health:{name}", lambda ctx: _check_health_raw(ctx, name, url))


async def _fetch_context_defaults(ctx) -> dict:
    """Fetch actual context defaults from Auth GW platform config.

    React reads from GET /v1/internal/config/platform/platform -> config.context_defaults.
    Must use same source for data parity.
    """
    try:
        raw = await _gw_request(ctx, "GET", "/v1/internal/config/platform/platform")
        if isinstance(raw, dict):
            config = raw.get("config", {})
            return config.get("context_defaults", {})
        return {}
    except Exception as e:
        log.warning("Panel: fetch context defaults failed: %s", e)
    return {}


# ── System ────────────────────────────────────────────────────────────

# (key, label, default, min, max)
_CTX_FIELDS = [
    ("quality_ceiling_tokens", "Quality Ceiling (tokens)", 50000, 5000, 500000),
    ("default_context_window", "Default History Window", 20, 5, 200),
    ("default_max_tool_rounds", "Max Tool Rounds", 10, 1, 50),
    ("default_max_result_tokens", "Max Result Size (tokens)", 3000, 500, 50000),
    ("default_keep_recent", "Keep Recent Verbatim", 6, 1, 50),
    ("list_truncate_items", "List Truncate (items)", 10, 1, 100),
    ("string_truncate_chars", "String Truncate (chars)", 1500, 100, 50000),
    ("max_history_stored", "Max Messages Stored", 40, 10, 200),
    ("history_ttl_days", "History TTL (days)", 7, 1, 90),
]


async def build_system(ctx, **kwargs):
    """System info + context defaults form with ACTUAL values from Redis."""
    gw, reg, stored = await asyncio.gather(
        _check_health("auth_gateway", f"{AUTH_GW}/healthz"),
        _check_health("registry", f"{REGISTRY_URL}/health"),
        _fetch_context_defaults(ctx),
    )

    gw_color = "green" if gw == "Operational" else "red"
    reg_color = "green" if reg == "Operational" else "red"

    form_defaults = {}
    form_children = []
    for key, label, default, mn, mx in _CTX_FIELDS:
        current = stored.get(key, default)
        form_defaults[key] = str(current)
        form_children.append(ui.Stack([
            ui.Text(f"{label}  ({mn}\u2013{mx}, default {default})", variant="caption"),
            ui.Input(
                placeholder=str(default),
                param_name=key,
                value=str(current),
            ),
        ], gap=1))

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
        ui.Divider(),
        ui.Header("Context Defaults", level=4,
                   subtitle="Platform-wide context window settings"),
        ui.Form(
            action="save_context_defaults",
            submit_label="Save Context Defaults",
            defaults=form_defaults,
            children=form_children,
        ),
        ui.Button(
            "Reset to Defaults",
            variant="ghost",
            on_click=ui.Call("reset_context_defaults"),
        ),
    ])
