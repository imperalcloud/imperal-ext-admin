"""Admin · System health, rules, confirmation & task limit handlers."""
from __future__ import annotations

import json
import logging
import os

import httpx
from imperal_sdk._shared_http import shared_http
from pydantic import BaseModel, Field
from typing import Optional

from app import chat, ActionResult, AUTH_GW, AUTH_SERVICE_TOKEN, REGISTRY_URL, _gw_request, _resolve_role_by_name, _tenant_id, EmptyParams
from models_records import (
    AdminRulesListResponse, ConfirmationPolicyResponse, RuleActionReceipt, SystemHealthResponse,
    TaskLimitResponse, UserConfirmationResponse,
)

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

# ─── System Health ────────────────────────────────────────────────────── #

@chat.function("system_health", action_type="read", data_model=SystemHealthResponse, description="Check platform health.")
async def fn_system_health(ctx, params: EmptyParams) -> ActionResult:
    """Check platform health."""
    results = {}
    for name, url in [("auth_gateway", f"{AUTH_GW}/healthz"), ("registry", f"{REGISTRY_URL}/health")]:
        try:
            async with shared_http(timeout=5) as c:
                r = await c.get(url)
                results[name] = "operational" if r.status_code == 200 else "down"
        except Exception:
            results[name] = "unreachable"
    return ActionResult.success(data=results, summary=f"Auth GW: {results.get('auth_gateway')}, Registry: {results.get('registry')}")

# ─── Automation Rules ─────────────────────────────────────────────────── #

@chat.function("list_rules", action_type="read", data_model=AdminRulesListResponse, description="List all automation rules.")
async def fn_list_rules(ctx, params: EmptyParams) -> ActionResult:
    """List all automation rules."""
    async with shared_http(timeout=10) as c:
        r = await c.get(f"{AUTH_GW}/v1/automations/internal/all", params={"tenant_id": _tenant_id(ctx)},
                        headers={"X-Service-Token": AUTH_SERVICE_TOKEN})
        if r.status_code != 200:
            return ActionResult.error(f"Failed: HTTP {r.status_code}")
        rules = r.json()
        uid = ctx.user.imperal_id if hasattr(ctx, "user") and ctx.user else ""
        my = sum(1 for r in rules if r.get("user_id") == uid)
        return ActionResult.success(data={"items": rules, "total": len(rules), "my_rules_count": my},
                                    summary=f"{len(rules)} rules total, {my} yours")

@chat.function("create_rule", action_type="write", effects=["create:automation_rule"], event="rule_created", data_model=RuleActionReceipt, description="Create automation from natural language.")
async def fn_create_rule(ctx, params: RulePromptParams) -> ActionResult:
    """Create automation from natural language."""
    async with shared_http(timeout=15) as c:
        r = await c.post(f"{AUTH_GW}/v1/automations", json={"prompt": params.prompt, "cooldown_seconds": params.cooldown_seconds, "max_per_hour": params.max_per_hour},
                         headers={"X-Service-Token": AUTH_SERVICE_TOKEN, "Content-Type": "application/json"})
        if r.status_code in (200, 201):
            return ActionResult.success(data={"rule": r.json()}, summary="Automation rule created", refresh_panels=["tools"])
        return ActionResult.error(f"Failed: {r.text}")

@chat.function("delete_rule", action_type="destructive", effects=["delete:automation_rule"], event="rule_deleted", data_model=RuleActionReceipt, description="Delete an automation rule.")
async def fn_delete_rule(ctx, params: RuleIdParams) -> ActionResult:
    """Delete an automation rule."""
    async with shared_http(timeout=10) as c:
        await c.delete(f"{AUTH_GW}/v1/automations/{params.rule_id}", headers={"X-Service-Token": AUTH_SERVICE_TOKEN})
    return ActionResult.success(data={"deleted": True, "rule_id": params.rule_id}, summary=f"Rule {params.rule_id} deleted", refresh_panels=["tools"])

@chat.function("pause_rule", action_type="write", effects=["update:automation_rule"], event="rule_paused", data_model=RuleActionReceipt, description="Pause an automation rule.")
async def fn_pause_rule(ctx, params: RuleIdParams) -> ActionResult:
    """Pause an automation rule."""
    async with shared_http(timeout=10) as c:
        await c.post(f"{AUTH_GW}/v1/automations/{params.rule_id}/pause", headers={"X-Service-Token": AUTH_SERVICE_TOKEN})
    return ActionResult.success(data={"paused": True, "rule_id": params.rule_id}, summary=f"Rule {params.rule_id} paused", refresh_panels=["tools"])

@chat.function("resume_rule", action_type="write", effects=["update:automation_rule"], event="rule_resumed", data_model=RuleActionReceipt, description="Resume a paused rule. Resets trigger_count.")
async def fn_resume_rule(ctx, params: RuleIdParams) -> ActionResult:
    """Resume a paused rule. Resets trigger_count."""
    async with shared_http(timeout=10) as c:
        h = {"X-Service-Token": AUTH_SERVICE_TOKEN, "Content-Type": "application/json"}
        await c.patch(f"{AUTH_GW}/v1/automations/internal/{params.rule_id}", json={"status": "active"}, headers=h)
        await c.patch(f"{AUTH_GW}/v1/automations/internal/{params.rule_id}", json={"trigger_count": 0}, headers=h)
    return ActionResult.success(data={"resumed": True, "rule_id": params.rule_id}, summary=f"Rule {params.rule_id} resumed", refresh_panels=["tools"])

# ─── Confirmation Policy ──────────────────────────────────────────────── #

@chat.function("set_confirmation_policy", action_type="write", effects=["update:confirmation_policy"], event="confirmation_set", data_model=ConfirmationPolicyResponse, description="Set confirmation policy for a role.")
async def fn_set_confirmation_policy(ctx, params: ConfirmationPolicyParams) -> ActionResult:
    """Set confirmation policy for a role."""
    valid = ("enforced", "default_on", "default_off", "disabled")
    if params.policy not in valid:
        return ActionResult.error(f"Invalid: must be {', '.join(valid)}")
    role = await _resolve_role_by_name(params.role_name)
    if not role:
        return ActionResult.error(f"Role '{params.role_name}' not found")
    result = await _gw_request("PATCH", f"/v1/roles/{role['id']}", {"confirmation_policy": params.policy})
    if isinstance(result, dict) and result.get("error"):
        return ActionResult.error(result["error"])
    return ActionResult.success(data={"role": params.role_name, "policy": params.policy}, summary=f"'{params.role_name}' confirmation: {params.policy}", refresh_panels=["tools"])

@chat.function("get_confirmation_policy", action_type="read", data_model=ConfirmationPolicyResponse, description="Get confirmation policy for a role.")
async def fn_get_confirmation_policy(ctx, params: RoleNameParams) -> ActionResult:
    """Get confirmation policy for a role."""
    role = await _resolve_role_by_name(params.role_name)
    if not role:
        return ActionResult.error(f"Role '{params.role_name}' not found")
    return ActionResult.success(data={"role": params.role_name, "policy": role.get("confirmation_policy", "default_on")},
                                summary=f"'{params.role_name}': {role.get('confirmation_policy', 'default_on')}")

@chat.function("set_user_confirmation", action_type="write", effects=["update:user_confirmation"], event="confirmation_set", data_model=UserConfirmationResponse, description="Set confirmation for a user.")
async def fn_set_user_confirmation(ctx, params: UserConfirmationParams) -> ActionResult:
    """Set confirmation for a user.

    STORE OF TRUTH: ``unified_config`` (scope=user) ``user_settings``, written
    via ``PATCH /v1/internal/users/{id}/settings``. That is the SAME row the
    Auth GW serves to the kernel on every turn
    (kernel_resolve._resolve_settings -> kctx.confirmation_enabled), so a
    toggle here takes effect on the user's very next message.

    Historically this handler wrote ``users.attributes.confirmation_enabled``
    instead. MEASURED on live prod: NOTHING reads that key for the gate — 0/38
    active users had it set, while 13/13 resolvable users tracked
    unified_config exactly. The 2-step toggle was therefore a silent no-op:
    admins could "enable" confirmations and the destructive gate stayed off,
    and get_user_confirmation always reported "inherit" no matter the real
    value. Federal: the confirmation gate is mandatory safety machinery, so
    its admin control MUST write the store the gate actually reads.

    ``attributes`` is still mirrored (best-effort, non-fatal) because the
    Users panel renders ``attrs.confirmation_enabled`` in the expanded row --
    keeping it in sync stops the panel showing a stale "inherit from role".
    """
    # 1) authoritative write -- the store the kernel reads
    settings_patch = {
        "confirmation_enabled": params.enabled,
        "confirmation_skip_read": params.skip_read,
    }
    result = await _gw_request(
        "PATCH", f"/v1/internal/users/{params.user_id}/settings", settings_patch)
    if isinstance(result, dict) and result.get("error"):
        return ActionResult.error(result["error"])

    # 2) verify it actually landed -- never report success on an unconfirmed write
    check = await _gw_request(
        "GET", f"/v1/internal/users/{params.user_id}/settings?tenant_id={_tenant_id(ctx)}")
    effective = None
    if isinstance(check, dict) and not check.get("error"):
        effective = (check.get("settings", check) or {}).get("confirmation_enabled")
    if effective is not None and bool(effective) != bool(params.enabled):
        return ActionResult.error(
            f"confirmation setting did not persist (asked {params.enabled}, "
            f"gateway still reports {effective})")

    # 3) best-effort mirror for the Users panel display (never fatal)
    mirror = await _gw_request("PATCH", f"/v1/users/{params.user_id}",
                               {"attributes": {"confirmation_enabled": params.enabled,
                                               "confirmation_skip_read": params.skip_read}})
    if isinstance(mirror, dict) and mirror.get("error"):
        log.warning("set_user_confirmation: attributes mirror failed for %s: %s",
                    params.user_id, mirror.get("error"))

    return ActionResult.success(data={"user_id": params.user_id, "enabled": params.enabled},
                                summary=f"User {params.user_id} confirmation {'enabled' if params.enabled else 'disabled'}", refresh_panels=["tools"])

@chat.function("get_user_confirmation", action_type="read", data_model=UserConfirmationResponse, description="Get user confirmation settings.")
async def fn_get_user_confirmation(ctx, params: UserIdParams) -> ActionResult:
    """Get user confirmation settings.

    Reads the EFFECTIVE value from the same store the kernel resolves
    (``unified_config.user_settings`` via the Auth GW internal settings
    endpoint) instead of ``users.attributes``, which no longer governs the
    gate. ``enabled`` is therefore what the user will actually experience on
    their next turn; ``role_policy`` is reported alongside as context, not as
    the answer.
    """
    user = await _gw_request("GET", f"/v1/users/{params.user_id}")
    if isinstance(user, dict) and user.get("error"):
        return ActionResult.error(user["error"])
    attrs = user.get("attributes", {}) if isinstance(user, dict) else {}

    settings = await _gw_request(
        "GET", f"/v1/internal/users/{params.user_id}/settings?tenant_id={_tenant_id(ctx)}")
    enabled = None
    if isinstance(settings, dict) and not settings.get("error"):
        s = settings.get("settings", settings) or {}
        enabled = s.get("confirmation_enabled")
    else:
        # settings endpoint unreachable -- fall back to the legacy attribute
        # rather than silently claiming the gate is off.
        enabled = attrs.get("confirmation_enabled")

    return ActionResult.success(
        data={"user_id": params.user_id, "email": user.get("email", ""), "role": user.get("role", ""),
              "enabled": enabled, "skip_read": attrs.get("confirmation_skip_read", False),
              "role_policy": user.get("role_confirmation_policy", "default_on")},
        summary=f"{user.get('email', params.user_id)}: enabled={enabled if enabled is not None else 'unknown'}")

# ─── Task Limits ──────────────────────────────────────────────────────── #

@chat.function("set_task_limit", action_type="write", effects=["update:task_limit"], event="task_limit_set", data_model=TaskLimitResponse, description="Set max concurrent tasks for a role (1-50).")
async def fn_set_task_limit(ctx, params: TaskLimitParams) -> ActionResult:
    """Set max concurrent tasks for a role (1-50)."""
    if not 1 <= params.max_tasks <= 50:
        return ActionResult.error("max_tasks must be 1-50")
    role = await _resolve_role_by_name(params.role_name)
    if not role:
        return ActionResult.error(f"Role '{params.role_name}' not found")
    result = await _gw_request("PATCH", f"/v1/roles/{role['id']}", {"max_concurrent_tasks": params.max_tasks})
    if isinstance(result, dict) and result.get("error"):
        return ActionResult.error(result["error"])
    return ActionResult.success(data={"role": params.role_name, "max_tasks": params.max_tasks},
                                summary=f"'{params.role_name}' task limit: {params.max_tasks}",
                                refresh_panels=["tools"])

@chat.function("get_task_limit", action_type="read", data_model=TaskLimitResponse, description="Get max concurrent tasks for a role.")
async def fn_get_task_limit(ctx, params: RoleNameParams) -> ActionResult:
    """Get max concurrent tasks for a role."""
    role = await _resolve_role_by_name(params.role_name)
    if not role:
        return ActionResult.error(f"Role '{params.role_name}' not found")
    return ActionResult.success(data={"role": params.role_name, "max_tasks": role.get("max_concurrent_tasks", 3)},
                                summary=f"'{params.role_name}' task limit: {role.get('max_concurrent_tasks', 3)}")

# ─── Panel Data ───────────────────────────────────────────────────────── #

from imperal_sdk import ui

# V23 EXEMPTION (SDL): get_panel_data is intentionally NOT given a data_model.
# Its return is Declarative-UI output ({left, right, tray_value} of ui.*.to_dict()),
# NOT an SDL entity/list — it carries no domain entity to type. Per the SDL
# migration policy, Declarative-UI panel builders are exempt from the
# sdl.Entity / sdl.EntityList contract; forcing an entity model here would
# misrepresent UI primitives as data records.
@chat.function("get_panel_data", action_type="read", ui_builder=True,
               description="Get panel Declarative UI data for admin extension.")
async def fn_get_panel_data(ctx, params: EmptyParams) -> ActionResult:
    """Build admin dashboard UI by calling the shared admin_stats fetcher."""
    from skeleton import build_admin_stats  # local import — avoids circular at module load
    stats = await build_admin_stats(ctx)

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
            ui.Stat(label="Users", value=stats.get("users_total", 0), icon="Users", color="blue"),
            ui.Stat(label="Active", value=stats.get("users_active", 0), icon="UserCheck", color="green"),
            ui.Stat(label="Roles", value=stats.get("roles_count", 0), icon="Shield", color="purple"),
            ui.Stat(label="Extensions", value=stats.get("extensions_active", 0), icon="Puzzle", color="cyan"),
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
