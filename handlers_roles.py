"""Admin · Role & scope management handlers."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from app import chat, ActionResult, _gw_request, _resolve_role_by_name


# ─── Models ───────────────────────────────────────────────────────────── #

class CreateRoleParams(BaseModel):
    """Create a new role."""
    name: str                          = Field(description="Role name")
    display_name: str                  = Field(default="", description="Human-readable name")
    default_scopes: Optional[list[str]] = Field(default=None, description="Default scopes")


class DeleteRoleParams(BaseModel):
    """Delete a role by ID or name."""
    role_id: str   = Field(default="", description="Role ID")
    role_name: str = Field(default="", description="Role name (resolved automatically)")


class UpdateRoleParams(BaseModel):
    """Update a role's properties including limits."""
    role_id: str                        = Field(default="", description="Role ID")
    role_name: str                      = Field(default="", description="Role name (resolved to ID)")
    display_name: str                   = Field(default="", description="New display name")
    default_scopes: Optional[list[str]] = Field(default=None, description="New default scopes")
    cascade: bool                       = Field(default=False, description="Update all users with this role")
    monthly_action_limit: Optional[int] = Field(default=None, description="Monthly action limit (0=unlimited)")
    context_window: Optional[int]       = Field(default=None, description="History window in messages (5-200)")


class ListScopesParams(BaseModel):
    """Filter scopes."""
    resource: str = Field(default="", description="Filter by resource")
    source: str   = Field(default="", description="Filter by source")


class CreateScopeParams(BaseModel):
    """Create a scope in resource:action format."""
    resource: str     = Field(description="Resource name (e.g. 'billing')")
    action: str       = Field(description="Action name (e.g. 'read')")
    display_name: str = Field(default="", description="Human-readable name")
    description: str  = Field(default="", description="What this scope grants")


class DeleteScopeParams(BaseModel):
    """Delete a scope."""
    scope_name: str        = Field(default="", description="Scope in resource:action format")
    scope_id: Optional[int] = Field(default=None, description="Scope ID")


# ─── Role Handlers ────────────────────────────────────────────────────── #

@chat.function("list_roles", action_type="read", description="List all roles with default scopes.")
async def fn_list_roles(ctx) -> ActionResult:
    roles = await _gw_request("GET", "/v1/roles")
    if not isinstance(roles, list):
        return ActionResult.error("Failed to fetch roles")
    return ActionResult.success(data={"roles": roles, "total": len(roles)},
                                summary=f"{len(roles)} roles found")


@chat.function("create_role", action_type="write", event="role_created",
               description="Create a new role.")
async def fn_create_role(ctx, params: CreateRoleParams) -> ActionResult:
    result = await _gw_request("POST", "/v1/roles", {
        "name": params.name,
        "display_name": params.display_name or params.name,
        "default_scopes": params.default_scopes or [],
    })
    if isinstance(result, dict) and "error" in result:
        return ActionResult.error(result["error"])
    return ActionResult.success(data={"role": result},
                                summary=f"Role '{params.name}' created")


@chat.function("delete_role", action_type="destructive", event="role_deleted",
               description="Delete a role by ID or name.")
async def fn_delete_role(ctx, params: DeleteRoleParams) -> ActionResult:
    role_id = params.role_id
    if params.role_name and not role_id:
        roles = await _gw_request("GET", "/v1/roles")
        if isinstance(roles, list):
            match = next((r for r in roles if r.get("name") == params.role_name), None)
            if match:
                role_id = match["id"]
            else:
                return ActionResult.error(f"Role '{params.role_name}' not found")
    if not role_id:
        return ActionResult.error("role_id or role_name required")
    result = await _gw_request("DELETE", f"/v1/roles/{role_id}")
    if isinstance(result, dict) and "error" in result:
        return ActionResult.error(result["error"])
    return ActionResult.success(
        data={"deleted": True, "role_id": role_id},
        summary=f"Role {params.role_name or role_id} deleted",
    )


@chat.function("update_role", action_type="write", event="role_updated",
               description="Update role scopes, limits, or display name. Can cascade.")
async def fn_update_role(ctx, params: UpdateRoleParams) -> ActionResult:
    role_id = params.role_id
    if params.role_name and not role_id:
        role = await _resolve_role_by_name(params.role_name)
        if not role:
            return ActionResult.error(f"Role '{params.role_name}' not found")
        role_id = role["id"]
    if not role_id:
        return ActionResult.error("role_id or role_name required")

    data: dict = {}
    if params.display_name:
        data["display_name"] = params.display_name
    if params.default_scopes is not None:
        data["default_scopes"] = params.default_scopes
    if params.monthly_action_limit is not None:
        data["monthly_action_limit"] = params.monthly_action_limit
    if params.context_window is not None:
        data["context_window"] = params.context_window
    if not data:
        return ActionResult.error("Nothing to update.")

    cascade = str(params.cascade).lower()
    result = await _gw_request("PATCH", f"/v1/roles/{role_id}?cascade={cascade}", data)
    if isinstance(result, dict) and "error" in result:
        return ActionResult.error(result["error"])
    cascaded = result.get("cascaded_count", 0) if isinstance(result, dict) else 0
    return ActionResult.success(
        data={"role": result, "cascaded_count": cascaded},
        summary=f"Role updated" + (f", cascaded to {cascaded} users" if cascaded else ""),
    )


# ─── Scope Handlers ───────────────────────────────────────────────────── #

@chat.function("list_scopes", action_type="read", description="List all defined scopes.")
async def fn_list_scopes(ctx, params: ListScopesParams) -> ActionResult:
    parts = []
    if params.resource: parts.append(f"resource={params.resource}")
    if params.source:   parts.append(f"source={params.source}")
    qs = "?" + "&".join(parts) if parts else ""
    scopes = await _gw_request("GET", f"/v1/scopes{qs}")
    if not isinstance(scopes, list):
        return ActionResult.error("Failed to list scopes")
    return ActionResult.success(data={"scopes": scopes, "total": len(scopes)},
                                summary=f"{len(scopes)} scopes found")


@chat.function("create_scope", action_type="write", event="scope_created",
               description="Create a scope in resource:action format.")
async def fn_create_scope(ctx, params: CreateScopeParams) -> ActionResult:
    name = f"{params.resource}:{params.action}"
    data: dict = {"name": name, "resource": params.resource, "action": params.action}
    if params.display_name: data["display_name"] = params.display_name
    if params.description:  data["description"] = params.description
    result = await _gw_request("POST", "/v1/scopes", data)
    if isinstance(result, dict) and "error" in result:
        return ActionResult.error(result["error"])
    return ActionResult.success(data={"scope": result, "name": name},
                                summary=f"Scope '{name}' created")


@chat.function("delete_scope", action_type="destructive", event="scope_deleted",
               description="Delete a scope by name or ID.")
async def fn_delete_scope(ctx, params: DeleteScopeParams) -> ActionResult:
    if params.scope_id:
        result = await _gw_request("DELETE", f"/v1/scopes/{params.scope_id}")
    elif params.scope_name:
        scopes = await _gw_request("GET", "/v1/scopes?resource=")
        if not isinstance(scopes, list):
            return ActionResult.error("Failed to list scopes")
        match = next(
            (s for s in scopes
             if s.get("name") == params.scope_name or s.get("scope") == params.scope_name),
            None,
        )
        if not match:
            return ActionResult.error(f"Scope '{params.scope_name}' not found")
        result = await _gw_request("DELETE", f"/v1/scopes/{match.get('id')}")
    else:
        return ActionResult.error("scope_name or scope_id required")
    if isinstance(result, dict) and "error" in result:
        return ActionResult.error(result["error"])
    return ActionResult.success(data={"deleted": True},
                                summary=f"Scope '{params.scope_name or params.scope_id}' deleted")
