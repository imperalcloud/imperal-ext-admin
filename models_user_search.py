# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors.
# Licensed under the AGPL-3.0 License.
"""Admin · SDL records for user SEARCH and the 360° user profile.

Federal I-EXT-RECORD-FIELD-NAMING-SYMMETRIC: every field name mirrors the
ACTUAL runtime dict key the handler returns (verified against
handlers_user_search.py).

Kept in its own module so models_users.py stays well under the 300-LOC
extension-validator ceiling.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator

from imperal_sdk import sdl


# ─── params ───────────────────────────────────────────────────────────── #

class FindUsersParams(BaseModel):
    """Search the user base by ANY identifying detail.

    A single ``query`` is matched against every identity field at once —
    imperal_id, email, display name, full name, nickname, company /
    business name, tax id, phone, city and country. That is the normal
    way to use it ("find me Robert", "who is imp_u_2o4S…", "the user from
    Acme Ltd"). The structured filters below narrow the result further
    and can be combined.
    """
    query: str = Field(
        default="",
        description=(
            "Free-text search across imperal_id, email, display name, full "
            "name, nickname, company name, tax id, phone, city and country. "
            "Case-insensitive substring match. Omit to list everyone."
        ),
    )
    email: str = Field(
        default="",
        description="Match the email field specifically (substring, case-insensitive).",
    )
    name: str = Field(
        default="",
        description="Match display name / full name / nickname specifically.",
    )
    company: str = Field(
        default="",
        description="Match the business/company name or tax id specifically.",
    )
    status: str = Field(
        default="",
        description=(
            "Match account state in words: 'active', 'inactive' "
            "(= deactivated/disabled), or 'never_logged_in'."
        ),
    )
    role: str = Field(
        default="",
        description="Only users with this exact role, e.g. 'admin', 'user', 'developer'.",
    )
    country: str = Field(
        default="",
        description="Only users whose billing country matches (substring).",
    )
    is_active: Optional[bool] = Field(
        default=None,
        description="True = only active accounts, False = only deactivated. Omit for both.",
    )
    account_type: str = Field(
        default="",
        description="Only this account type, e.g. 'personal' or 'business'.",
    )
    never_logged_in: bool = Field(
        default=False,
        description="Only accounts that have NEVER logged in.",
    )
    sort: str = Field(
        default="",
        description=(
            "Sort order: 'name' (default), 'newest', 'oldest', "
            "'last_login', 'role'."
        ),
    )
    limit: int = Field(
        default=50,
        description="Max rows to return (1-500). Use a high value when counting.",
    )


class UserDetailsParams(BaseModel):
    """Identify one user for the full 360° profile."""
    user: str = Field(
        description=(
            "The user — imperal_id, email, display name, company name, or any "
            "unambiguous fragment of those. Resolved flexibly; an ambiguous "
            "match returns the candidates instead of guessing."
        ),
    )
    include_billing: bool = Field(
        default=True,
        description="Also fetch wallet balance, plan and subscription state.",
    )
    include_activity: bool = Field(
        default=True,
        description="Also fetch recent audit-log activity for this user.",
    )
    activity_hours: int = Field(
        default=168,
        description="How far back to read activity, in hours (default 168 = 7 days).",
    )


class UserActivityParams(BaseModel):
    """Read one user's audit trail."""
    user: str = Field(
        description="The user — imperal_id, email, name, or a fragment of any.",
    )
    hours: int = Field(
        default=168,
        description="Look-back window in hours (default 168 = 7 days).",
    )
    action: str = Field(
        default="",
        description="Only entries whose action matches this (substring), e.g. 'login', 'delete'.",
    )
    scope: str = Field(
        default="",
        description="Only entries in this scope, e.g. 'billing', 'automations', 'users'.",
    )
    limit: int = Field(
        default=100,
        description="Max entries to return (1-200), newest first.",
    )


# ─── records ──────────────────────────────────────────────────────────── #

class UserSearchRecord(sdl.Entity):
    """One matched user, enriched with the identity fields a human actually
    searches by (company, phone, country) lifted out of ``attributes``.

    The raw gateway fields are kept verbatim alongside, so nothing is lost.
    """
    imperal_id: Optional[str] = None
    email: Optional[Any] = None
    display_name: Optional[Any] = None
    full_name: Optional[Any] = None
    nickname: Optional[Any] = None
    role: Optional[Any] = None
    is_active: Optional[Any] = None
    account_type: Optional[str] = None
    company_name: Optional[str] = None
    tax_id: Optional[str] = None
    phone: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    created_at: Optional[Any] = None
    last_login: Optional[Any] = None
    never_logged_in: Optional[bool] = None
    email_verified: Optional[Any] = None
    auth_method: Optional[Any] = None
    matched_on: Optional[list[str]] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data["id"] = data.get("imperal_id") or data.get("id") or ""
            data.setdefault(
                "title",
                data.get("display_name") or data.get("full_name")
                or data.get("email") or data.get("imperal_id") or "",
            )
            data.setdefault("kind", "user")
        return data


class UserSearchResponse(sdl.EntityList[UserSearchRecord]):
    """find_users return shape — matched users plus what was searched."""
    total: int = 0
    total_scanned: int = 0
    truncated: bool = False
    filter: dict = Field(default_factory=dict)


class UserActivityEntry(sdl.Entity):
    """One audit-log entry attributed to a user."""
    entry_id: Optional[str] = None
    timestamp: Optional[str] = None
    action: Optional[str] = None
    scope: Optional[str] = None
    actor: Optional[str] = None
    target: Optional[str] = None
    detail: Optional[Any] = None
    ip: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data.setdefault("id", str(data.get("entry_id") or data.get("timestamp") or ""))
            act = data.get("action") or "activity"
            data.setdefault("title", f"{act} · {data.get('timestamp', '')}")
            data.setdefault("kind", "auditentry")
        return data


class UserActivityResponse(sdl.EntityList[UserActivityEntry]):
    """get_user_activity return shape."""
    user_id: str = ""
    total: int = 0
    hours: int = 0
    actions_seen: list[str] = Field(default_factory=list)


class UserProfileRecord(sdl.Entity):
    """The complete 360° picture of one user: identity, business details,
    billing address, role/scopes, subscription, wallet and recent activity.

    Every section is optional — a missing sub-system degrades to an empty
    dict rather than failing the whole read.
    """
    imperal_id: Optional[str] = None
    email: Optional[Any] = None
    display_name: Optional[Any] = None
    full_name: Optional[Any] = None
    nickname: Optional[Any] = None
    role: Optional[Any] = None
    is_active: Optional[Any] = None
    auth_method: Optional[Any] = None
    email_verified: Optional[Any] = None
    created_at: Optional[Any] = None
    last_login: Optional[Any] = None
    scopes: Optional[Any] = None
    account_type: Optional[str] = None
    company_name: Optional[str] = None
    tax_id: Optional[str] = None
    tax_id_type: Optional[str] = None
    company: dict = Field(default_factory=dict)
    phone: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    postal_code: Optional[str] = None
    address_line: Optional[str] = None
    billing_address: dict = Field(default_factory=dict)
    subscription: dict = Field(default_factory=dict)
    plan: Optional[str] = None
    subscription_status: Optional[str] = None
    balance: int = 0
    wallet: dict = Field(default_factory=dict)
    limits: dict = Field(default_factory=dict)
    activity: list[dict] = Field(default_factory=list)
    recent_actions_count: int = 0
    activity_summary: dict = Field(default_factory=dict)
    attributes: dict = Field(default_factory=dict)
    unavailable: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data["id"] = data.get("imperal_id") or data.get("id") or ""
            data.setdefault(
                "title",
                data.get("display_name") or data.get("full_name")
                or data.get("email") or data.get("imperal_id") or "",
            )
            data.setdefault("kind", "user")
        return data
