# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors.
# Licensed under the AGPL-3.0 License.
"""Entity record models for admin extension (Phase 14 federal typed return
contract, 2026-05-17).

Federal I-EXT-RECORD-FIELD-NAMING-SYMMETRIC — field names mirror actual
runtime return dict keys (not the corresponding CreateXParams since admin
read tools mostly read-only). Schema published to manifest for kernel
$REF resolver path validation + classifier envelope rendering.

Records use Optional[Any] for complex nested values (lists/dicts) to avoid
strict-mode validation noise during soak. Once stable, can be tightened.
"""
from __future__ import annotations

from typing import Optional, Any
from pydantic import BaseModel


# --- users ---

class UserListResponse(BaseModel):
    """list_users return shape."""
    users: list[dict] = []
    total: int = 0


# --- billing (admin-side) ---

class BillingOverviewResponse(BaseModel):
    plans: list[dict] = []
    plans_count: int = 0
    wallets_active: int = 0
    stream_events_total: int = 0


class UserBalancesResponse(BaseModel):
    wallets: list[dict] = []
    total_users: int = 0
    total_tokens_in_circulation: int = 0


class UserBalanceRecord(BaseModel):
    user_id: Optional[str] = None
    email: Optional[str] = None
    balance: Optional[int] = None
    plan: Optional[str] = None
    cap: Optional[int] = None
    held: Optional[int] = None
    holds: Optional[list[dict]] = None


class BillingHealthResponse(BaseModel):
    redis: Optional[Any] = None
    lua_scripts: Optional[Any] = None
    wallets: Optional[Any] = None
    holds: Optional[Any] = None
    issues: Optional[list] = None


# --- extensions ---

class ExtensionsListResponse(BaseModel):
    extensions: list[dict] = []
    total: int = 0


class ExtensionConfigRecord(BaseModel):
    app_id: Optional[str] = None
    config: Optional[dict] = None
    version: Optional[str] = None
    status: Optional[str] = None


class AccessPolicyRecord(BaseModel):
    app_id: Optional[str] = None
    mode: Optional[str] = None
    per_role: Optional[dict] = None
    per_user: Optional[dict] = None
    resolved: Optional[dict] = None


class ExtensionUsersResponse(BaseModel):
    users: list[dict] = []
    total: int = 0
    app_id: Optional[str] = None


# --- llm ---

class LLMTestResultRecord(BaseModel):
    success: Optional[bool] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    latency_ms: Optional[int] = None
    error: Optional[str] = None


# --- rbac ---

class EffectiveScopesResponse(BaseModel):
    user_id: str
    effective_scopes: list[str] = []
    formatted: Optional[str] = None
    sources: Optional[dict] = None


class PermissionCheckResponse(BaseModel):
    user_id: str
    scope: str
    has_permission: bool
    answer: Optional[str] = None
    source: Optional[str] = None


class CompareRolesResponse(BaseModel):
    role_a: Optional[str] = None
    role_b: Optional[str] = None
    common: list[str] = []
    only_a: list[str] = []
    only_b: list[str] = []


class AuditLogResponse(BaseModel):
    entries: list[dict] = []
    total: int = 0
    period: Optional[str] = None


# --- roles ---

class RoleListResponse(BaseModel):
    roles: list[dict] = []
    total: int = 0


class ScopeListResponse(BaseModel):
    scopes: list[str] = []
    total: int = 0


# --- system ---

class SystemHealthResponse(BaseModel):
    auth_gateway: Optional[Any] = None
    registry: Optional[Any] = None
    overall: Optional[str] = None
    services: Optional[dict] = None


class AdminRulesListResponse(BaseModel):
    rules: list[dict] = []
    total: int = 0
    my_rules_count: int = 0


class ConfirmationPolicyResponse(BaseModel):
    role: str
    policy: Optional[dict] = None


class UserConfirmationResponse(BaseModel):
    user_id: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    enabled: Optional[bool] = None
    skip_read: Optional[bool] = None
    role_policy: Optional[dict] = None


class TaskLimitResponse(BaseModel):
    role: str
    max_tasks: int
