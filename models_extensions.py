# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors.
# Licensed under the AGPL-3.0 License.
"""SDL entity records — EXTENSIONS domain.

Federal I-EXT-RECORD-FIELD-NAMING-SYMMETRIC: field names mirror the ACTUAL
registry/gateway dict keys (verified against handlers_extensions.py +
panels_extensions.py). 100% SDL — list returns are real ``sdl.EntityList[T]``.
"""
from __future__ import annotations

from typing import Optional, Any
from pydantic import model_validator

from imperal_sdk import sdl


# --- extension list item ---

class ExtensionRecord(sdl.Entity):
    """A single registered extension as a canonical SDL entity
    (kind='extension'): id=app_id, title=display_name (or name).

    Registry app dict keys (verified vs panels_extensions._build_expanded_content
    and the list-item builder) kept verbatim. ``version`` stays a plain field
    (the registry returns it as a string) rather than mixing the Versioned facet,
    matching the additive non-breaking SDL migration policy."""
    app_id: Optional[str] = None
    name: Optional[str] = None
    display_name: Optional[Any] = None
    category: Optional[str] = None
    version: Optional[Any] = None
    tools: Optional[list] = None
    required_scopes: Optional[list[str]] = None
    scopes: Optional[list[str]] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            # Canonical id = app_id; OVERWRITE with app_id when present (it is
            # the registry-canonical handle), else fall back to gateway id.
            data["id"] = data.get("app_id") or data.get("id") or ""
            data.setdefault(
                "title",
                data.get("display_name") or data.get("name")
                or data.get("app_id") or "",
            )
            data.setdefault("kind", "extension")
        return data


class ExtensionsListResponse(sdl.EntityList[ExtensionRecord]):
    """list_extensions return shape — a REAL sdl.EntityList[ExtensionRecord]
    (items=[...]). NO legacy {extensions:[dict],total} wrapper."""
    pass


# --- single extension config / policy / settings receipt ---

class ExtensionConfigRecord(sdl.Entity, sdl.Versioned):
    """get_extension_config return shape — a single extension config entity.

    ``version`` is provided by the Versioned facet (role ``core.version``);
    ``status`` is the core Entity field (role ``core.status``)."""
    app_id: Optional[str] = None
    config: Optional[dict] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data["id"] = data.get("app_id") or data.get("id") or ""
            data.setdefault("title", data.get("app_id") or "")
            data.setdefault("kind", "extension")
        return data


class AccessPolicyRecord(sdl.Entity):
    """get_access_policy return shape — a single extension access-policy entity.

    Field names match the handler's actual data keys: ``policy`` and
    ``role_resolution`` (NOT the older per_role/per_user/resolved guesses)."""
    app_id: Optional[str] = None
    policy: Optional[dict] = None
    role_resolution: Optional[list] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data["id"] = data.get("app_id") or data.get("id") or ""
            data.setdefault("title", data.get("app_id") or "")
            data.setdefault("kind", "extension")
        return data


class ExtSettingsReceipt(sdl.Entity):
    """Receipt entity for extension write tools that return a small confirmation
    payload keyed by app_id (update_extension_config, update_skeleton_ttl,
    suspend/activate_extension, set_access_policy, deny/allow_extension,
    save_ext_* receipts) — kind='extension'. Keeps every observed receipt key
    verbatim so panels/$REF read the same data. Reuse this rather than inventing
    a per-verb receipt."""
    app_id: Optional[str] = None
    updated: Optional[bool] = None
    ttl: Optional[int] = None
    status: Optional[str] = None
    previous: Optional[str] = None
    verified: Optional[bool] = None
    policy: Optional[dict] = None
    denied: Optional[list] = None
    removed: Optional[list] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data["id"] = data.get("app_id") or data.get("id") or ""
            data.setdefault("title", data.get("app_id") or "")
            data.setdefault("kind", "extension")
        return data
