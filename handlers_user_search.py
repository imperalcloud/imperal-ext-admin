# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors.
# Licensed under the AGPL-3.0 License.
"""Admin · user SEARCH, 360° profile and per-user activity.

Why this module exists: the admin extension could LIST users and act on a
user once you already knew their exact id or email, but it could not FIND
a person. An operator asking "who is imp_u_2o4S1CJA4u", "find the user
from Acme Ltd" or "which account belongs to Robert" had no tool for it —
only a private resolver used internally by other handlers.

Everything here is read-only; the existing mutation handlers are untouched.
"""
from __future__ import annotations

from app import chat, ActionResult, _gw_request, _resolve_user_flexible
from models_user_search import (
    FindUsersParams,
    UserActivityParams,
    UserActivityResponse,
    UserDetailsParams,
    UserProfileRecord,
    UserSearchResponse,
)


# ─── field extraction (one place, so search and profile agree) ────────── #

def _attrs(u: dict) -> dict:
    a = u.get("attributes")
    return a if isinstance(a, dict) else {}


def _company_of(u: dict) -> dict:
    c = _attrs(u).get("company")
    return c if isinstance(c, dict) else {}


def _billing_of(u: dict) -> dict:
    b = _attrs(u).get("billing")
    return b if isinstance(b, dict) else {}


def _name_of(u: dict) -> str:
    a = _attrs(u)
    return str(
        u.get("display_name") or a.get("display_name")
        or u.get("full_name") or a.get("full_name")
        or u.get("nickname") or ""
    )


def _company_name_of(u: dict) -> str:
    return str(_company_of(u).get("company_name") or "")


def _identity_haystack(u: dict) -> str:
    """Every identifying string of a user, lowercased, in one blob.

    This is what makes "find by any parameter" real: id, email, all name
    variants, company, tax id, phone and location are searched together,
    so the operator never has to know WHICH field holds the thing they
    remember about the person.
    """
    comp, bill, a = _company_of(u), _billing_of(u), _attrs(u)
    parts = [
        u.get("imperal_id"), u.get("id"), u.get("email"),
        # EVERY name variant, not just the preferred one: a person filed as
        # display_name "Robert Kerr" may be searched for as "Robert J. Kerr",
        # which only exists in attributes.full_name.
        u.get("display_name"), a.get("display_name"),
        u.get("full_name"), a.get("full_name"),
        u.get("nickname"),
        comp.get("company_name"), comp.get("tax_id_value"),
        bill.get("phone"), bill.get("city"), bill.get("country"),
        u.get("role"),
    ]
    return " ".join(str(p) for p in parts if p).lower()


def _matches(u: dict, p: FindUsersParams) -> bool:
    """Every provided criterion must match (logical AND)."""
    if p.query and p.query.strip().lower() not in _identity_haystack(u):
        return False
    if p.email and p.email.strip().lower() not in str(u.get("email") or "").lower():
        return False
    if p.name:
        a = _attrs(u)
        names = " ".join(str(v) for v in (
            u.get("display_name"), a.get("display_name"),
            u.get("full_name"), a.get("full_name"), u.get("nickname"),
        ) if v).lower()
        if p.name.strip().lower() not in names:
            return False
    if p.company:
        comp = _company_of(u)
        blob = f"{comp.get('company_name') or ''} {comp.get('tax_id_value') or ''}".lower()
        if p.company.strip().lower() not in blob:
            return False
    if p.role and str(u.get("role") or "").lower() != p.role.strip().lower():
        return False
    if p.country:
        country = str(_billing_of(u).get("country") or "").lower()
        if p.country.strip().lower() not in country:
            return False
    if p.is_active is not None and bool(u.get("is_active")) is not p.is_active:
        return False
    if p.status:
        want = p.status.strip().lower()
        if want in ("active", "inactive", "deactivated", "disabled"):
            if bool(u.get("is_active")) is not (want == "active"):
                return False
    if p.account_type:
        at = str(_attrs(u).get("account_type") or "personal").lower()
        if at != p.account_type.strip().lower():
            return False
    if p.never_logged_in and u.get("last_login"):
        return False
    return True


def _sort_users(users: list[dict], sort: str) -> list[dict]:
    key = (sort or "name").strip().lower()
    if key == "newest":
        return sorted(users, key=lambda u: str(u.get("created_at") or ""), reverse=True)
    if key == "oldest":
        return sorted(users, key=lambda u: str(u.get("created_at") or ""))
    if key == "last_login":
        return sorted(users, key=lambda u: str(u.get("last_login") or ""), reverse=True)
    if key == "role":
        return sorted(users, key=lambda u: (str(u.get("role") or ""), _name_of(u).lower()))
    return sorted(users, key=lambda u: (_name_of(u).lower() or str(u.get("email") or "").lower()))


def _row(u: dict) -> dict:
    """Projection returned by find_users — identity at a glance."""
    comp, bill = _company_of(u), _billing_of(u)
    return {
        "imperal_id":   u.get("imperal_id") or u.get("id") or "",
        "email":        u.get("email") or "",
        "display_name": _name_of(u),
        "company_name": comp.get("company_name") or "",
        "role":         u.get("role") or "",
        "is_active":    bool(u.get("is_active")),
        "account_type": _attrs(u).get("account_type") or "personal",
        "country":      bill.get("country") or "",
        "phone":        bill.get("phone") or "",
        "created_at":   u.get("created_at") or "",
        "last_login":   u.get("last_login") or "",
        "never_logged_in": not bool(u.get("last_login")),
        "matched_on":   "",
    }


async def resolve_user_any(value: str) -> tuple[str | None, str | None]:
    """Resolve a person from ANY identifying string.

    Order matters: the platform's own resolver runs first (exact
    imperal_id / email / name), so existing behaviour is unchanged and
    cheap. Only if that finds nothing do we widen to the full identity
    haystack -- company name, tax id, phone, city -- which is what lets
    "the user from Acme Industrial" resolve at all.

    Ambiguity is reported, never guessed: two people at the same company
    return an error listing the candidates instead of silently picking one.
    """
    uid, err = await _resolve_user_flexible(value)
    if uid:
        return uid, None

    needle = (value or "").strip().lower()
    if not needle:
        return None, "No user specified."

    users = await _all_users()
    if users is None:
        return None, err or "Failed to fetch users from the gateway."

    hits = [u for u in users if needle in _identity_haystack(u)]
    if not hits:
        return None, err or f"No user matches '{value}'."
    if len(hits) > 1:
        names = ", ".join(
            f"{_name_of(u) or u.get('email') or ''} ({u.get('imperal_id') or u.get('id')})"
            for u in hits[:6]
        )
        return None, (
            f"'{value}' matches {len(hits)} users: {names}. "
            f"Re-run with the exact imperal_id or email."
        )
    only = hits[0]
    return (only.get("imperal_id") or only.get("id") or ""), None


def _matched_on(u: dict, p: FindUsersParams) -> str:
    """Which field actually satisfied the free-text query.

    Telling the operator WHY a row matched turns a list into an answer —
    'matched on company_name' is the difference between a hit and a guess.
    """
    q = (p.query or "").strip().lower()
    if not q:
        return "filter"
    comp, bill = _company_of(u), _billing_of(u)
    for label, value in (
        ("imperal_id", u.get("imperal_id") or u.get("id")),
        ("email", u.get("email")),
        ("name", _name_of(u)),
        ("full_name", _attrs(u).get("full_name") or u.get("full_name")),
        ("nickname", u.get("nickname")),
        ("company_name", comp.get("company_name")),
        ("tax_id", comp.get("tax_id_value")),
        ("phone", bill.get("phone")),
        ("city", bill.get("city")),
        ("country", bill.get("country")),
        ("role", u.get("role")),
    ):
        if value and q in str(value).lower():
            return label
    return "other"


async def _all_users() -> list[dict] | None:
    raw = await _gw_request("GET", "/v1/users?include_inactive=true")
    if isinstance(raw, dict) and raw.get("error"):
        return None
    users = raw.get("items", raw) if isinstance(raw, dict) else raw
    return users if isinstance(users, list) else None


# ─── find_users ───────────────────────────────────────────────────────── #

@chat.function(
    "find_users",
    action_type="read",
    data_model=UserSearchResponse,
    description=(
        "FIND a person in the user base by ANY detail: imperal_id (full or "
        "partial), email, display/full name, nickname, company or business "
        "name, tax id, phone, city, country, role or account type. Also "
        "filters by active/deactivated and never-logged-in. Use this "
        "whenever asked who a user is or to locate an account."
    ),
)
async def fn_find_users(ctx, params: FindUsersParams) -> ActionResult:
    """Search users across every identifying field."""
    users = await _all_users()
    if users is None:
        return ActionResult.error("Failed to fetch users from the gateway.")

    hits = [u for u in users if isinstance(u, dict) and _matches(u, params)]
    hits = _sort_users(hits, params.sort)

    limit = max(1, min(params.limit or 50, 500))
    total = len(hits)
    rows = []
    for u in hits[:limit]:
        row = _row(u)
        row["matched_on"] = _matched_on(u, params)
        rows.append(row)

    criteria = {
        k: v for k, v in {
            "query": params.query, "email": params.email, "name": params.name,
            "company": params.company, "role": params.role,
            "country": params.country, "account_type": params.account_type,
            "is_active": params.is_active,
            "never_logged_in": params.never_logged_in or None,
        }.items() if v not in ("", None, False)
    }

    if total == 0:
        shown = ", ".join(f"{k}={v!r}" for k, v in criteria.items()) or "no criteria"
        return ActionResult.success(
            data={"items": [], "total": 0, "shown": 0,
                  "searched": len(users), "criteria": criteria},
            summary=(
                f"No user matches {shown}. Searched {len(users)} accounts "
                f"(including deactivated)."
            ),
        )

    if total == 1:
        u = rows[0]
        who = u["display_name"] or u["email"] or u["imperal_id"]
        extra = f" · {u['company_name']}" if u["company_name"] else ""
        summary = (
            f"{who}{extra} — {u['email']} · {u['imperal_id']} · role={u['role']} · "
            f"{'active' if u['is_active'] else 'DEACTIVATED'} "
            f"(matched on {u['matched_on']})"
        )
    else:
        summary = (
            f"{total} user(s) match"
            + (f" ({', '.join(f'{k}={v!r}' for k, v in criteria.items())})" if criteria else "")
            + (f"; showing {len(rows)}" if total > len(rows) else "")
        )

    return ActionResult.success(
        data={"items": rows, "total": total, "shown": len(rows),
              "searched": len(users), "criteria": criteria},
        summary=summary,
    )
