# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors.
# Licensed under the AGPL-3.0 License.
"""SDL entity records — USERS & BALANCES domain.

Federal I-EXT-RECORD-FIELD-NAMING-SYMMETRIC: every field name mirrors the
ACTUAL runtime dict key the handler returns (verified against handlers_users.py
and handlers_billing.py). 100% SDL — no legacy plain-BaseModel wrappers; list
returns are real ``sdl.EntityList[T]``.
"""
from __future__ import annotations

from typing import Optional, Any
from pydantic import model_validator

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
    x-sdl='entity-list'). NO legacy {users:[dict],total} wrapper."""
    pass


class ExtensionUsersResponse(sdl.EntityList[UserRecord]):
    """list_extension_users return shape — users who can access an extension,
    as a REAL sdl.EntityList[UserRecord]. The gateway adds an ``access``
    (granted/denied) marker per user; it is not part of the canonical user
    entity, so the handler should keep granted/denied COUNTS in the summary
    string (not as items). NO legacy {users:[dict],total,app_id} wrapper."""
    pass


# --- billing balances ---

class UserBalanceRecord(sdl.Entity):
    """get_user_balance / list_user_balances wallet entity (kind='userbalance').

    ``balance`` is a token count (int), NOT a currency Decimal, so the
    ``money.balance`` (Balanced) facet is deliberately NOT mixed in to avoid
    int->Decimal type drift; kept as the existing plain int field.

    list_user_balances wallet items use only ``{user_id, balance}``;
    get_user_balance additionally returns ``available``, ``holds``,
    ``holds_total`` — all kept verbatim below.
    """
    user_id: Optional[str] = None
    email: Optional[str] = None
    balance: Optional[int] = None
    available: Optional[int] = None
    plan: Optional[str] = None
    cap: Optional[int] = None
    held: Optional[int] = None
    holds: Optional[list[dict]] = None
    holds_total: Optional[int] = None
    # Subscription truth, enriched from the gateway (the canonical billing read —
    # same source the panel + the user's own billing extension show). The Redis
    # wallet alone has no plan/renewal, so get_user_balance now joins them in.
    status: Optional[str] = None
    expires_at: Optional[str] = None
    cancel_at_period_end: Optional[bool] = None
    included_tokens: Optional[int] = None
    # adjust_balance receipt keys (this model is its data_model). The handler
    # returns {user_id, balance, adjustment, reason}; ``adjustment``/``reason``
    # were previously dropped. ``new_balance`` is an additive alias kept for
    # call-sites that read that key (I-EXT-RECORD-FIELD-NAMING-SYMMETRIC).
    adjustment: Optional[Any] = None
    reason: Optional[str] = None
    new_balance: Optional[Any] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data["id"] = data.get("user_id") or data.get("id") or ""
            data.setdefault("title", data.get("email") or data.get("user_id") or "")
            data.setdefault("kind", "userbalance")
        return data


class UserBalancesResponse(sdl.EntityList[UserBalanceRecord]):
    """list_user_balances return shape — a REAL sdl.EntityList[UserBalanceRecord].
    The handler keeps the platform scalars ``total_users`` and
    ``total_tokens_in_circulation`` as extra typed fields below (EntityList is a
    pydantic BaseModel, so additive fields are allowed). NO legacy wrapper."""
    total_users: int = 0
    total_tokens_in_circulation: int = 0
