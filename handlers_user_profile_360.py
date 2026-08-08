# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors.
# Licensed under the AGPL-3.0 License.
"""Admin · full 360° user profile + per-user audit activity.

Split from handlers_user_search.py to stay under the 300-LOC ceiling the
extension validator enforces per file.

Both tools are read-only. They aggregate what the platform already knows
about a person — identity, business details, billing address, role and
scopes, subscription, wallet, effective limits and audit trail — into ONE
answer, so an operator never has to chain five lookups by hand.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app import chat, ActionResult, _gw_request
from models_user_search import (
    UserActivityParams,
    UserActivityResponse,
    UserDetailsParams,
    UserProfileRecord,
)
from handlers_user_search import (
    _attrs, _billing_of, _company_of, _name_of, resolve_user_any,
)


async def _gw_safe(path: str) -> dict | None:
    """GET a gateway path, returning None on ANY failure.

    A 360 profile must not die because one downstream service is having a
    bad day: an operator investigating an account needs the identity and
    audit trail even when billing is unreachable. The caller records which
    sections were unavailable and says so honestly in the receipt.
    """
    try:
        out = await _gw_request("GET", path)
    except Exception:
        return None
    if isinstance(out, dict) and out.get("error"):
        return None
    return out if isinstance(out, dict) else None


async def _fetch_user(user_id: str) -> dict:
    """The gateway user record, by imperal_id."""
    raw = await _gw_request("GET", "/v1/users?include_inactive=true")
    users = raw.get("items", raw) if isinstance(raw, dict) else raw
    if isinstance(users, list):
        for u in users:
            if isinstance(u, dict) and (u.get("imperal_id") or u.get("id")) == user_id:
                return u
    return {}


async def _audit_for(user_id: str, hours: int, limit: int = 200) -> tuple[list[dict], str]:
    """This user's audit entries, newest first.

    Returns ``(entries, error)`` — a failing audit read degrades the
    profile to 'activity unavailable' instead of failing the whole call.
    """
    try:
        since = (datetime.now(timezone.utc) - timedelta(hours=max(1, hours))).isoformat()
        raw = await _gw_request("GET", f"/v1/audit?since={since}&limit=500")
    except Exception as exc:                                   # pragma: no cover
        return [], str(exc)

    if isinstance(raw, dict) and raw.get("error"):
        return [], str(raw["error"])
    entries = raw if isinstance(raw, list) else (
        raw.get("entries", raw.get("items", [])) if isinstance(raw, dict) else []
    )
    if not isinstance(entries, list):
        return [], "audit log returned an unexpected shape"

    mine = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        who = (
            e.get("user_id") or e.get("actor") or e.get("imperal_id")
            or e.get("actor_id") or e.get("target_user_id")
            or e.get("acting_user") or ""
        )
        if who == user_id:
            mine.append({
                "timestamp": e.get("timestamp") or e.get("ts") or e.get("created_at") or "",
                "action":    e.get("action") or e.get("event") or "",
                "scope":     e.get("scope") or e.get("resource") or "",
                "user_id":   who,
                "actor":     e.get("actor") or who,
                "detail":    e.get("detail") or e.get("message") or e.get("description") or "",
                "status":    e.get("status") or "",
                "ip":        e.get("ip") or e.get("ip_address") or "",
            })
    mine.sort(key=lambda r: r.get("timestamp") or "", reverse=True)
    return mine[:limit], ""


@chat.function(
    "get_user_details",
    action_type="read",
    data_model=UserProfileRecord,
    id_projection="user",
    description=(
        "The COMPLETE 360° profile of one user, found by imperal_id, email, "
        "name or company: identity and contact, business/tax details, billing "
        "address, role and scopes, account status, subscription, wallet "
        "balance, effective limits and recent activity — in one answer."
    ),
)
async def fn_get_user_details(ctx, params: UserDetailsParams) -> ActionResult:
    """Aggregate everything the platform knows about one person."""
    user_id, err = await resolve_user_any(params.user)
    if err:
        return ActionResult.error(err, retryable=True)

    user = await _fetch_user(user_id)
    if not user:
        return ActionResult.error(f"No user record found for {user_id}.")

    attrs   = _attrs(user)
    company = _company_of(user)
    billing = _billing_of(user)
    unavailable: list[str] = []

    subscription: dict = {}
    wallet: dict = {}
    limits: dict = {}
    if params.include_billing:
        sub = await _gw_safe(f"/v1/billing/internal/subscription/{user_id}")
        if sub is None:
            unavailable.append("subscription")
        else:
            subscription = sub

        bal = await _gw_safe(f"/v1/billing/internal/balance/{user_id}")
        if bal is None:
            unavailable.append("wallet")
        else:
            wallet = bal

        lim = await _gw_safe(f"/v1/billing/internal/user-limits/{user_id}")
        if lim is None:
            unavailable.append("limits")
        else:
            limits = lim

    activity: list[dict] = []
    activity_summary: dict = {}
    if params.include_activity:
        activity, aerr = await _audit_for(user_id, params.activity_hours)
        if aerr:
            unavailable.append("activity")
        else:
            counts: dict[str, int] = {}
            for e in activity:
                a = e.get("action") or "(unknown)"
                counts[a] = counts.get(a, 0) + 1
            activity_summary = {
                "window_hours": params.activity_hours,
                "events":       len(activity),
                "by_action":    counts,
                "latest":       activity[0]["timestamp"] if activity else "",
            }

    data = {
        "imperal_id":    user.get("imperal_id") or user_id,
        "email":         user.get("email"),
        "display_name":  _name_of(user),
        "full_name":     user.get("full_name") or attrs.get("full_name"),
        "nickname":      user.get("nickname") or attrs.get("display_name"),
        "role":          user.get("role"),
        "is_active":     user.get("is_active"),
        "auth_method":   user.get("auth_method"),
        "email_verified": attrs.get("email_verified"),
        "created_at":    user.get("created_at"),
        "last_login":    user.get("last_login"),
        "scopes":        user.get("scopes"),
        "account_type":  attrs.get("account_type") or "personal",
        "company_name":  company.get("company_name") or "",
        "tax_id":        company.get("tax_id_value") or "",
        "tax_id_type":   company.get("tax_id_type") or "",
        "company":       company,
        # Contact / location lifted to the top level as well: an operator
        # asking "what's their phone / where are they" should not have to
        # know these live inside attributes.billing.
        "phone":         billing.get("phone") or "",
        "city":          billing.get("city") or "",
        "country":       billing.get("country") or "",
        "postal_code":   billing.get("postal_code") or "",
        "address_line":  billing.get("address_line1") or billing.get("address") or "",
        "billing_address": billing,
        "subscription":  subscription,
        # The two numbers an operator asks for by name, lifted out of the
        # nested billing payloads.
        "plan":          subscription.get("plan") or "",
        "subscription_status": subscription.get("status") or "",
        "balance":       wallet.get("balance", wallet.get("tokens", 0)) or 0,
        "wallet":        wallet,
        "limits":        limits,
        "activity":      activity,
        "activity_summary": activity_summary,
        "recent_actions_count": len(activity),
        "attributes":    attrs,
        "unavailable":   unavailable,
    }

    who = data["display_name"] or data["email"] or user_id
    bits = [
        f"{who} · {data['email']} · {user_id}",
        f"role={data['role']}",
        "active" if data["is_active"] else "DEACTIVATED",
    ]
    if company.get("company_name"):
        bits.append(f"company={company['company_name']}")
    if subscription.get("plan"):
        bits.append(f"plan={subscription['plan']}")
    if wallet.get("balance") is not None:
        bits.append(f"balance={wallet['balance']}")
    if activity_summary.get("events"):
        bits.append(f"{activity_summary['events']} events/{params.activity_hours}h")
    if unavailable:
        bits.append(f"unavailable: {', '.join(unavailable)}")

    return ActionResult.success(data=data, summary=" · ".join(bits))


@chat.function(
    "get_user_activity",
    action_type="read",
    data_model=UserActivityResponse,
    id_projection="user",
    description=(
        "One user's audit trail — every recorded action with timestamp, scope, "
        "status and IP. Find the user by id, email, name or company. Use to "
        "answer 'what has this user been doing' or to investigate an incident."
    ),
)
async def fn_get_user_activity(ctx, params: UserActivityParams) -> ActionResult:
    """Read the audit log for one user."""
    user_id, err = await resolve_user_any(params.user)
    if err:
        return ActionResult.error(err, retryable=True)

    entries, aerr = await _audit_for(user_id, params.hours, limit=max(1, min(params.limit, 500)))
    if aerr:
        return ActionResult.error(f"Could not read the audit log: {aerr}")

    if params.action:
        needle = params.action.strip().lower()
        entries = [e for e in entries if needle in (e.get("action") or "").lower()]

    counts: dict[str, int] = {}
    for e in entries:
        a = e.get("action") or "(unknown)"
        counts[a] = counts.get(a, 0) + 1
    top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:5]

    if not entries:
        return ActionResult.success(
            data={"items": [], "total": 0, "user_id": user_id,
                  "hours": params.hours, "actions_seen": []},
            summary=(
                f"No recorded activity for {user_id} in the last "
                f"{params.hours}h"
                + (f" matching action {params.action!r}" if params.action else "")
                + "."
            ),
        )

    return ActionResult.success(
        data={"items": entries, "total": len(entries), "user_id": user_id,
              "hours": params.hours, "actions_seen": [a for a, _ in top]},
        summary=(
            f"{len(entries)} event(s) for {user_id} in {params.hours}h · "
            f"top: {', '.join(f'{a}×{n}' for a, n in top) or '—'} · "
            f"latest {entries[0]['timestamp']}"
        ),
    )
