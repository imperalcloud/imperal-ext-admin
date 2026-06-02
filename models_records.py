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

SDL migration (additive, non-breaking — SDK 5.2.0): the single-entity return
records below now subclass ``sdl.Entity`` (+ matching facets). EVERY existing
field is kept verbatim — panels, install-flows and the kernel $REF resolver
keep reading the exact same keys. A ``mode="before"`` validator populates the
canonical ``id``/``title`` from existing id-ish/name-ish fields, so EXISTING
``ActionResult.success(data={...})`` construction calls work unchanged. UserListResponse is now a REAL ``sdl.EntityList[UserRecord]`` (2026-06-02, NO
legacy) — each user is a typed SDL entity so the kernel resolves/refers to users
as SDL entities. The remaining LIST wrappers (BillingOverviewResponse, ...) keep
their original shape until their inner items are typed too.
"""
from __future__ import annotations

from typing import Optional, Any
from pydantic import BaseModel, model_validator

from imperal_sdk import sdl


# --- users ---

class UserRecord(sdl.Entity):
    """A single user as a canonical SDL entity (kind='user'): id=imperal_id,
    title=display name. Gateway fields are kept verbatim for rendering."""
    imperal_id: Optional[str] = None
    display_name: Optional[Any] = None
    full_name: Optional[Any] = None
    email: Optional[Any] = None
    role: Optional[Any] = None
    is_active: Optional[Any] = None
    last_login: Optional[Any] = None
    scopes: Optional[Any] = None
    attributes: Optional[Any] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            # Canonical id = imperal_id (reset_conversation / user tools key on
            # it); OVERWRITE any non-canonical gateway "id". Mirrors
            # _resolve_user_by_email (imperal_id or id).
            data["id"] = data.get("imperal_id") or data.get("id") or ""
            data.setdefault(
                "title",
                data.get("display_name") or data.get("full_name")
                or data.get("email") or data.get("imperal_id") or "",
            )
            data.setdefault("kind", "user")
        return data


class UserListResponse(sdl.EntityList[UserRecord]):
    """list_users return shape — a REAL sdl.EntityList[UserRecord] (items=[...],
    x-sdl='entity-list'). Replaces the legacy {users:[dict],total} wrapper so the
    kernel resolves/refers to users as typed SDL entities. NO legacy."""
    pass


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


class UserBalanceRecord(sdl.Entity):
    """get_user_balance return shape — a single user wallet entity.

    ``balance`` is a token count (int), NOT a currency Decimal, so the
    ``money.balance`` (Balanced) facet is deliberately NOT mixed in to avoid
    int->Decimal type drift; kept as the existing plain int field.
    """
    user_id: Optional[str] = None
    email: Optional[str] = None
    balance: Optional[int] = None
    plan: Optional[str] = None
    cap: Optional[int] = None
    held: Optional[int] = None
    holds: Optional[list[dict]] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data.setdefault("id", data.get("user_id") or "")
            data.setdefault("title", data.get("email") or data.get("user_id") or "")
        return data


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


class ExtensionConfigRecord(sdl.Entity, sdl.Versioned):
    """get_extension_config return shape — a single extension config entity.

    ``version`` is provided by the Versioned facet (role ``core.version``);
    ``status`` is the core Entity field (role ``core.status``).
    """
    app_id: Optional[str] = None
    config: Optional[dict] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data.setdefault("id", data.get("app_id") or "")
            data.setdefault("title", data.get("app_id") or "")
        return data


class AccessPolicyRecord(sdl.Entity):
    """get_access_policy return shape — a single extension access-policy entity."""
    app_id: Optional[str] = None
    mode: Optional[str] = None
    per_role: Optional[dict] = None
    per_user: Optional[dict] = None
    resolved: Optional[dict] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data.setdefault("id", data.get("app_id") or "")
            data.setdefault("title", data.get("app_id") or "")
        return data


class ExtensionUsersResponse(BaseModel):
    users: list[dict] = []
    total: int = 0
    app_id: Optional[str] = None


# --- llm ---

class LLMTestResultRecord(sdl.Entity):
    """test_llm_connection return shape — a single connection-test entity."""
    success: Optional[bool] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    latency_ms: Optional[int] = None
    error: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data.setdefault("id", data.get("model") or data.get("provider") or "")
            data.setdefault("title", data.get("model") or data.get("provider") or "")
        return data


# --- rbac ---

class EffectiveScopesResponse(sdl.Entity):
    """effective_scopes return shape — a single user-scopes entity."""
    user_id: str
    effective_scopes: list[str] = []
    formatted: Optional[str] = None
    sources: Optional[dict] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data.setdefault("id", data.get("user_id") or "")
            data.setdefault("title", data.get("user_id") or "")
        return data


class PermissionCheckResponse(sdl.Entity):
    """check_permission return shape — a single permission-check entity."""
    user_id: str
    scope: str
    has_permission: bool
    answer: Optional[str] = None
    source: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data.setdefault("id", data.get("user_id") or "")
            data.setdefault("title", data.get("user_id") or "")
        return data


class CompareRolesResponse(sdl.Entity):
    """compare_roles return shape — a single role-comparison entity."""
    role_a: Optional[str] = None
    role_b: Optional[str] = None
    common: list[str] = []
    only_a: list[str] = []
    only_b: list[str] = []

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data.setdefault("id", data.get("role_a") or "")
            data.setdefault("title", data.get("role_a") or "")
        return data


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


class ConfirmationPolicyResponse(sdl.Entity):
    """get_confirmation_policy return shape — a single role-policy entity."""
    role: str
    policy: Optional[dict] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data.setdefault("id", data.get("role") or "")
            data.setdefault("title", data.get("role") or "")
        return data


class UserConfirmationResponse(sdl.Entity):
    """get_user_confirmation return shape — a single user-confirmation entity."""
    user_id: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    enabled: Optional[bool] = None
    skip_read: Optional[bool] = None
    role_policy: Optional[dict] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data.setdefault("id", data.get("user_id") or "")
            data.setdefault("title", data.get("email") or data.get("user_id") or "")
        return data


class TaskLimitResponse(sdl.Entity):
    """get_task_limit return shape — a single role task-limit entity."""
    role: str
    max_tasks: int

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data.setdefault("id", data.get("role") or "")
            data.setdefault("title", data.get("role") or "")
        return data
