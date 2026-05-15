"""Admin · User management handlers."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from app import chat, ActionResult, _gw_request, _verify_write_reflected, EmptyParams


# ─── Models ───────────────────────────────────────────────────────────── #

class CreateUserParams(BaseModel):
    """Create a new platform user."""
    email: str    = Field(description="User email")
    password: str = Field(description="User password")
    role: str     = Field(default="user", description="Role name")


class UpdateUserParams(BaseModel):
    """Update user properties."""
    user_id: str                    = Field(description="imperal_id")
    role: str                       = Field(default="", description="New role")
    is_active: Optional[bool]       = Field(default=None, description="Active status")
    scopes: Optional[list[str]]     = Field(default=None, description="Custom scopes")
    attributes: Optional[dict]      = Field(default=None, description="User attributes")


class UserIdParams(BaseModel):
    """Target a specific user."""
    user_id: str = Field(description="imperal_id")


class UpdateUserLimitsParams(BaseModel):
    """Update individual limit overrides for a user."""
    user_id: str = Field(description="imperal_id")
    monthly_action_limit: Optional[str] = Field(default=None, description="Monthly actions (empty = inherit)")
    max_concurrent_tasks: Optional[str] = Field(default=None, description="Concurrent tasks (empty = inherit)")
    context_window: Optional[str]       = Field(default=None, description="History window (empty = inherit)")


class SetUserAttributeParams(BaseModel):
    """Set a single attribute key-value on a user."""
    user_id: str   = Field(description="imperal_id")
    attr_key: str  = Field(description="Attribute key")
    attr_value: str = Field(default="", description="Attribute value")


class RemoveUserAttributeParams(BaseModel):
    """Remove a single attribute key from a user."""
    user_id: str  = Field(description="imperal_id")
    attr_key: str = Field(description="Attribute key to remove")


# ─── Handlers ─────────────────────────────────────────────────────────── #

@chat.function("list_users", action_type="read",
               description="List all users with roles, scopes, status.")
async def fn_list_users(ctx, params: EmptyParams) -> ActionResult:
    raw = await _gw_request(ctx, "GET", "/v1/users?include_inactive=true")
    users = raw.get("items", raw) if isinstance(raw, dict) else raw
    if not isinstance(users, list):
        return ActionResult.error("Failed to fetch users")
    return ActionResult.success(
        data={"users": users, "total": len(users)},
        summary=f"{len(users)} users found",
    )


@chat.function("create_user", action_type="write", chain_callable=True, effects=["user.write"], event="user_created",
               description="Create a new user with email, password, and role.")
async def fn_create_user(ctx, params: CreateUserParams) -> ActionResult:
    result = await _gw_request(ctx, "POST", "/v1/users", {
        "email": params.email, "password": params.password, "role": params.role,
    })
    if isinstance(result, dict) and "error" in result:
        return ActionResult.error(result["error"])
    drift = _verify_write_reflected(result, {"email": params.email, "role": params.role})
    if drift:
        return ActionResult.error(f"User creation did not reflect — {drift}")
    return ActionResult.success(
        data={"user": result},
        summary=f"User {params.email} created with role {params.role}",
    refresh_panels=["tools"],
    )


@chat.function("update_user", action_type="write", chain_callable=True, effects=["user.write"], event="user_updated",
               description="Update user role, scopes, attributes, or status.")
async def fn_update_user(ctx, params: UpdateUserParams) -> ActionResult:
    data: dict = {}
    if params.role:                  data["role"] = params.role
    if params.is_active is not None: data["is_active"] = params.is_active
    if params.scopes is not None:    data["scopes"] = params.scopes
    if params.attributes is not None: data["attributes"] = params.attributes
    result = await _gw_request(ctx, "PATCH", f"/v1/users/{params.user_id}", data)
    if isinstance(result, dict) and "error" in result:
        return ActionResult.error(result["error"])
    drift = _verify_write_reflected(result, data)
    if drift:
        return ActionResult.error(f"Update did not take effect — {drift}")
    return ActionResult.success(
        data={"user": result},
        summary=f"User {params.user_id} updated",
    refresh_panels=["tools"],
    )


@chat.function("deactivate_user", action_type="destructive", chain_callable=True, effects=["user.delete"], event="user_deactivated",
               description="Deactivate user (can reactivate later).")
async def fn_deactivate_user(ctx, params: UserIdParams) -> ActionResult:
    result = await _gw_request(ctx, "DELETE", f"/v1/users/{params.user_id}")
    if isinstance(result, dict) and "error" in result:
        return ActionResult.error(result["error"])
    return ActionResult.success(
        data={"deactivated": result},
        summary=f"User {params.user_id} deactivated",
    )


@chat.function("hard_delete_user", action_type="destructive", chain_callable=True, effects=["user.delete"], event="user_deleted",
               description="PERMANENT delete. Cannot be undone.")
async def fn_hard_delete_user(ctx, params: UserIdParams) -> ActionResult:
    result = await _gw_request(ctx, "DELETE", f"/v1/users/{params.user_id}?permanent=true")
    if isinstance(result, dict) and "error" in result:
        return ActionResult.error(result["error"])
    return ActionResult.success(
        data={"deleted": result},
        summary=f"User {params.user_id} permanently deleted",
    refresh_panels=["tools"],
    )


# ─── Limits ───────────────────────────────────────────────────────────── #

@chat.function("update_user_limits", action_type="write", chain_callable=True, effects=["user.write"], event="user_updated",
               description="Update individual limit overrides for a user.")
async def fn_update_user_limits(ctx, params: UpdateUserLimitsParams) -> ActionResult:
    # Fetch current user to merge attributes
    user = await _gw_request(ctx, "GET", f"/v1/users/{params.user_id}")
    if isinstance(user, dict) and "error" in user:
        return ActionResult.error(user["error"])
    existing = (user.get("attributes") or {}) if isinstance(user, dict) else {}

    updates = {}
    for field, attr_key in [
        (params.monthly_action_limit, "monthly_action_limit"),
        (params.max_concurrent_tasks, "max_concurrent_tasks"),
        (params.context_window, "context_window"),
    ]:
        if field is not None and field.strip():
            try:
                updates[attr_key] = int(field)
            except ValueError:
                pass
        elif field is not None and not field.strip():
            # Empty string = clear override (inherit from role)
            existing.pop(attr_key, None)

    existing.update(updates)
    result = await _gw_request(ctx, "PATCH", f"/v1/users/{params.user_id}",
                               {"attributes": existing})
    if isinstance(result, dict) and "error" in result:
        return ActionResult.error(result["error"])
    return ActionResult.success(
        data={"user_id": params.user_id, "limits": updates},
        summary=f"Limits updated for {params.user_id}",
    refresh_panels=["tools"],
    )


# ─── Attributes (ABAC) ───────────────────────────────────────────────── #

@chat.function("set_user_attribute", action_type="write", chain_callable=True, effects=["user.write"], event="user_updated",
               description="Set a single attribute key-value on a user.")
async def fn_set_user_attribute(ctx, params: SetUserAttributeParams) -> ActionResult:
    if not params.attr_key.strip():
        return ActionResult.error("Attribute key is required")
    user = await _gw_request(ctx, "GET", f"/v1/users/{params.user_id}")
    if isinstance(user, dict) and "error" in user:
        return ActionResult.error(user["error"])
    attrs = (user.get("attributes") or {}) if isinstance(user, dict) else {}
    attrs[params.attr_key.strip()] = params.attr_value
    result = await _gw_request(ctx, "PATCH", f"/v1/users/{params.user_id}",
                               {"attributes": attrs})
    if isinstance(result, dict) and "error" in result:
        return ActionResult.error(result["error"])
    return ActionResult.success(
        data={"user_id": params.user_id, "key": params.attr_key, "value": params.attr_value},
        summary=f"Attribute '{params.attr_key}' set on {params.user_id}",
    refresh_panels=["tools"],
    )


@chat.function("remove_user_attribute", action_type="write", chain_callable=True, effects=["user.write"], event="user_updated",
               description="Remove an attribute key from a user.")
async def fn_remove_user_attribute(ctx, params: RemoveUserAttributeParams) -> ActionResult:
    user = await _gw_request(ctx, "GET", f"/v1/users/{params.user_id}")
    if isinstance(user, dict) and "error" in user:
        return ActionResult.error(user["error"])
    attrs = (user.get("attributes") or {}) if isinstance(user, dict) else {}
    removed = attrs.pop(params.attr_key, None)
    if removed is None:
        return ActionResult.error(f"Attribute '{params.attr_key}' not found")
    result = await _gw_request(ctx, "PATCH", f"/v1/users/{params.user_id}",
                               {"attributes": attrs})
    if isinstance(result, dict) and "error" in result:
        return ActionResult.error(result["error"])
    return ActionResult.success(
        data={"user_id": params.user_id, "removed": params.attr_key},
        summary=f"Attribute '{params.attr_key}' removed from {params.user_id}",
    refresh_panels=["tools"],
    )
