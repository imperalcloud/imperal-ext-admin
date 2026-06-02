# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors.
# Licensed under the AGPL-3.0 License.
"""SDL entity records — RBAC query domain (audit, permission checks, scope diff).

Federal I-EXT-RECORD-FIELD-NAMING-SYMMETRIC: field names mirror the ACTUAL
runtime dict keys (verified against handlers_rbac.py + panels_audit.py). 100%
SDL — the audit list return is a real ``sdl.EntityList[T]``; the single-result
RBAC answers are real ``sdl.Entity`` records.
"""
from __future__ import annotations

from typing import Optional, Any
from pydantic import model_validator

from imperal_sdk import sdl


# --- audit log ---

class AuditEntryRecord(sdl.Entity):
    """A single audit-log entry as a canonical SDL entity (kind='audit_entry').

    Gateway entry dict keys (verified vs panels_audit._build_entry_expanded /
    build_audit): id, created_at|timestamp, actor|actor_id, action, target_type,
    target_id, source, ip|ip_address, details|message, before_state, after_state.
    id = entry id (falls back to timestamp); title = action."""
    created_at: Optional[Any] = None
    timestamp: Optional[Any] = None
    actor: Optional[Any] = None
    actor_id: Optional[Any] = None
    action: Optional[str] = None
    target_type: Optional[str] = None
    target_id: Optional[Any] = None
    source: Optional[str] = None
    ip: Optional[str] = None
    ip_address: Optional[str] = None
    details: Optional[Any] = None
    message: Optional[Any] = None
    before_state: Optional[Any] = None
    after_state: Optional[Any] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data["id"] = (
                data.get("id") or data.get("created_at")
                or data.get("timestamp") or ""
            )
            data.setdefault("title", data.get("action") or "audit_entry")
            data.setdefault("kind", "audit_entry")
        return data


class AuditLogResponse(sdl.EntityList[AuditEntryRecord]):
    """audit_log return shape — a REAL sdl.EntityList[AuditEntryRecord]
    (items=[...]). The handler keeps its observability scalars as extra typed
    fields (period/showing/truncated/hours) — additive on the pydantic
    EntityList. NO legacy {entries:[dict],total,period} wrapper."""
    period: Optional[str] = None
    showing: Optional[int] = None
    truncated: Optional[bool] = None
    hours: Optional[int] = None


# --- single-result RBAC answers ---

class EffectiveScopesResponse(sdl.Entity):
    """effective_scopes return shape — a single user-scopes entity."""
    user_id: str
    effective_scopes: Any = None
    formatted: Optional[str] = None
    sources: Optional[dict] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data.setdefault("id", data.get("user_id") or "")
            data.setdefault("title", data.get("user_id") or "")
            data.setdefault("kind", "user")
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
            data.setdefault("kind", "user")
        return data


class CompareRolesResponse(sdl.Entity):
    """compare_roles return shape — a single role-comparison entity.

    Field names match the handler's actual keys: role1/role2 (dicts),
    common_scopes/only_in_role1/only_in_role2 (NOT the older role_a/role_b/
    common/only_a/only_b guesses)."""
    role1: Optional[Any] = None
    role2: Optional[Any] = None
    common_scopes: Optional[list[str]] = None
    only_in_role1: Optional[list[str]] = None
    only_in_role2: Optional[list[str]] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            r1 = data.get("role1") if isinstance(data.get("role1"), dict) else {}
            r2 = data.get("role2") if isinstance(data.get("role2"), dict) else {}
            name1 = r1.get("name") if r1 else (data.get("role1") if isinstance(data.get("role1"), str) else "")
            name2 = r2.get("name") if r2 else (data.get("role2") if isinstance(data.get("role2"), str) else "")
            data.setdefault("id", f"{name1}_vs_{name2}")
            data.setdefault("title", f"{name1} vs {name2}")
            data.setdefault("kind", "rolecomparison")
        return data
