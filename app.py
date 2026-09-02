"""
Admin v5.9.1 — shared state.

Platform administration via Auth Gateway + Registry APIs.
"""
import logging
import os

import httpx
from imperal_sdk._shared_http import shared_http

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
REDIS_URL = os.getenv("REDIS_URL", "")
TEMPORAL_HOST = os.getenv("TEMPORAL_HOST", "104.224.88.156")
TEMPORAL_PORT = int(os.getenv("TEMPORAL_PORT", "7233"))
TEMPORAL_NAMESPACE = os.getenv("TEMPORAL_NAMESPACE", "default")

# ── HTTP ──────────────────────────────────────────────────────────────────────


def _get_service_token() -> str:
    return (
        os.getenv("AUTH_SERVICE_TOKEN", "")
        or os.getenv("IMPERAL_SERVICE_TOKEN", "")
        or os.getenv("SERVICE_TOKEN", "")
    )


class _AuthServiceTokenProxy(str):
    def __str__(self):
        return _get_service_token()

    def __bool__(self):
        return bool(_get_service_token())


AUTH_SERVICE_TOKEN = _AuthServiceTokenProxy()


async def _gw_request(method, path, data=None, acting=None, ctx=None):
    token = _get_service_token()
    if not token and ctx:
        token = getattr(ctx, "_service_token", "") or (
            ctx._derive_service_token() if hasattr(ctx, "_derive_service_token") else ""
        )
    headers = {"X-Service-Token": token}
    if acting:
        headers["X-Acting-User"] = acting

    async with shared_http(timeout=10.0) as c:
        url = f"{AUTH_GW.rstrip('/')}/{path.lstrip('/')}"
        if method.upper() in ("POST", "PUT", "PATCH"):
            r = await getattr(c, method.lower())(url, json=data, headers=headers)
        elif method.upper() == "DELETE" and data is not None:
            r = await c.request("DELETE", url, json=data, headers=headers)
        else:
            r = await getattr(c, method.lower())(url, headers=headers)

    if r.status_code >= 400:
        body = (r.text or "").strip()
        try:
            payload = r.json()
            detail = payload.get("detail") or payload.get("error") or body[:300]
        except Exception:
            detail = body[:300] or "(empty body)"
        return {"error": f"HTTP {r.status_code}: {detail}"}
    if not r.content:
        return {}
    try:
        return r.json()
    except Exception as e:
        return {"error": f"non-JSON response from auth-gw (HTTP {r.status_code}): {(r.text or '')[:200]} :: {e}"}


def _verify_write_reflected(result, expected: dict) -> str | None:
    """Federal I-EXT-VERIFY-WRITE-REFLECTS-INTENT.

    After a mutating call (PATCH/POST), confirm the response echoes back the
    values we asked for. Catches replication-lag fabricated-success, silent
    server-side coercion, and split-brain residue (see galera incident
    2026-05-11: US slave SQL_thread stopped → reads returned stale snapshot
    while writes succeeded on EU master → Webbee narrated success on no-op).

    Returns a drift-description string if mismatch detected, None if reflected
    correctly. Callers convert to ActionResult.error.
    """
    if not isinstance(result, dict):
        return None
    for key, want in expected.items():
        if want is None:
            continue
        got = result.get(key)
        if got == want:
            continue
        if isinstance(want, list) and isinstance(got, list) and sorted(want) == sorted(got):
            continue
        if isinstance(want, dict) and isinstance(got, dict):
            if all(got.get(k) == v for k, v in want.items()):
                continue
        return (
            f"server did not reflect '{key}': requested {want!r}, "
            f"got {got!r} (possible replication lag or silent coercion)"
        )
    return None


async def _registry_get(path):
    async with shared_http(timeout=10) as c:
        return await c.get(f"{REGISTRY_URL}{path}", headers={"x-api-key": REGISTRY_KEY})


async def _registry_put(path, data):
    async with shared_http(timeout=10) as c:
        return await c.put(f"{REGISTRY_URL}{path}", json=data,
                           headers={"x-api-key": REGISTRY_KEY, "Content-Type": "application/json"})


async def _registry_patch(path, data):
    async with shared_http(timeout=10) as c:
        return await c.patch(f"{REGISTRY_URL}{path}", json=data,
                             headers={"x-api-key": REGISTRY_KEY, "Content-Type": "application/json"})


async def _admin_put(path: str, body: dict, acting: str = "", timeout: float = 5.0):
    headers = {"X-Service-Token": AUTH_SERVICE_TOKEN}
    if acting:
        headers["X-Acting-User"] = acting
    async with shared_http(timeout=timeout) as client:
        return await client.put(f"{AUTH_GW.rstrip('/')}{path}", json=body, headers=headers)


async def _admin_put_checked(path: str, body: dict, acting: str = "", timeout: float = 5.0,
                             forbidden_message: str = "admin role required") -> tuple[dict | None, str | None]:
    try:
        resp = await _admin_put(path, body, acting=acting, timeout=timeout)
    except Exception as e:
        return None, f"save HTTP error: {type(e).__name__}: {e}"
    if resp.status_code == 403:
        return None, forbidden_message
    if resp.status_code != 200:
        return None, f"save failed: status={resp.status_code} body={resp.text[:200]}"
    try:
        payload = resp.json()
    except Exception as e:
        return None, f"save failed: non-JSON response body={resp.text[:200]} :: {type(e).__name__}: {e}"
    drift = _verify_write_reflected(payload, body)
    if drift:
        return None, drift
    return payload, None

# ── Helpers ───────────────────────────────────────────────────────────────────


def _user_id(ctx) -> str:
    return ctx.user.imperal_id if hasattr(ctx, "user") and ctx.user else ""


def _tenant_id(ctx) -> str:
    if hasattr(ctx, "user") and ctx.user and hasattr(ctx.user, "tenant_id"):
        return ctx.user.tenant_id
    return "default"


def _acting(ctx) -> str:
    """The user performing a write, for the gateway's X-Acting-User audit trail.

    Was duplicated identically (6-line try/except body) in FIVE handler
    files (handlers_billing.py, handlers_billing_mode.py, handlers_payment.py,
    handlers_system_pricing.py, handlers_voice.py) plus panels_user_profile.py's
    own _panel_acting -- single source of truth now.
    """
    try:
        return str(getattr(getattr(ctx, "user", None), "imperal_id", "") or "")
    except Exception:
        return ""


def _aslist(r) -> list:
    """Normalize a gateway response that should be a list.

    Was duplicated identically in handlers_admin_reads.py and
    handlers_email.py -- single source of truth now.
    """
    if isinstance(r, list):
        return r
    if isinstance(r, dict) and "error" not in r:
        return r.get("items") or []
    return []


def _panel_acting(ctx) -> str:
    """Best-effort acting-user id for the gateway audit trail.

    Was duplicated verbatim in panels_billing_analytics.py and
    panels_credits.py (9 identical lines each) -- single source of truth
    now. panels_user_profile.py keeps its own slightly different variant
    on purpose (try/except around attribute access rather than a dict
    fallback), so it is left untouched here.
    """
    for attr in ("user_id", "imperal_id"):
        val = getattr(ctx, attr, "") or ""
        if val:
            return str(val)
    user = getattr(ctx, "user", None)
    if isinstance(user, dict):
        return str(user.get("imperal_id") or user.get("user_id") or "")
    return ""


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


async def _resolve_user_flexible(value: str) -> tuple[str | None, str | None]:
    """Resolve ANY user identifier the caller might reasonably type to a
    canonical `imp_u_*` imperal_id — never a hard reject on the first miss.

    Tries, in order:
    1. Already an `imp_u_*` id -> returned as-is (trusted shape).
    2. Contains `@` -> exact email match via `_resolve_user_by_email`.
    3. Anything else (partial id, display name, email fragment) -> pulls the
       full user list and matches by: exact/substring imperal_id, exact/
       substring display_name or email (case-insensitive). Ambiguous or
       zero matches return a clear, actionable error listing the candidates
       (or lack thereof) instead of silently guessing.

    Returns ``(imperal_id, None)`` on a single confident match, or
    ``(None, error_message)`` otherwise.
    """
    if not value:
        return None, "user identifier is empty"
    v = value.strip()
    if v.startswith("imp_u_"):
        return v, None
    if "@" in v:
        resolved = await _resolve_user_by_email(v)
        if resolved:
            return resolved, None
        return None, f"no user found for email {v!r}."

    raw = await _gw_request("GET", "/v1/users?include_inactive=true")
    users = raw.get("items", raw) if isinstance(raw, dict) else raw
    if not isinstance(users, list):
        return None, f"could not resolve {v!r}: user list unavailable"

    v_lower = v.lower()
    matches = []
    for u in users:
        if not isinstance(u, dict):
            continue
        uid = u.get("imperal_id") or u.get("id") or ""
        name = u.get("display_name") or u.get("full_name") or ""
        email = u.get("email") or ""
        if (v_lower == uid.lower() or v_lower == name.lower() or v_lower == email.lower()):
            return uid, None  # exact match on any field — take it immediately
        if v_lower in uid.lower() or v_lower in name.lower() or v_lower in email.lower():
            matches.append((uid, name, email))

    if len(matches) == 1:
        return matches[0][0], None
    if len(matches) > 1:
        listed = "; ".join(f"{uid} ({name or email})" for uid, name, email in matches[:8])
        return None, (
            f"{len(matches)} users match {v!r} — ambiguous. Candidates: {listed}. "
            f"Use the exact imp_u_* id from this list."
        )
    return None, (
        f"no user found matching {v!r} (checked imperal_id, name and email, "
        f"including partial matches). Double-check the value, or run "
        f"list_users to browse the full user list."
    )


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
    version="5.11.0",
    system=True,
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
    ext,
    "tool_admin_chat",
    description=(
        "Admin assistant — manage users, roles, extensions and system health. "
        "RBAC scopes, effective permissions, compare roles, bulk assign, audit log, "
        "extension access policies, deny/allow extensions"
    ),
    system_prompt=SYSTEM_PROMPT,
    max_rounds=10,
)

# Note: the prior `_build_system_prompt` monkey-patch that read
# `ctx.skeleton_data` to inject live admin stats has been removed.
# `ctx.skeleton_data` was removed in SDK v1.6.0 (federal I-SKELETON-LLM-ONLY:
# skeleton access is restricted to @ext.skeleton handlers). The intent
# classifier now reads the admin_stats skeleton section automatically on
# every chat turn — see skeleton.py for the producer.

# ── Health check ──────────────────────────────────────────────────────────────


@ext.health_check
async def health(ctx) -> dict:
    results = {}
    for name, url in [("auth_gateway", f"{AUTH_GW}/healthz"), ("registry", f"{REGISTRY_URL}/health")]:
        try:
            async with shared_http(timeout=3) as c:
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
