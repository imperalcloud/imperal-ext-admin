"""Admin · RBAC query handlers."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from app import chat, ActionResult, _gw_request, _resolve_user_by_email, _resolve_role_by_name


# ─── Models ───────────────────────────────────────────────────────────── #

class UserRefParams(BaseModel):
    """Identify a user by ID or email."""
    user_id: str = Field(default="", description="User imperal_id")
    email: str   = Field(default="", description="User email (resolved automatically)")


class CheckPermissionParams(BaseModel):
    """Check a specific permission."""
    user_id: str = Field(default="", description="User imperal_id")
    email: str   = Field(default="", description="User email")
    scope: str   = Field(description="Scope in resource:action format")


class CompareRolesParams(BaseModel):
    """Compare two roles."""
    role1: str = Field(description="First role name")
    role2: str = Field(description="Second role name")


class BulkAssignRoleParams(BaseModel):
    """Assign a role to multiple users."""
    role: str                    = Field(description="Target role name")
    user_ids: Optional[list[str]] = Field(default=None, description="Explicit list of imperal_ids")
    filter: Optional[dict]       = Field(default=None, description="Filter (e.g. {current_role: 'user'})")


class AuditLogParams(BaseModel):
    """Query audit log."""
    actor: str  = Field(default="", description="Filter by actor")
    target: str = Field(default="", description="Filter by target")
    action: str = Field(default="", description="Filter by action type")
    hours: int  = Field(default=24, description="How many hours back")


# ─── Internal ─────────────────────────────────────────────────────────── #

async def _resolve_ref(user_id: str, email: str) -> str | None:
    if user_id: return user_id
    if email:   return await _resolve_user_by_email(email)
    return None


# ─── Handlers ─────────────────────────────────────────────────────────── #

@chat.function("effective_scopes", action_type="read", description="Show all effective scopes for a user with sources.")
async def fn_effective_scopes(ctx, params: UserRefParams) -> ActionResult:
    ref = await _resolve_ref(params.user_id, params.email)
    if not ref:
        return ActionResult.error("user_id or email required" if not params.email else f"User '{params.email}' not found")
    result = await _gw_request("GET", f"/v1/scopes/effective/{ref}")
    if isinstance(result, dict) and "error" in result:
        return ActionResult.error(result["error"])
    scopes = result.get("scopes", result) if isinstance(result, dict) else result
    lines = [f"{s.get('scope', s.get('name', '?'))} [{s.get('source', '?')}]" if isinstance(s, dict) else str(s) for s in (scopes if isinstance(scopes, list) else [])]
    return ActionResult.success(data={"user_id": ref, "effective_scopes": result, "formatted": "\n".join(lines) or "No scopes"},
                                summary=f"Effective scopes for {ref}")


@chat.function("check_permission", action_type="read", description="Check if user has a specific scope. YES/NO.")
async def fn_check_permission(ctx, params: CheckPermissionParams) -> ActionResult:
    if not params.scope:
        return ActionResult.error("scope is required")
    ref = await _resolve_ref(params.user_id, params.email)
    if not ref:
        return ActionResult.error("user_id or email required" if not params.email else f"User '{params.email}' not found")
    result = await _gw_request("GET", f"/v1/scopes/effective/{ref}")
    if isinstance(result, dict) and "error" in result:
        return ActionResult.error(result["error"])
    scopes = result.get("scopes", result) if isinstance(result, dict) else result
    has_perm, source = False, "none"
    for s in (scopes if isinstance(scopes, list) else []):
        s_name = s.get("scope", s.get("name", "")) if isinstance(s, dict) else str(s)
        if s_name == params.scope or s_name == "*":
            has_perm, source = True, (s.get("source", "matched") if isinstance(s, dict) else "direct")
            break
    answer = "YES" if has_perm else "NO"
    return ActionResult.success(data={"user_id": ref, "scope": params.scope, "has_permission": has_perm, "answer": answer, "source": source},
                                summary=f"{answer} — {params.scope} (source: {source})")


@chat.function("compare_roles", action_type="read", description="Compare two roles — common and unique scopes.")
async def fn_compare_roles(ctx, params: CompareRolesParams) -> ActionResult:
    roles = await _gw_request("GET", "/v1/roles")
    if not isinstance(roles, list):
        return ActionResult.error("Failed to fetch roles")
    r1 = next((r for r in roles if r.get("name", "").lower() == params.role1.lower()), None)
    r2 = next((r for r in roles if r.get("name", "").lower() == params.role2.lower()), None)
    if not r1: return ActionResult.error(f"Role '{params.role1}' not found")
    if not r2: return ActionResult.error(f"Role '{params.role2}' not found")
    s1, s2 = set(r1.get("default_scopes", [])), set(r2.get("default_scopes", []))
    common, only1, only2 = sorted(s1 & s2), sorted(s1 - s2), sorted(s2 - s1)
    return ActionResult.success(
        data={"role1": {"name": r1["name"], "total": len(s1)}, "role2": {"name": r2["name"], "total": len(s2)},
              "common_scopes": common, "only_in_role1": only1, "only_in_role2": only2},
        summary=f"{r1['name']} vs {r2['name']}: {len(common)} common, {len(only1)}+{len(only2)} unique")


@chat.function("bulk_assign_role", action_type="write", event="roles_assigned", description="Assign a role to multiple users. Max 100.")
async def fn_bulk_assign_role(ctx, params: BulkAssignRoleParams) -> ActionResult:
    target_role = await _resolve_role_by_name(params.role)
    if not target_role:
        return ActionResult.error(f"Role '{params.role}' not found")
    raw = await _gw_request("GET", "/v1/users?include_inactive=true")
    users = raw.get("items", raw) if isinstance(raw, dict) else raw
    if not isinstance(users, list):
        return ActionResult.error("Failed to fetch users")
    targets = []
    if params.user_ids:
        targets = [u for u in users if (u.get("imperal_id") or u.get("id")) in params.user_ids]
    elif params.filter and isinstance(params.filter, dict):
        cr = params.filter.get("current_role", "")
        if cr: targets = [u for u in users if u.get("role", "").lower() == cr.lower() and u.get("is_active", True)]
    else:
        return ActionResult.error("Provide user_ids or filter with current_role")
    if not targets:   return ActionResult.error("No matching users")
    if len(targets) > 100: return ActionResult.error(f"Too many ({len(targets)}). Max 100.")
    success, errors = 0, []
    for u in targets:
        uid = u.get("imperal_id") or u.get("id")
        try:
            r = await _gw_request("PATCH", f"/v1/users/{uid}", {"role": target_role["name"]})
            if isinstance(r, dict) and "error" in r: errors.append({"user": u.get("email"), "error": r["error"]})
            else: success += 1
        except Exception as e:
            errors.append({"user": u.get("email"), "error": str(e)})
    return ActionResult.success(
        data={"target_role": target_role["name"], "total": len(targets), "success": success, "errors": errors[:10]},
        summary=f"Assigned '{params.role}' to {success}/{len(targets)}" + (f" ({len(errors)} errors)" if errors else ""))


@chat.function("audit_log", action_type="read", description="View audit log. Default last 24h, max 50 entries.")
async def fn_audit_log(ctx, params: AuditLogParams) -> ActionResult:
    parts = [f"hours={params.hours}"]
    if params.actor:  parts.append(f"actor={params.actor}")
    if params.target: parts.append(f"target={params.target}")
    if params.action: parts.append(f"action={params.action}")
    result = await _gw_request("GET", f"/v1/audit?{'&'.join(parts)}")
    if isinstance(result, dict) and "error" in result:
        return ActionResult.error(result["error"])
    entries = result if isinstance(result, list) else result.get("entries", result.get("data", []))
    if not isinstance(entries, list): entries = []
    display, total = entries[:50], len(entries)
    return ActionResult.success(
        data={"entries": display, "total": total, "showing": len(display), "truncated": total > 50, "hours": params.hours},
        summary=f"{len(display)} entries" + (f" (of {total})" if total > 50 else "") + f" from last {params.hours}h")
