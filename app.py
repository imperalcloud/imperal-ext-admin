"""
Admin v5.2.2 — shared state.

Platform administration via Auth Gateway + Registry APIs.
"""
import logging
import os

import httpx

from imperal_sdk import Extension
from imperal_sdk.chat import ChatExtension, ActionResult
from pydantic import BaseModel


class EmptyParams(BaseModel):
    """Federal V17 placeholder for handlers that take no parameters.

    `@chat.function` MUST declare a Pydantic params model — this is the
    canonical empty model reused by read-only handlers (list_*, get_*,
    *_health) that don't need any input.
    """
    pass


log = logging.getLogger("admin")

# ── Config ────────────────────────────────────────────────────────────────────

AUTH_GW = os.getenv("IMPERAL_GATEWAY_URL", "http://104.224.88.155:8085")
REGISTRY_URL = os.getenv("REGISTRY_URL", "http://66.78.41.10:8098")
REGISTRY_KEY = os.getenv("REGISTRY_API_KEY", "")
AUTH_SERVICE_TOKEN = os.getenv("AUTH_SERVICE_TOKEN", "")
REDIS_URL = os.getenv("REDIS_URL", "")
TEMPORAL_HOST = os.getenv("TEMPORAL_HOST", "104.224.88.156")
TEMPORAL_PORT = int(os.getenv("TEMPORAL_PORT", "7233"))
TEMPORAL_NAMESPACE = os.getenv("TEMPORAL_NAMESPACE", "default")

# ── HTTP ──────────────────────────────────────────────────────────────────────

_http = None


def _get_http():
    global _http
    if _http is None:
        _http = httpx.AsyncClient(
            base_url=AUTH_GW,
            headers={"X-Service-Token": AUTH_SERVICE_TOKEN},
            timeout=10.0,
        )
    return _http


async def _gw_request(method, path, data=None):
    c = _get_http()
    if method.upper() in ("POST", "PUT", "PATCH"):
        r = await getattr(c, method.lower())(path, json=data)
    else:
        r = await getattr(c, method.lower())(path)
    return r.json()


async def _registry_get(path):
    async with httpx.AsyncClient(timeout=10) as c:
        return await c.get(f"{REGISTRY_URL}{path}", headers={"x-api-key": REGISTRY_KEY})


async def _registry_put(path, data):
    async with httpx.AsyncClient(timeout=10) as c:
        return await c.put(f"{REGISTRY_URL}{path}", json=data,
                           headers={"x-api-key": REGISTRY_KEY, "Content-Type": "application/json"})


async def _registry_patch(path, data):
    async with httpx.AsyncClient(timeout=10) as c:
        return await c.patch(f"{REGISTRY_URL}{path}", json=data,
                             headers={"x-api-key": REGISTRY_KEY, "Content-Type": "application/json"})

# ── Helpers ───────────────────────────────────────────────────────────────────


def _user_id(ctx) -> str:
    return ctx.user.imperal_id if hasattr(ctx, "user") and ctx.user else ""


def _tenant_id(ctx) -> str:
    if hasattr(ctx, "user") and ctx.user and hasattr(ctx.user, "tenant_id"):
        return ctx.user.tenant_id
    return "default"


async def _resolve_app_id(app_id, include_all=False):
    if not app_id:
        return app_id
    status = "all" if include_all else "active"
    r = await _registry_get(f"/v1/apps?status={status}")
    if r.status_code != 200:
        return app_id
    apps = r.json()
    if not isinstance(apps, list):
        return app_id
    for a in apps:
        if a.get("app_id") == app_id:
            return app_id
    for a in apps:
        aid = a.get("app_id", "")
        if aid.startswith(app_id) or app_id in aid:
            return aid
    return app_id


async def _resolve_user_by_email(email):
    raw = await _gw_request("GET", f"/v1/users?search={email}")
    users = raw.get("items", raw) if isinstance(raw, dict) else raw
    if isinstance(users, list):
        for u in users:
            if u.get("email", "").lower() == email.lower():
                return u.get("imperal_id") or u.get("id")
    return None


async def _resolve_role_by_name(role_name):
    roles = await _gw_request("GET", "/v1/roles")
    if isinstance(roles, list):
        for r in roles:
            if r.get("name", "").lower() == role_name.lower():
                return r
    return None


async def _invalidate_extension_caches(user_id: str = None):
    if not REDIS_URL:
        return
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(REDIS_URL, decode_responses=True)
        await r.delete("imperal:access_policies")
        if user_id:
            await r.delete(f"imperal:user_disabled:{user_id}")
        await r.aclose()
    except Exception as e:
        log.warning(f"Cache invalidation non-critical: {e}")


async def _signal_session_refresh(user_id: str):
    try:
        from temporalio.client import Client
        client = await Client.connect(f"{TEMPORAL_HOST}:{TEMPORAL_PORT}", namespace=TEMPORAL_NAMESPACE)
        handle = client.get_workflow_handle(f"session-{user_id}")
        await handle.signal("update_config")
    except Exception as e:
        log.debug(f"Session signal non-critical for {user_id}: {e}")

# ── System prompt ─────────────────────────────────────────────────────────────

from pathlib import Path as _Path
SYSTEM_PROMPT = (_Path(__file__).parent / "system_prompt.txt").read_text()

# ── Extension ─────────────────────────────────────────────────────────────────

ext = Extension(
    "admin",
    version="5.2.2",
    capabilities=[
        # User CRUD (create/update/deactivate/delete/limits/attributes)
        "admin:users:read", "admin:users:write", "admin:users:delete",
        # Roles + RBAC scopes + policies
        "admin:roles:read", "admin:roles:write",
        "admin:scopes:read", "admin:scopes:write",
        # Extension lifecycle + per-extension settings (8 save_ext_* handlers)
        "admin:extensions:read", "admin:extensions:write",
        # Billing admin (balances, adjustments, overview)
        "admin:billing:read", "admin:billing:write",
        # System config (context defaults, rules, confirmation/task limits, health)
        "admin:system:read", "admin:system:write",
        # Audit log
        "admin:audit:read",
        # LLM provider configuration + connection test
        "admin:llm:read", "admin:llm:write",
        # Payment provider config + connection test
        "admin:payment:read", "admin:payment:write",
        # Developer portal review workflow (apps, payouts)
        "admin:developer:review",
        # Namespace umbrella for tool_admin_chat orchestration (E8)
        "admin:*",
        # Storage for settings + LLM config blobs
        "config:read", "config:write",
        "store:read", "store:write",
        # LLM calls (health-aware summary, route test)
        "ai:complete",
        # Cross-user target scope guard (admin routinely targets other users)
        "users:read", "users:manage", "users:admin",
    ],
    display_name='Admin',
    description=(
        'Administrative control plane — manage users, roles, RBAC scopes, billing limits, payment plans, extension installs, LLM model configuration, and tenant-wide settings.'
    ),
    icon="icon.svg",
    actions_explicit=True,
)

chat = ChatExtension(
    ext=ext,
    tool_name="tool_admin_chat",
    description=(
        "Admin assistant — manage users, roles, extensions and system health. "
        "RBAC scopes, effective permissions, compare roles, bulk assign, audit log, "
        "extension access policies, deny/allow extensions"
    ),
    system_prompt=SYSTEM_PROMPT,
    max_rounds=10,
)

# Inject skeleton live stats into system prompt
_original_build_system = chat._build_system_prompt


def _patched_build_system_prompt(ctx):
    base = _original_build_system(ctx)
    skeleton = ctx.skeleton_data or {} if hasattr(ctx, "skeleton_data") else {}
    stats = skeleton.get("admin_stats", {})
    context = skeleton.get("_context", {})

    extra = ""
    if stats:
        users_block = ""
        for u in stats.get("users_list", []):
            status = "ACTIVE" if u.get("active") else "INACTIVE"
            users_block += f"  - {u.get('email','')} | {u.get('role','')} | {status} | id={u.get('id','')}\n"
        extra += f"""
LIVE STATS (awareness only — call functions for actual data):
- Users: {stats.get('users_total', '?')} total, {stats.get('users_active', '?')} active
- Roles: {stats.get('roles_count', '?')}
- Extensions: {stats.get('extensions_active', '?')} active
- Auth Gateway: {stats.get('health_auth_gateway', '?')}
- Registry: {stats.get('health_registry', '?')}
{users_block}"""

    if context.get("hub_mode"):
        exts = context.get("extensions_info", [])
        if exts:
            extra += "\nACTIVE EXTENSIONS:\n"
            for e in exts:
                extra += f"  - {e.get('name', e.get('app_id', '?'))} ({e.get('app_id', '')})\n"

    return base + extra


chat._build_system_prompt = _patched_build_system_prompt

# ── Health check ──────────────────────────────────────────────────────────────


@ext.health_check
async def health(ctx) -> dict:
    results = {}
    for name, url in [("auth_gateway", f"{AUTH_GW}/healthz"), ("registry", f"{REGISTRY_URL}/health")]:
        try:
            async with httpx.AsyncClient(timeout=3) as c:
                r = await c.get(url)
                results[name] = "ok" if r.status_code == 200 else "down"
        except Exception:
            results[name] = "unreachable"
    ok = all(v == "ok" for v in results.values())
    return {"status": "ok" if ok else "degraded", "version": ext.version, **results}


# ── Lifecycle Hooks ───────────────────────────────────────────────────────────

@ext.on_install
async def on_install(ctx):
    log.info(f"admin installed for user {ctx.user.imperal_id if ctx and hasattr(ctx, 'user') and ctx.user else 'system'}")
