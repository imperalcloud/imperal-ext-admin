"""Admin · User management handlers."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from app import (
    chat, ActionResult, _gw_request, _verify_write_reflected, EmptyParams,
    _resolve_user_by_email, _invalidate_extension_caches, _signal_session_refresh,
)
from models_records import (
    UserListResponse,
    UserRecord,
)


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


class ResetConvParams(BaseModel):
    """Reset (clear) a specific user's conversation. A target is REQUIRED — pass
    user_id or email; the tool NEVER silently defaults to the caller (for a
    genuine self-reset the kernel passes the caller's own imperal_id)."""
    user_id: str = Field(default="", description="imperal_id of the user to reset (admin only for another user)")
    email: str   = Field(default="", description="email of the user to reset (admin only for another user)")


# ─── Handlers ─────────────────────────────────────────────────────────── #

@chat.function("list_users", action_type="read",
               data_model=UserListResponse,
               description="List all users with roles, scopes, status.")
async def fn_list_users(ctx, params: EmptyParams) -> ActionResult:
    raw = await _gw_request("GET", "/v1/users?include_inactive=true")
    users = raw.get("items", raw) if isinstance(raw, dict) else raw
    if not isinstance(users, list):
        return ActionResult.error("Failed to fetch users")
    # SDL entity-list (NO legacy {users} wrapper): each user is a canonical SDL
    # entity (id=imperal_id, title=display name, kind="user"); gateway fields are
    # kept verbatim for rendering. The kernel reads data["items"] + title to
    # resolve a user SET ("обоим ignat") and fan out by id. Data conforms to the
    # sdl.EntityList[UserRecord] contract (data_model carries x-sdl="entity-list").
    items = []
    for _u in users:
        if not isinstance(_u, dict):
            continue
        _it = dict(_u)
        # Canonical entity id = imperal_id (the id reset_conversation / every
        # admin user tool keys on — mirrors _resolve_user_by_email). OVERWRITE,
        # not setdefault: the gateway dict already carries a separate "id" that
        # is NOT the imperal_id, and the reset endpoint 404s on it.
        _it["id"] = _u.get("imperal_id") or _u.get("id") or ""
        _it.setdefault(
            "title",
            _u.get("display_name") or _u.get("full_name")
            or _u.get("email") or _u.get("imperal_id") or "",
        )
        _it.setdefault("kind", "user")
        items.append(_it)
    return ActionResult.success(
        data={"items": items, "total": len(items)},
        summary=f"{len(items)} users found",
    )


@chat.function("create_user", action_type="write", event="user_created",
               data_model=UserRecord,
               description="Create a new user with email, password, and role.")
async def fn_create_user(ctx, params: CreateUserParams) -> ActionResult:
    result = await _gw_request("POST", "/v1/users", {
        "email": params.email, "password": params.password, "role": params.role,
    })
    if isinstance(result, dict) and "error" in result:
        return ActionResult.error(result["error"])
    drift = _verify_write_reflected(result, {"email": params.email, "role": params.role})
    if drift:
        return ActionResult.error(f"User creation did not reflect — {drift}")
    # SDL: return the created user as a canonical UserRecord entity (id=imperal_id,
    # title=display name, kind="user"); the _sdl_canon validator fills core fields
    # from the gateway dict. NO legacy {"user": ...} wrapper.
    return ActionResult.success(
        data=result,
        summary=f"User {params.email} created with role {params.role}",
    refresh_panels=["tools"],
    )


@chat.function("update_user", action_type="write", event="user_updated",
               data_model=UserRecord,
               description="Update user role, scopes, attributes, or status.")
async def fn_update_user(ctx, params: UpdateUserParams) -> ActionResult:
    data: dict = {}
    if params.role:                  data["role"] = params.role
    if params.is_active is not None: data["is_active"] = params.is_active
    if params.scopes is not None:    data["scopes"] = params.scopes
    if params.attributes is not None: data["attributes"] = params.attributes
    result = await _gw_request("PATCH", f"/v1/users/{params.user_id}", data)
    if isinstance(result, dict) and "error" in result:
        return ActionResult.error(result["error"])
    drift = _verify_write_reflected(result, data)
    if drift:
        return ActionResult.error(f"Update did not take effect — {drift}")
    # Role/scope changes alter extension visibility — flush the shared policy
    # caches and nudge the live session, mirroring deny/allow_extension (the
    # missing invalidation kept stale visibility after role moves).
    if params.role or params.scopes is not None:
        await _invalidate_extension_caches(user_id=params.user_id)
        await _signal_session_refresh(params.user_id)
    # SDL: return the updated user as a canonical UserRecord entity (the gateway
    # PATCH echoes the full user dict; _sdl_canon fills id/title/kind). NO legacy
    # {"user": ...} wrapper.
    return ActionResult.success(
        data=result,
        summary=f"User {params.user_id} updated",
    refresh_panels=["tools"],
    )


@chat.function("deactivate_user", action_type="destructive", event="user_deactivated",
               data_model=UserRecord,
               description="Deactivate user (can reactivate later).")
async def fn_deactivate_user(ctx, params: UserIdParams) -> ActionResult:
    result = await _gw_request("DELETE", f"/v1/users/{params.user_id}")
    if isinstance(result, dict) and "error" in result:
        return ActionResult.error(result["error"])
    # SDL: return the (now-inactive) user as a canonical UserRecord entity. The
    # gateway may echo the user dict or an empty body — anchor the canonical id on
    # the targeted imperal_id so the entity always resolves. NO {"deactivated":...}
    # wrapper; the "deactivated" fact lives in the summary for ICNLI narration.
    data = dict(result) if isinstance(result, dict) else {}
    data.setdefault("imperal_id", params.user_id)
    data.setdefault("is_active", False)
    return ActionResult.success(
        data=data,
        summary=f"User {params.user_id} deactivated",
    )


@chat.function("hard_delete_user", action_type="destructive", event="user_deleted",
               data_model=UserRecord,
               description="PERMANENT delete. Cannot be undone.")
async def fn_hard_delete_user(ctx, params: UserIdParams) -> ActionResult:
    result = await _gw_request("DELETE", f"/v1/users/{params.user_id}?permanent=true")
    if isinstance(result, dict) and "error" in result:
        return ActionResult.error(result["error"])
    # SDL: return the deleted user as a canonical UserRecord entity keyed on the
    # targeted imperal_id (the gateway returns an empty/confirmation body on a
    # permanent delete). NO {"deleted": ...} wrapper; the permanence fact lives in
    # the summary for ICNLI narration.
    data = dict(result) if isinstance(result, dict) else {}
    data.setdefault("imperal_id", params.user_id)
    return ActionResult.success(
        data=data,
        summary=f"User {params.user_id} permanently deleted",
    refresh_panels=["tools"],
    )


@chat.function("reset_conversation", action_type="destructive", event="user_conversation_reset",
               description=(
                   "Reset (clear) a user's chat history and conversational state — history, "
                   "session memory, skeleton caches — and restart their session. Money, usage, "
                   "billing, and installed apps are PRESERVED. With NO user_id/email this resets "
                   "the CALLER's own conversation (available to any user). With a user_id or email "
                   "it resets THAT user (ADMIN only). Use when a user says 'clear my history', "
                   "'start over', 'reset my chat', or an admin asks to reset a specific user. "
                   "Confirmation is required before it runs."),
               data_model=UserRecord)
async def fn_reset_conversation(ctx, params: ResetConvParams) -> ActionResult:
    self_uid = getattr(ctx.user, "imperal_id", "") or ""
    target = (params.user_id or "").strip()
    if not target and params.email:
        target = await _resolve_user_by_email(params.email) or ""
        if not target:
            return ActionResult.error(f"User '{params.email}' not found.")
    # SAFETY (2026-06-02): never silently default an unresolved target to the
    # caller — a phantom/lost target once turned "clear THESE users' history"
    # into "clear MY history". A target is REQUIRED; the kernel passes the
    # caller's own id explicitly for a genuine self-reset.
    if not target:
        return ActionResult.error(
            "Specify which user to reset — provide a user_id or email."
        )

    # Cross-user reset is admin-only; self-reset is allowed for everyone.
    if target != self_uid and getattr(ctx.user, "role", "") != "admin":
        return ActionResult.error("Only admins can reset another user's conversation.")

    result = await _gw_request("POST", f"/v1/users/{target}/reset-conversation")
    if isinstance(result, dict) and "error" in result:
        return ActionResult.error(result["error"])

    whose = "your" if target == self_uid else f"{target}'s"
    summary = (
        f"Reset {whose} conversation: {result.get('redis_keys_deleted', 0)} key(s) cleared, "
        f"session {'restarted' if result.get('workflow_terminated') else 'was not running'}."
    )
    # SDL: return the affected user as a canonical UserRecord entity keyed on the
    # reset target's imperal_id; the reset receipt scalars (redis_keys_deleted,
    # workflow_terminated) are not user fields, so they are surfaced in the summary
    # for ICNLI narration rather than as silently-ignored extra data keys.
    return ActionResult.success(
        data={"imperal_id": target},
        summary=summary,
    )


# ─── Limits ───────────────────────────────────────────────────────────── #

@chat.function("update_user_limits", action_type="write", event="user_updated",
               data_model=UserRecord,
               description="Update individual limit overrides for a user.")
async def fn_update_user_limits(ctx, params: UpdateUserLimitsParams) -> ActionResult:
    # Fetch current user to merge attributes
    user = await _gw_request("GET", f"/v1/users/{params.user_id}")
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
    result = await _gw_request("PATCH", f"/v1/users/{params.user_id}",
                               {"attributes": existing})
    if isinstance(result, dict) and "error" in result:
        return ActionResult.error(result["error"])
    # SDL: return the user as a canonical UserRecord entity (id=imperal_id) carrying
    # the merged attribute set the limits live in — both `imperal_id` and
    # `attributes` are real UserRecord fields, so the shape is field-symmetric. NO
    # legacy {user_id, limits} wrapper; the applied-limits delta is in the summary.
    return ActionResult.success(
        data={"imperal_id": params.user_id, "attributes": existing},
        summary=f"Limits updated for {params.user_id}: {updates}" if updates else f"Limits updated for {params.user_id}",
    refresh_panels=["tools"],
    )


# ─── Attributes (ABAC) ───────────────────────────────────────────────── #

@chat.function("set_user_attribute", action_type="write", event="user_updated",
               data_model=UserRecord,
               description="Set a single attribute key-value on a user.")
async def fn_set_user_attribute(ctx, params: SetUserAttributeParams) -> ActionResult:
    if not params.attr_key.strip():
        return ActionResult.error("Attribute key is required")
    user = await _gw_request("GET", f"/v1/users/{params.user_id}")
    if isinstance(user, dict) and "error" in user:
        return ActionResult.error(user["error"])
    attrs = (user.get("attributes") or {}) if isinstance(user, dict) else {}
    attrs[params.attr_key.strip()] = params.attr_value
    result = await _gw_request("PATCH", f"/v1/users/{params.user_id}",
                               {"attributes": attrs})
    if isinstance(result, dict) and "error" in result:
        return ActionResult.error(result["error"])
    # SDL: return the user as a canonical UserRecord entity (id=imperal_id) carrying
    # the updated `attributes` map — field-symmetric (both are UserRecord fields).
    # NO legacy {user_id, key, value} wrapper; the set key/value is in the summary.
    return ActionResult.success(
        data={"imperal_id": params.user_id, "attributes": attrs},
        summary=f"Attribute '{params.attr_key}' set on {params.user_id}",
    refresh_panels=["tools"],
    )


@chat.function("remove_user_attribute", action_type="write", event="user_updated",
               data_model=UserRecord,
               description="Remove an attribute key from a user.")
async def fn_remove_user_attribute(ctx, params: RemoveUserAttributeParams) -> ActionResult:
    user = await _gw_request("GET", f"/v1/users/{params.user_id}")
    if isinstance(user, dict) and "error" in user:
        return ActionResult.error(user["error"])
    attrs = (user.get("attributes") or {}) if isinstance(user, dict) else {}
    removed = attrs.pop(params.attr_key, None)
    if removed is None:
        return ActionResult.error(f"Attribute '{params.attr_key}' not found")
    result = await _gw_request("PATCH", f"/v1/users/{params.user_id}",
                               {"attributes": attrs})
    if isinstance(result, dict) and "error" in result:
        return ActionResult.error(result["error"])
    # SDL: return the user as a canonical UserRecord entity (id=imperal_id) carrying
    # the remaining `attributes` map after removal — field-symmetric. NO legacy
    # {user_id, removed} wrapper; the removed key is named in the summary.
    return ActionResult.success(
        data={"imperal_id": params.user_id, "attributes": attrs},
        summary=f"Attribute '{params.attr_key}' removed from {params.user_id}",
    refresh_panels=["tools"],
    )
