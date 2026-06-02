"""Admin · Extension & access policy handlers."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from app import (EmptyParams,
    chat, ActionResult, _gw_request, _registry_get, _registry_put, _registry_patch,
    _resolve_app_id, _resolve_user_by_email, _invalidate_extension_caches, _signal_session_refresh,
    _tenant_id,
)
from models_records import (
    AccessPolicyRecord, ExtensionConfigRecord, ExtensionUsersResponse, ExtensionsListResponse,
    ExtSettingsReceipt,
)


# ─── Models ───────────────────────────────────────────────────────────── #

class AppIdParams(BaseModel):
    """Target a specific extension."""
    app_id: str = Field(description="Exact app_id from ACTIVE EXTENSIONS list")


class UpdateExtConfigParams(BaseModel):
    """Update extension config."""
    app_id: str  = Field(description="Exact app_id")
    config: dict = Field(description="Config sections to update")


class UpdateSkeletonTtlParams(BaseModel):
    """Update skeleton refresh interval."""
    app_id: str       = Field(description="Exact app_id")
    ttl: int          = Field(default=60, description="Refresh interval in seconds")
    section_name: str = Field(default="", description="Specific section. Omit for all.")


class UserExtParams(BaseModel):
    """Identify a user for extension access."""
    user_id: str = Field(default="", description="User imperal_id")
    email: str   = Field(default="", description="User email")


class SetAccessPolicyParams(BaseModel):
    """Set extension access policy."""
    app_id: str                        = Field(description="Exact app_id")
    mode: str                          = Field(default="", description="public or restricted")
    required_scopes: Optional[list[str]] = Field(default=None, description="Scopes for restricted mode")
    denied_roles: Optional[list[str]]  = Field(default=None, description="Roles to deny")
    denied_users: Optional[list[str]]  = Field(default=None, description="User IDs to deny")


class DenyAllowParams(BaseModel):
    """Deny or allow access for a role/user."""
    app_id: str = Field(description="Exact app_id")
    role: str   = Field(default="", description="Role name")
    user: str   = Field(default="", description="User email or imperal_id")


# ─── Extension Management ─────────────────────────────────────────────── #

@chat.function("list_extensions", action_type="read", data_model=ExtensionsListResponse, description="List all active extensions.")
async def fn_list_extensions(ctx, params: EmptyParams) -> ActionResult:
    r = await _registry_get("/v1/apps?status=active")
    if r.status_code != 200:
        return ActionResult.error(f"Failed: HTTP {r.status_code}")
    apps = r.json()
    if not isinstance(apps, list):
        return ActionResult.error("Invalid response from registry")
    # SDL entity-list (NO legacy {extensions} wrapper): each app is a canonical
    # SDL entity (id=app_id, title=display_name/name, kind="extension"); registry
    # fields kept verbatim. Conforms to sdl.EntityList[ExtensionRecord].
    items = []
    for _a in apps:
        if not isinstance(_a, dict):
            continue
        _it = dict(_a)
        _it["id"] = _a.get("app_id") or _a.get("id") or ""
        _it.setdefault("title", _a.get("display_name") or _a.get("name") or _a.get("app_id") or "")
        _it.setdefault("kind", "extension")
        items.append(_it)
    return ActionResult.success(data={"items": items, "total": len(items)}, summary=f"{len(items)} active extensions")


@chat.function("get_extension_config", action_type="read", data_model=ExtensionConfigRecord, description="Get full extension config.")
async def fn_get_extension_config(ctx, params: AppIdParams) -> ActionResult:
    aid = await _resolve_app_id(params.app_id)
    tid = _tenant_id(ctx)
    r = await _registry_get(f"/v1/apps/{aid}/settings")
    if r.status_code != 200:
        return ActionResult.error(f"Failed for '{aid}': HTTP {r.status_code}")
    return ActionResult.success(data={"app_id": aid, "config": r.json()}, summary=f"Config for {aid}")


@chat.function("update_extension_config", action_type="write", event="extension_configured", data_model=ExtSettingsReceipt, description="Update extension config.")
async def fn_update_extension_config(ctx, params: UpdateExtConfigParams) -> ActionResult:
    aid = await _resolve_app_id(params.app_id)
    tid = _tenant_id(ctx)
    if not params.config:
        return ActionResult.error("No config provided")
    r = await _registry_put(f"/v1/apps/{aid}/settings", params.config)
    if r.status_code == 200:
        return ActionResult.success(data={"app_id": aid, "updated": True}, summary=f"Config updated for {aid}", refresh_panels=["tools"])
    return ActionResult.error(f"Failed: HTTP {r.status_code}")


@chat.function("update_skeleton_ttl", action_type="write", event="skeleton_updated", data_model=ExtSettingsReceipt, description="Update skeleton refresh TTL.")
async def fn_update_skeleton_ttl(ctx, params: UpdateSkeletonTtlParams) -> ActionResult:
    aid = await _resolve_app_id(params.app_id)
    tid = _tenant_id(ctx)
    payload = {"skeleton": {"sections": [{"section_name": params.section_name, "ttl": params.ttl}]}} if params.section_name else {"skeleton": {"ttl": params.ttl}}
    r = await _registry_put(f"/v1/apps/{aid}/settings", payload)
    if r.status_code == 200:
        return ActionResult.success(data={"app_id": aid, "ttl": params.ttl}, summary=f"Skeleton TTL {params.ttl}s for {aid}", refresh_panels=["tools"])
    return ActionResult.error(f"Failed: HTTP {r.status_code}")


@chat.function("suspend_extension", action_type="destructive", event="extension_suspended", data_model=ExtSettingsReceipt, description="Suspend an extension.")
async def fn_suspend_extension(ctx, params: AppIdParams) -> ActionResult:
    aid = await _resolve_app_id(params.app_id, include_all=True)
    r = await _registry_patch(f"/v1/apps/{aid}", {"status": "suspended"})
    if r.status_code != 200:
        return ActionResult.error(f"Failed: HTTP {r.status_code}")
    v = await _registry_get(f"/v1/apps/{aid}")
    if v.status_code == 200 and v.json().get("status") == "suspended":
        await _invalidate_extension_caches()
        return ActionResult.success(data={"app_id": aid, "status": "suspended", "verified": True}, summary=f"{aid} suspended", refresh_panels=["tools"])
    return ActionResult.success(data={"app_id": aid}, summary=f"{aid} suspend sent (unverified)")


@chat.function("activate_extension", action_type="write", event="extension_activated", data_model=ExtSettingsReceipt, description="Activate a suspended extension.")
async def fn_activate_extension(ctx, params: AppIdParams) -> ActionResult:
    aid = await _resolve_app_id(params.app_id, include_all=True)
    r = await _registry_get(f"/v1/apps/{aid}")
    if r.status_code == 404:
        return ActionResult.error(f"'{aid}' not found. Must be registered first.")
    cur = r.json().get("status", "unknown")
    if cur == "active":
        return ActionResult.success(data={"app_id": aid, "status": "active"}, summary=f"{aid} already active", refresh_panels=["tools"])
    if cur == "deleted":
        return ActionResult.error(f"'{aid}' was deleted. Must be re-registered.")
    r = await _registry_patch(f"/v1/apps/{aid}", {"status": "active"})
    if r.status_code != 200:
        return ActionResult.error(f"Failed: HTTP {r.status_code}")
    v = await _registry_get(f"/v1/apps/{aid}")
    if v.status_code == 200 and v.json().get("status") == "active":
        await _invalidate_extension_caches()
        return ActionResult.success(data={"app_id": aid, "status": "active", "previous": cur}, summary=f"{aid} activated (was {cur})")
    return ActionResult.success(data={"app_id": aid}, summary=f"{aid} activate sent (unverified)")


# ─── Access Policy Handlers ───────────────────────────────────────────── #

@chat.function(
    "list_user_extensions",
    action_type="read",
    data_model=ExtensionsListResponse,
    description=(
        "List the calling user's installed extensions when called with no "
        "user_id/email (self-service mode — used by 'what extensions do I "
        "have' chat intent); list another user's extensions when user_id "
        "or email is specified (admin mode — requires admin scope at the "
        "gateway). B-3 self-service path added 2026-05-11."
    ),
)
async def fn_list_user_extensions(ctx, params: UserExtParams) -> ActionResult:
    # B-3 (2026-05-11): when both user_id and email are empty, default to
    # the calling user — this is the self-service path that the
    # hub_routing.txt "extensions/apps" intent class targets. Closes the
    # anti-fab fallback class where 'какие у меня расширения?' used to
    # route to conversational and hit the now-deleted hardcoded apps list.
    ref = params.user_id or (
        await _resolve_user_by_email(params.email) if params.email else None
    )
    if not ref:
        # No explicit target — fall back to the caller's own imperal_id.
        # ctx.user.imperal_id is kernel-authoritative; cannot be spoofed.
        ref = getattr(ctx.user, "imperal_id", "") or ""
    if not ref:
        return ActionResult.error(
            "user_id or email required" if not params.email else f"User '{params.email}' not found"
        )
    result = await _gw_request("GET", f"/v1/users/{ref}/extensions")
    if isinstance(result, dict) and "error" in result:
        return ActionResult.error(result["error"])
    exts = result if isinstance(result, list) else result.get("extensions", [])
    # SDL entity-list (NO legacy {extensions} wrapper): canonical extension
    # entities; the target user_id stays in the summary string. Conforms to
    # sdl.EntityList[ExtensionRecord].
    items = []
    for _e in exts:
        if not isinstance(_e, dict):
            continue
        _it = dict(_e)
        _it["id"] = _e.get("app_id") or _e.get("id") or ""
        _it.setdefault("title", _e.get("display_name") or _e.get("name") or _e.get("app_id") or "")
        _it.setdefault("kind", "extension")
        items.append(_it)
    return ActionResult.success(data={"items": items, "total": len(items)}, summary=f"{len(items)} extensions for {ref}")


@chat.function("set_access_policy", action_type="write", event="access_policy_set", data_model=ExtSettingsReceipt, description="Set extension access policy.")
async def fn_set_access_policy(ctx, params: SetAccessPolicyParams) -> ActionResult:
    aid = await _resolve_app_id(params.app_id)
    tid = _tenant_id(ctx)
    policy: dict = {}
    if params.mode: policy["mode"] = params.mode
    if params.required_scopes is not None: policy["required_scopes"] = params.required_scopes
    exceptions: dict = {}
    if params.denied_roles is not None: exceptions["denied_roles"] = params.denied_roles
    if params.denied_users is not None: exceptions["denied_users"] = params.denied_users
    if exceptions: policy["exceptions"] = exceptions
    if not policy:
        return ActionResult.success(data={"app_id": aid}, summary="No changes needed", refresh_panels=["tools"])
    cur = await _gw_request("GET", f"/v1/internal/config/app/{aid}?tenant_id={tid}&app_id={aid}")
    cur_policy = (cur or {}).get("config", {}).get("access_policy", {"mode": "public"})
    merged = {**cur_policy, **policy}
    if "exceptions" in policy:
        merged["exceptions"] = {**cur_policy.get("exceptions", {}), **policy["exceptions"]}
    await _gw_request("PUT", f"/v1/internal/config/app/{aid}?tenant_id={tid}&app_id={aid}", {"config": {"access_policy": merged}})
    return ActionResult.success(data={"app_id": aid, "policy": merged}, summary=f"Policy for {aid}: mode={merged.get('mode', '?')}")


@chat.function("get_access_policy", action_type="read", data_model=AccessPolicyRecord, description="Show access policy with per-role resolution.")
async def fn_get_access_policy(ctx, params: AppIdParams) -> ActionResult:
    aid = await _resolve_app_id(params.app_id)
    tid = _tenant_id(ctx)
    cfg = await _gw_request("GET", f"/v1/internal/config/app/{aid}?tenant_id={tid}&app_id={aid}")
    policy = (cfg or {}).get("config", {}).get("access_policy", {"mode": "public"})
    roles = await _gw_request("GET", "/v1/roles")
    resolution = []
    if isinstance(roles, list):
        for role in roles:
            rs = role.get("default_scopes") or []
            req = policy.get("required_scopes", [])
            denied = policy.get("exceptions", {}).get("denied_roles", [])
            if role["name"] in denied:
                st = "DENIED (role exception)"
            elif req:
                st = "PASS" if all(r in rs or "*" in rs or f"{r.split(':')[0]}:*" in rs for r in req) else f"DENIED (missing {req})"
            elif policy.get("mode") == "restricted":
                st = "DENIED (restricted)"
            else:
                st = "PASS"
            resolution.append({"role": role["name"], "status": st})
    return ActionResult.success(data={"app_id": aid, "policy": policy, "role_resolution": resolution},
                                summary=f"Policy for {aid}: mode={policy.get('mode', 'public')}")


@chat.function("list_extension_users", action_type="read", data_model=ExtensionUsersResponse, description="List users who can access an extension.")
async def fn_list_extension_users(ctx, params: AppIdParams) -> ActionResult:
    aid = await _resolve_app_id(params.app_id, include_all=True)
    result = await _gw_request("GET", f"/v1/extensions/{aid}/users")
    if isinstance(result, dict) and "error" in result:
        return ActionResult.error(result["error"])
    users = result if isinstance(result, list) else result.get("users", [])
    granted = sum(1 for u in users if u.get("access") == "granted")
    denied = sum(1 for u in users if u.get("access") == "denied")
    # SDL entity-list (NO legacy {users,app_id,granted,denied} wrapper): each is a
    # canonical SDL user entity (id=imperal_id, title=display name, kind="user");
    # the gateway "access" (granted/denied) marker is kept verbatim per item but
    # the COUNTS and target app_id stay in the summary string (per the
    # ExtensionUsersResponse contract). Conforms to sdl.EntityList[UserRecord].
    items = []
    for _u in users:
        if not isinstance(_u, dict):
            continue
        _it = dict(_u)
        _it["id"] = _u.get("imperal_id") or _u.get("id") or ""
        _it.setdefault(
            "title",
            _u.get("display_name") or _u.get("full_name")
            or _u.get("email") or _u.get("imperal_id") or "",
        )
        _it.setdefault("kind", "user")
        items.append(_it)
    return ActionResult.success(data={"items": items, "total": len(items)},
                                summary=f"{granted} granted, {denied} denied for {aid}")


@chat.function("deny_extension", action_type="destructive", event="extension_denied", data_model=ExtSettingsReceipt, description="Add role/user to denied list.")
async def fn_deny_extension(ctx, params: DenyAllowParams) -> ActionResult:
    if not params.role and not params.user:
        return ActionResult.error("Provide role or user to deny")
    aid = await _resolve_app_id(params.app_id)
    tid = _tenant_id(ctx)
    cfg = await _gw_request("GET", f"/v1/internal/config/app/{aid}?tenant_id={tid}&app_id={aid}")
    policy = (cfg or {}).get("config", {}).get("access_policy", {"mode": "public", "exceptions": {"denied_roles": [], "denied_users": []}})
    exc = policy.get("exceptions", {"denied_roles": [], "denied_users": []})
    added, uid = [], params.user
    if params.role:
        dr = exc.get("denied_roles", [])
        if params.role in dr: return ActionResult.error(f"Role '{params.role}' already denied")
        dr.append(params.role); exc["denied_roles"] = dr; added.append(f"role '{params.role}'")
    if params.user:
        if "@" in str(params.user):
            uid = await _resolve_user_by_email(params.user)
            if not uid: return ActionResult.error(f"User '{params.user}' not found")
        du = exc.get("denied_users", [])
        if uid in du: return ActionResult.error(f"User already denied")
        du.append(uid); exc["denied_users"] = du; added.append(f"user '{uid}'")
    policy["exceptions"] = exc
    await _gw_request("PUT", f"/v1/internal/config/app/{aid}?tenant_id={tid}&app_id={aid}", {"config": {"access_policy": policy}})
    await _invalidate_extension_caches(user_id=uid if params.user else None)
    return ActionResult.success(data={"app_id": aid, "denied": added}, summary=f"Denied {', '.join(added)} from {aid}", refresh_panels=["tools"])


@chat.function("allow_extension", action_type="write", event="extension_allowed", data_model=ExtSettingsReceipt, description="Remove role/user from denied list.")
async def fn_allow_extension(ctx, params: DenyAllowParams) -> ActionResult:
    if not params.role and not params.user:
        return ActionResult.error("Provide role or user to allow")
    aid = await _resolve_app_id(params.app_id)
    tid = _tenant_id(ctx)
    cfg = await _gw_request("GET", f"/v1/internal/config/app/{aid}?tenant_id={tid}&app_id={aid}")
    policy = (cfg or {}).get("config", {}).get("access_policy", {"mode": "public", "exceptions": {"denied_roles": [], "denied_users": []}})
    exc = policy.get("exceptions", {"denied_roles": [], "denied_users": []})
    removed, uid = [], params.user
    if params.role:
        dr = exc.get("denied_roles", [])
        if params.role not in dr: return ActionResult.error(f"Role '{params.role}' is not denied")
        dr.remove(params.role); exc["denied_roles"] = dr; removed.append(f"role '{params.role}'")
    if params.user:
        if "@" in str(params.user):
            uid = await _resolve_user_by_email(params.user)
            if not uid: return ActionResult.error(f"User '{params.user}' not found")
        du = exc.get("denied_users", [])
        if uid not in du: return ActionResult.error(f"User is not denied")
        du.remove(uid); exc["denied_users"] = du; removed.append(f"user '{uid}'")
    policy["exceptions"] = exc
    await _gw_request("PUT", f"/v1/internal/config/app/{aid}?tenant_id={tid}&app_id={aid}", {"config": {"access_policy": policy}})
    await _invalidate_extension_caches(user_id=uid if params.user else None)
    if uid and params.user: await _signal_session_refresh(uid)
    return ActionResult.success(data={"app_id": aid, "removed": removed}, summary=f"Allowed {', '.join(removed)} for {aid}", refresh_panels=["tools"])
