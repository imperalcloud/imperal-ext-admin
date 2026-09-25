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
from imperal_sdk._shared_http import shared_http
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


async def _fetch_plans_raw() -> list[dict]:
    """Fetch billing plans from Auth GW (same read fn_billing_overview uses)."""
    try:
        plans = await _gw_request("GET", "/v1/billing/plans")
        return plans if isinstance(plans, list) else []
    except Exception as e:
        log.warning("Panel: fetch plans failed: %s", e)
        return []


async def _fetch_plans() -> list[dict]:
    return await _cached("plans", _fetch_plans_raw)


async def _fetch_extensions_raw() -> list[dict]:
    """Cross-store view of every app: merge the Registry (`/v1/apps`), the
    Marketplace store (`developer_apps` via `/v1/admin/apps`), and the on-disk
    `/opt/extensions/<id>` tree. Each returned app carries a ``stores`` list so
    the panel can show exactly WHERE it lives — these three stores can drift."""
    reg_list: list = []
    dev_list: list = []
    try:
        r = await _registry_get("/v1/apps?status=active")
        if r.status_code == 200 and isinstance(r.json(), list):
            reg_list = r.json()
    except Exception as e:
        log.warning("Panel: registry fetch failed: %s", e)
    try:
        d = await _gw_request("GET", "/v1/admin/apps")
        if isinstance(d, list):
            dev_list = d
    except Exception as e:
        log.warning("Panel: developer_apps fetch failed: %s", e)

    merged: dict[str, dict] = {}
    for a in reg_list:
        aid = a.get("app_id") or a.get("id")
        if not aid:
            continue
        m = merged.setdefault(aid, {"app_id": aid, "stores": []})
        m.update({k: v for k, v in a.items() if v not in (None, "")})
        m["app_id"] = aid
        m["registry_status"] = a.get("status")
        if "Registry" not in m["stores"]:
            m["stores"].append("Registry")
    for a in dev_list:
        aid = a.get("app_id")
        if not aid:
            continue
        m = merged.setdefault(aid, {"app_id": aid, "stores": []})
        for k, v in a.items():
            if v not in (None, "") and (k not in m or m.get(k) in (None, "")):
                m[k] = v
        m["app_id"] = aid
        m["marketplace_status"] = a.get("status")
        if "Marketplace" not in m["stores"]:
            m["stores"].append("Marketplace")
    for aid, m in merged.items():
        try:
            if os.path.isdir(f"/opt/extensions/{aid}"):
                m["stores"].append("Disk")
        except Exception:
            pass
        # Status badge = LIFECYCLE truth. developer_apps.status (marketplace) is the
        # SINGLE SOURCE OF TRUTH for the lifecycle state — active / suspended /
        # draft / pending_review. The Registry status is only 2-state usability, so
        # reading it made a drafted app wrongly show "Active" (Registry stays active
        # on a soft draft). Fall back to Registry only for non-marketplace/system
        # apps that aren't in developer_apps.
        m["status"] = (m.get("marketplace_status") or m.get("registry_status")
                       or m.get("status") or "unknown")
    return sorted(merged.values(), key=lambda x: x.get("app_id", ""))


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
        async with shared_http(timeout=3) as c:
            r = await c.get(url)
            return "Operational" if r.status_code == 200 else "Degraded"
    except Exception:
        return "Unreachable"


async def _check_health(name: str, url: str) -> str:
    return await _cached(f"health:{name}", lambda: _check_health_raw(name, url))


# ── System ────────────────────────────────────────────────────────────

async def build_system(ctx, **kwargs):
    """System info — platform topology graph, health, temporal cluster, and services."""
    gw, reg = await asyncio.gather(
        _check_health("auth_gateway", f"{AUTH_GW}/healthz"),
        _check_health("registry", f"{REGISTRY_URL}/health"),
    )

    gw_color = "green" if gw == "Operational" else "red"
    reg_color = "green" if reg == "Operational" else "red"

    # Core node services
    temporal_status = "Operational" if TEMPORAL_HOST else "Unconfigured"
    temporal_color = "green" if temporal_status == "Operational" else "amber"

    # 1. Interactive Cluster Topology Graph (Cytoscape / react-cytoscapejs)
    graph_nodes = [
        {"id": "auth_gw", "label": "Auth Gateway\n(104.224.88.155:8085)", "type": "gateway", "size": 48},
        {"id": "worker", "label": "Platform Worker\n(104.224.88.156)", "type": "worker", "size": 56},
        {"id": "temporal", "label": "Temporal Cluster\n(port: 7233)", "type": "orchestrator", "size": 44},
        {"id": "registry", "label": "Registry Service\n(66.78.41.10:8098)", "type": "registry", "size": 40},
        {"id": "redis", "label": "Config Store & Redis\n(cache & routing)", "type": "database", "size": 36},
    ]
    graph_edges = [
        {"source": "auth_gw", "target": "worker", "label": "HTTP / gRPC", "type": "control"},
        {"source": "worker", "target": "temporal", "label": "Workflows", "type": "state"},
        {"source": "worker", "target": "registry", "label": "Sync API", "type": "meta"},
        {"source": "worker", "target": "redis", "label": "Routing Cache", "type": "fast"},
        {"source": "auth_gw", "target": "redis", "label": "Token Ledger", "type": "auth"},
    ]

    return ui.Stack(children=[
        ui.Header("System Architecture & Cluster Topology", level=3),
        ui.Stats(children=[
            ui.Stat(label="Auth Gateway", value=gw, color=gw_color),
            ui.Stat(label="Registry", value=reg, color=reg_color),
            ui.Stat(label="Temporal Cluster", value=temporal_status, color=temporal_color),
            ui.Stat(label="Decentralized OS", value="Active", color="blue"),
        ], columns=2),
        ui.Card(
            title="Interactive Cluster Topology (Cytoscape Graph)",
            content=ui.Graph(
                nodes=graph_nodes,
                edges=graph_edges,
                layout="cose-bilkent",
                height=320,
                edge_label_visible=True,
                color_by="type",
            ),
        ),
        ui.Card(
            title="Cluster & Core Services",
            content=ui.KeyValue(items=[
                {"key": "OS Architecture", "value": "Imperal Cloud ICNLI AI Cloud OS (Decentralized)"},
                {"key": "Auth Gateway", "value": f"auth.imperal.io ({AUTH_GW})"},
                {"key": "Registry API", "value": f"api-server:8098 ({REGISTRY_URL})"},
                {"key": "Temporal Host", "value": f"{TEMPORAL_HOST}:{TEMPORAL_PORT} (ns: {TEMPORAL_NAMESPACE})"},
            ])
        ),
        ui.Alert(
            title="Context & LLM Tunables",
            message="LLM provider configurations and neural routing are managed under the LLM Config section.",
            type="info",
        ),
    ])
