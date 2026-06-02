# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors.
# Licensed under the AGPL-3.0 License.
"""SDL entity records — ROLES & SCOPES domain.

Federal I-EXT-RECORD-FIELD-NAMING-SYMMETRIC: field names mirror the ACTUAL
gateway dict keys (verified against handlers_roles.py + panels_roles.py /
panels_scopes.py). 100% SDL — list returns are real ``sdl.EntityList[T]``.
"""
from __future__ import annotations

from typing import Optional, Any
from pydantic import model_validator

from imperal_sdk import sdl


# --- roles ---

class RoleRecord(sdl.Entity):
    """A single role as a canonical SDL entity (kind='role'): id=role id (or
    name), title=display_name (or name). Gateway role dict keys (verified vs
    /v1/roles consumers in panels_roles.py) kept verbatim."""
    name: Optional[str] = None
    display_name: Optional[Any] = None
    default_scopes: Optional[list[str]] = None
    is_system: Optional[bool] = None
    confirmation_policy: Optional[str] = None
    monthly_action_limit: Optional[int] = None
    max_concurrent_tasks: Optional[int] = None
    context_window: Optional[int] = None
    default_extensions: Optional[list] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            # Canonical id = role id; OVERWRITE with the more-canonical key if
            # present. delete_role / update_role resolve by name->id, so name
            # is the resolvable handle when id is absent.
            data["id"] = data.get("id") or data.get("role_id") or data.get("name") or ""
            data.setdefault("title", data.get("display_name") or data.get("name") or "")
            data.setdefault("kind", "role")
        return data


class RoleListResponse(sdl.EntityList[RoleRecord]):
    """list_roles return shape — a REAL sdl.EntityList[RoleRecord] (items=[...]).
    NO legacy {roles:[dict],total} wrapper."""
    pass


class RoleActionReceipt(sdl.Entity):
    """Receipt entity for role create/update/delete writes (kind='role').

    Reused by create_role / update_role / delete_role return shapes — keeps the
    existing receipt keys verbatim (``role`` payload, ``role_id``, ``deleted``,
    ``cascaded_count``) so panels and the $REF resolver read the same data.
    Prefer this over inventing a per-verb receipt."""
    role: Optional[Any] = None
    role_id: Optional[str] = None
    name: Optional[str] = None
    deleted: Optional[bool] = None
    cascaded_count: Optional[int] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            _role = data.get("role")
            inner = _role if isinstance(_role, dict) else {}
            data["id"] = (
                data.get("role_id") or inner.get("id")
                or inner.get("name") or data.get("name") or ""
            )
            data.setdefault(
                "title",
                inner.get("display_name") or inner.get("name")
                or data.get("name") or str(data.get("role_id") or ""),
            )
            data.setdefault("kind", "role")
        return data


class BulkRoleAssignReceipt(sdl.Entity):
    """Receipt entity for bulk_assign_role (kind='rolebulk').

    Mirrors the ACTUAL handler return keys verbatim (verified vs
    handlers_rbac.fn_bulk_assign_role): {target_role, total, success, errors}.
    id = target_role (the resolvable handle); title = target_role."""
    target_role: Optional[str] = None
    total: Optional[int] = None
    success: Optional[Any] = None
    errors: Optional[Any] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data["id"] = data.get("target_role") or data.get("id") or "bulk_assign"
            data.setdefault("title", data.get("target_role") or "bulk_assign")
            data.setdefault("kind", "rolebulk")
        return data


# --- scopes ---

class ScopeRecord(sdl.Entity):
    """A single scope as a canonical SDL entity (kind='scope').

    Scopes arrive in two shapes across the surface:
      * a full gateway dict {name, resource, action, source, source_id,
        is_system, display_name, description, id};
      * a BARE string ('billing:read') — the legacy ScopeListResponse declared
        ``scopes: list[str]``.
    The before-validator wraps a bare string into a canonical entity so either
    shape resolves to the same SDL entity (id=title=scope string)."""
    name: Optional[str] = None
    scope: Optional[str] = None
    resource: Optional[str] = None
    action: Optional[str] = None
    source: Optional[str] = None
    source_id: Optional[Any] = None
    is_system: Optional[bool] = None
    display_name: Optional[Any] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        # Bare-string scope -> wrap into a canonical entity.
        if isinstance(data, str):
            return {"id": data, "title": data, "kind": "scope",
                    "scope": data, "name": data}
        if isinstance(data, dict):
            handle = data.get("name") or data.get("scope") or data.get("id") or ""
            data["id"] = data.get("id") or handle
            data.setdefault("title", data.get("display_name") or handle)
            data.setdefault("kind", "scope")
        return data


class ScopeListResponse(sdl.EntityList[ScopeRecord]):
    """list_scopes return shape — a REAL sdl.EntityList[ScopeRecord] (items=[...]).
    Items may be gateway dicts or bare strings (ScopeRecord wraps both).
    NO legacy {scopes:[str],total} wrapper."""
    pass
