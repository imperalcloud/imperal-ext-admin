"""Admin · System health, rules, confirmation & task limit handlers."""
from __future__ import annotations

import json
import logging
import os

import httpx
from pydantic import BaseModel, Field
from typing import Optional

from app import chat, ActionResult, AUTH_GW, AUTH_SERVICE_TOKEN, REGISTRY_URL, _gw_request, _resolve_role_by_name, _tenant_id, EmptyParams

log = logging.getLogger("admin")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# ─── Models ───────────────────────────────────────────────────────────── #

class RulePromptParams(BaseModel):
    """Create automation from natural language."""
    prompt: str           = Field(description="Rule description in natural language")
    cooldown_seconds: int = Field(default=300, description="Min seconds between triggers")
    max_per_hour: int     = Field(default=10, description="Max triggers per hour")

class RuleIdParams(BaseModel):
    """Target a specific rule."""
    rule_id: int = Field(description="Rule ID")

class ConfirmationPolicyParams(BaseModel):
    """Set confirmation policy for a role."""
    role_name: str = Field(description="Role name")
    policy: str    = Field(description="enforced / default_on / default_off / disabled")

class RoleNameParams(BaseModel):
    """Target a role by name."""
    role_name: str = Field(description="Role name")

class UserConfirmationParams(BaseModel):
    """Set user confirmation settings."""
    user_id: str   = Field(description="User imperal_id")
    enabled: bool  = Field(description="Enable or disable")
    skip_read: bool = Field(default=False, description="Skip for read-only actions")

class UserIdParams(BaseModel):
    """Target a specific user."""
    user_id: str = Field(description="User imperal_id")

class TaskLimitParams(BaseModel):
    """Set task limit for a role."""
    role_name: str = Field(description="Role name")
    max_tasks: int = Field(default=3, description="Max concurrent tasks (1-50)")

class ContextDefaultsParams(BaseModel):
    """Platform-wide context window defaults."""
    quality_ceiling_tokens: Optional[int]  = Field(default=None, description="Quality ceiling tokens")
    default_context_window: Optional[int]  = Field(default=None, description="Default history window")
    default_max_tool_rounds: Optional[int] = Field(default=None, description="Max tool rounds")
    default_max_result_tokens: Optional[int] = Field(default=None, description="Max result size tokens")
    default_keep_recent: Optional[int]     = Field(default=None, description="Keep recent verbatim")
    list_truncate_items: Optional[int]     = Field(default=None, description="List truncate items")
    string_truncate_chars: Optional[int]   = Field(default=None, description="String truncate chars")
    max_history_stored: Optional[int]      = Field(default=None, description="Max messages stored")
    history_ttl_days: Optional[int]        = Field(default=None, description="History TTL days")

# ─── System Health ────────────────────────────────────────────────────── #

@chat.function("system_health", action_type="read", description="Check platform health.")
async def fn_system_health(ctx, params: EmptyParams) -> ActionResult:
    results = {}
    for name, url in [("auth_gateway", f"{AUTH_GW}/healthz"), ("registry", f"{REGISTRY_URL}/health")]:
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                r = await c.get(url)
                results[name] = "operational" if r.status_code == 200 else "down"
        except Exception:
            results[name] = "unreachable"
    return ActionResult.success(data=results, summary=f"Auth GW: {results.get('auth_gateway')}, Registry: {results.get('registry')}")

# ─── Automation Rules ─────────────────────────────────────────────────── #

@chat.function("list_rules", action_type="read", description="List all automation rules.")
async def fn_list_rules(ctx, params: EmptyParams) -> ActionResult:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{AUTH_GW}/v1/automations/internal/all", params={"tenant_id": _tenant_id(ctx)},
                        headers={"X-Service-Token": AUTH_SERVICE_TOKEN})
        if r.status_code != 200:
            return ActionResult.error(f"Failed: HTTP {r.status_code}")
        rules = r.json()
        uid = ctx.user.imperal_id if hasattr(ctx, "user") and ctx.user else ""
        my = sum(1 for r in rules if r.get("user_id") == uid)
        return ActionResult.success(data={"rules": rules, "total": len(rules), "my_rules_count": my},
                                    summary=f"{len(rules)} rules total, {my} yours")

@chat.function("create_rule", action_type="write", event="rule_created", description="Create automation from natural language.")
async def fn_create_rule(ctx, params: RulePromptParams) -> ActionResult:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(f"{AUTH_GW}/v1/automations", json={"prompt": params.prompt, "cooldown_seconds": params.cooldown_seconds, "max_per_hour": params.max_per_hour},
                         headers={"X-Service-Token": AUTH_SERVICE_TOKEN, "Content-Type": "application/json"})
        if r.status_code in (200, 201):
            return ActionResult.success(data={"rule": r.json()}, summary="Automation rule created")
        return ActionResult.error(f"Failed: {r.text}")

@chat.function("delete_rule", action_type="destructive", event="rule_deleted", description="Delete an automation rule.")
async def fn_delete_rule(ctx, params: RuleIdParams) -> ActionResult:
    async with httpx.AsyncClient(timeout=10) as c:
        await c.delete(f"{AUTH_GW}/v1/automations/{params.rule_id}", headers={"X-Service-Token": AUTH_SERVICE_TOKEN})
    return ActionResult.success(data={"deleted": True, "rule_id": params.rule_id}, summary=f"Rule {params.rule_id} deleted")

@chat.function("pause_rule", action_type="write", event="rule_paused", description="Pause an automation rule.")
async def fn_pause_rule(ctx, params: RuleIdParams) -> ActionResult:
    async with httpx.AsyncClient(timeout=10) as c:
        await c.post(f"{AUTH_GW}/v1/automations/{params.rule_id}/pause", headers={"X-Service-Token": AUTH_SERVICE_TOKEN})
    return ActionResult.success(data={"paused": True, "rule_id": params.rule_id}, summary=f"Rule {params.rule_id} paused")

@chat.function("resume_rule", action_type="write", event="rule_resumed", description="Resume a paused rule. Resets trigger_count.")
async def fn_resume_rule(ctx, params: RuleIdParams) -> ActionResult:
    async with httpx.AsyncClient(timeout=10) as c:
        h = {"X-Service-Token": AUTH_SERVICE_TOKEN, "Content-Type": "application/json"}
        await c.patch(f"{AUTH_GW}/v1/automations/internal/{params.rule_id}", json={"status": "active"}, headers=h)
        await c.patch(f"{AUTH_GW}/v1/automations/internal/{params.rule_id}", json={"trigger_count": 0}, headers=h)
    return ActionResult.success(data={"resumed": True, "rule_id": params.rule_id}, summary=f"Rule {params.rule_id} resumed")

# ─── Confirmation Policy ──────────────────────────────────────────────── #

@chat.function("set_confirmation_policy", action_type="write", event="confirmation_set", description="Set confirmation policy for a role.")
async def fn_set_confirmation_policy(ctx, params: ConfirmationPolicyParams) -> ActionResult:
    valid = ("enforced", "default_on", "default_off", "disabled")
    if params.policy not in valid:
        return ActionResult.error(f"Invalid: must be {', '.join(valid)}")
    role = await _resolve_role_by_name(params.role_name)
    if not role:
        return ActionResult.error(f"Role '{params.role_name}' not found")
    result = await _gw_request("PATCH", f"/v1/roles/{role['id']}", {"confirmation_policy": params.policy})
    if isinstance(result, dict) and result.get("error"):
        return ActionResult.error(result["error"])
    return ActionResult.success(data={"role": params.role_name, "policy": params.policy}, summary=f"'{params.role_name}' confirmation: {params.policy}")

@chat.function("get_confirmation_policy", action_type="read", description="Get confirmation policy for a role.")
async def fn_get_confirmation_policy(ctx, params: RoleNameParams) -> ActionResult:
    role = await _resolve_role_by_name(params.role_name)
    if not role:
        return ActionResult.error(f"Role '{params.role_name}' not found")
    return ActionResult.success(data={"role": params.role_name, "policy": role.get("confirmation_policy", "default_on")},
                                summary=f"'{params.role_name}': {role.get('confirmation_policy', 'default_on')}")

@chat.function("set_user_confirmation", action_type="write", event="confirmation_set", description="Set confirmation for a user.")
async def fn_set_user_confirmation(ctx, params: UserConfirmationParams) -> ActionResult:
    result = await _gw_request("PATCH", f"/v1/users/{params.user_id}",
                               {"attributes": {"confirmation_enabled": params.enabled, "confirmation_skip_read": params.skip_read}})
    if isinstance(result, dict) and result.get("error"):
        return ActionResult.error(result["error"])
    return ActionResult.success(data={"user_id": params.user_id, "enabled": params.enabled},
                                summary=f"User {params.user_id} confirmation {'enabled' if params.enabled else 'disabled'}")

@chat.function("get_user_confirmation", action_type="read", description="Get user confirmation settings.")
async def fn_get_user_confirmation(ctx, params: UserIdParams) -> ActionResult:
    user = await _gw_request("GET", f"/v1/users/{params.user_id}")
    if isinstance(user, dict) and user.get("error"):
        return ActionResult.error(user["error"])
    attrs = user.get("attributes", {}) if isinstance(user, dict) else {}
    return ActionResult.success(
        data={"user_id": params.user_id, "email": user.get("email", ""), "role": user.get("role", ""),
              "enabled": attrs.get("confirmation_enabled"), "skip_read": attrs.get("confirmation_skip_read", False),
              "role_policy": user.get("role_confirmation_policy", "default_on")},
        summary=f"{user.get('email', params.user_id)}: enabled={attrs.get('confirmation_enabled', 'inherit')}")

# ─── Task Limits ──────────────────────────────────────────────────────── #

@chat.function("set_task_limit", action_type="write", event="task_limit_set", description="Set max concurrent tasks for a role (1-50).")
async def fn_set_task_limit(ctx, params: TaskLimitParams) -> ActionResult:
    if not 1 <= params.max_tasks <= 50:
        return ActionResult.error("max_tasks must be 1-50")
    role = await _resolve_role_by_name(params.role_name)
    if not role:
        return ActionResult.error(f"Role '{params.role_name}' not found")
    result = await _gw_request("PATCH", f"/v1/roles/{role['id']}", {"max_concurrent_tasks": params.max_tasks})
    if isinstance(result, dict) and result.get("error"):
        return ActionResult.error(result["error"])
    return ActionResult.success(data={"role": params.role_name, "max_tasks": params.max_tasks},
                                summary=f"'{params.role_name}' task limit: {params.max_tasks}")

@chat.function("get_task_limit", action_type="read", description="Get max concurrent tasks for a role.")
async def fn_get_task_limit(ctx, params: RoleNameParams) -> ActionResult:
    role = await _resolve_role_by_name(params.role_name)
    if not role:
        return ActionResult.error(f"Role '{params.role_name}' not found")
    return ActionResult.success(data={"role": params.role_name, "max_tasks": role.get("max_concurrent_tasks", 3)},
                                summary=f"'{params.role_name}' task limit: {role.get('max_concurrent_tasks', 3)}")

# ─── Context Defaults ─────────────────────────────────────────────────── #

@chat.function("save_context_defaults", action_type="write",
               description="Save platform-wide context window defaults via Auth GW.")
async def fn_save_context_defaults(ctx, params: ContextDefaultsParams) -> ActionResult:
    """Persist context defaults via Auth GW platform config (same as React)."""
    try:
        # Read current platform config
        raw = await _gw_request("GET", "/v1/internal/config/platform/platform")
        current_config = raw.get("config", {}) if isinstance(raw, dict) else {}
        current_defaults = current_config.get("context_defaults", {})

        updates = {}
        for field_name in ContextDefaultsParams.model_fields:
            val = getattr(params, field_name)
            if val is not None:
                updates[field_name] = int(val)

        current_defaults.update(updates)
        current_config["context_defaults"] = current_defaults

        # Write back via Auth GW
        await _gw_request("PUT", "/v1/internal/config/platform/platform",
                          {"config": current_config})

        return ActionResult.success(
            data={"saved": updates, "full_config": current_defaults},
            summary=f"Saved {len(updates)} context defaults",
        )
    except Exception as e:
        log.error("save_context_defaults failed: %s", e)
        return ActionResult.error(f"Failed to save: {e}", retryable=True)

# ─── Panel Data ───────────────────────────────────────────────────────── #

from imperal_sdk import ui

@chat.function("get_panel_data", action_type="read",
               description="Get panel Declarative UI data for admin extension.")
async def fn_get_panel_data(ctx, params: EmptyParams) -> ActionResult:
    """Build admin dashboard UI from skeleton cache."""
    cached = ctx.skeleton_data.get("admin_stats", {}) if hasattr(ctx, "skeleton_data") else {}
    stats = cached if isinstance(cached, dict) else {}

    # Left panel: user list
    users = stats.get("users_list", [])
    items = [
        ui.ListItem(
            id=u.get("id", ""),
            title=u.get("email", "?"),
            subtitle=u.get("role", "user"),
            badge=ui.Badge("active", color="green") if u.get("active") else ui.Badge("inactive", color="gray"),
            on_click=ui.Call("effective_scopes", user_id=u.get("id", "")),
        )
        for u in users
    ]
    left = ui.List(items=items, searchable=True)

    # Right panel: dashboard widgets
    right = ui.Stack([
        ui.Grid([
            ui.Stat(label="Users", value=stats.get("users_total", 0), icon="users", color="blue"),
            ui.Stat(label="Active", value=stats.get("users_active", 0), icon="user-check", color="green"),
            ui.Stat(label="Roles", value=stats.get("roles_count", 0), icon="shield", color="purple"),
            ui.Stat(label="Extensions", value=stats.get("extensions_active", 0), icon="puzzle", color="cyan"),
        ], columns=2),
        ui.Card(
            title="System Health",
            content=ui.Stack([
                ui.Alert(
                    title="Auth Gateway",
                    message=stats.get("health_auth_gateway", "unknown"),
                    type="success" if stats.get("health_auth_gateway") == "operational" else "error",
                ),
                ui.Alert(
                    title="Registry",
                    message=stats.get("health_registry", "unknown"),
                    type="success" if stats.get("health_registry") == "operational" else "error",
                ),
            ]),
        ),
    ])

    # Tray value
    health_ok = stats.get("health_auth_gateway") == "operational" and stats.get("health_registry") == "operational"
    tray_value = 1 if health_ok else 0

    return ActionResult.success(
        data={
            "left": left.to_dict(),
            "right": right.to_dict(),
            "tray_value": tray_value,
        },
        summary="Panel data loaded",
    )
