"""Functional tests for admin user search / 360° profile / activity.

Covers exactly what the operator asked for: find a person by id, by email,
by name, by company name — or by any parameter at once — and then get every
detail and every log entry about them.
"""
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app as _app  # noqa: E402
import handlers_user_search as hs  # noqa: E402
import handlers_user_profile_360 as hp  # noqa: E402


# ─── fixture data (shaped like the real gateway payload) ──────────────── #

ROBERT = {
    "imperal_id": "imp_u_2o4S1CJA4u",
    "id": "row-1",
    "email": "robert.kerr@acme-industrial.com",
    "display_name": "Robert Kerr",
    "role": "user",
    "is_active": True,
    "last_login": "2026-08-07T21:10:00Z",
    "created_at": "2026-03-02T10:00:00Z",
    "scopes": ["chat:use"],
    "attributes": {
        "full_name": "Robert J. Kerr",
        "email_verified": True,
        "company": {"company_name": "Acme Industrial Ltd", "tax_id_value": "GB123456789"},
        "billing": {"phone": "+44 20 7946 0000", "city": "Manchester", "country": "GB"},
    },
}

MARIA = {
    "imperal_id": "imp_u_9xKmQ2ZzLp",
    "id": "row-2",
    "email": "maria@nordwind.dk",
    "display_name": "Maria Sørensen",
    "role": "admin",
    "is_active": True,
    "created_at": "2026-01-15T08:00:00Z",
    "attributes": {
        "company": {"company_name": "Nordwind ApS"},
        "billing": {"country": "DK", "city": "Copenhagen"},
    },
}

DORMANT = {
    "imperal_id": "imp_u_dormant001",
    "id": "row-3",
    "email": "old.account@example.org",
    "display_name": "Dormant Account",
    "role": "user",
    "is_active": False,
    "created_at": "2025-11-01T08:00:00Z",
    "attributes": {},
}

USERS = [ROBERT, MARIA, DORMANT]

AUDIT = [
    {"user_id": "imp_u_2o4S1CJA4u", "action": "user.login", "timestamp": "2026-08-07T21:10:00Z",
     "resource": "session", "ip": "1.2.3.4"},
    {"user_id": "imp_u_2o4S1CJA4u", "action": "billing.topup", "timestamp": "2026-08-07T20:00:00Z",
     "resource": "wallet"},
    {"actor_id": "imp_u_9xKmQ2ZzLp", "action": "admin.role_change", "timestamp": "2026-08-07T19:00:00Z",
     "resource": "user:imp_u_dormant001"},
]


@pytest.fixture
def gw(monkeypatch):
    """Fake auth-gw: serves users, audit, billing and limits."""
    calls = []

    async def _fake(method, path, data=None, acting=None):
        calls.append((method, path))
        if path.startswith("/v1/users"):
            return {"items": USERS}
        if path.startswith("/v1/audit"):
            return {"entries": AUDIT}
        if "/billing/internal/subscription/" in path:
            return {"plan": "Pro", "status": "active", "period_end": "2026-09-01"}
        if "/billing/internal/balance/" in path:
            return {"balance": 12500}
        if "/billing/internal/user-limits/" in path:
            return {"daily_token_cap": 100000}
        return {}

    for mod in (hs, hp, _app):
        monkeypatch.setattr(mod, "_gw_request", _fake, raising=False)
    return calls


def _ids(res):
    return {i.get("imperal_id") for i in res.data["items"]}


# ─── find_users ───────────────────────────────────────────────────────── #

@pytest.mark.asyncio
@pytest.mark.parametrize("params, expected", [
    # by id — full and partial
    (dict(query="imp_u_2o4S1CJA4u"), {"imp_u_2o4S1CJA4u"}),
    (dict(query="2o4S1CJA"),         {"imp_u_2o4S1CJA4u"}),
    # by email — full, local part, and domain
    (dict(query="robert.kerr@acme-industrial.com"), {"imp_u_2o4S1CJA4u"}),
    (dict(query="nordwind.dk"),                     {"imp_u_9xKmQ2ZzLp"}),
    (dict(email="maria"),                           {"imp_u_9xKmQ2ZzLp"}),
    # by name — display name, full name, case-insensitive
    (dict(query="Robert"),      {"imp_u_2o4S1CJA4u"}),
    (dict(query="robert j."),   {"imp_u_2o4S1CJA4u"}),
    (dict(name="sørensen"),     {"imp_u_9xKmQ2ZzLp"}),
    # by company — the capability that did not exist before
    (dict(query="Acme Industrial"), {"imp_u_2o4S1CJA4u"}),
    (dict(company="acme"),          {"imp_u_2o4S1CJA4u"}),
    (dict(company="Nordwind"),      {"imp_u_9xKmQ2ZzLp"}),
    (dict(query="GB123456789"),     {"imp_u_2o4S1CJA4u"}),   # tax id
    # by other parameters
    (dict(query="+44 20 7946 0000"), {"imp_u_2o4S1CJA4u"}),  # phone
    (dict(query="Copenhagen"),       {"imp_u_9xKmQ2ZzLp"}),  # city
    (dict(country="GB"),             {"imp_u_2o4S1CJA4u"}),
    (dict(role="admin"),             {"imp_u_9xKmQ2ZzLp"}),
    (dict(status="inactive"),        {"imp_u_dormant001"}),
])
async def test_find_users_by_every_parameter(gw, params, expected):
    from models_user_search import FindUsersParams
    res = await hs.fn_find_users(None, FindUsersParams(**params))
    assert res.status == "success"
    assert _ids(res) == expected


@pytest.mark.asyncio
async def test_find_users_filters_combine(gw):
    from models_user_search import FindUsersParams
    # active users in GB -> Robert only (Maria is DK, Dormant is inactive)
    res = await hs.fn_find_users(None, FindUsersParams(country="GB", status="active"))
    assert _ids(res) == {"imp_u_2o4S1CJA4u"}


@pytest.mark.asyncio
async def test_find_users_reports_company_and_identity_in_results(gw):
    from models_user_search import FindUsersParams
    res = await hs.fn_find_users(None, FindUsersParams(query="acme"))
    row = res.data["items"][0]
    assert row["company_name"] == "Acme Industrial Ltd"
    assert row["email"] == "robert.kerr@acme-industrial.com"
    assert row["imperal_id"] == "imp_u_2o4S1CJA4u"
    assert row["display_name"] == "Robert Kerr"
    assert row["is_active"] is True


@pytest.mark.asyncio
async def test_unknown_person_is_an_honest_empty_result(gw):
    from models_user_search import FindUsersParams
    res = await hs.fn_find_users(None, FindUsersParams(query="nobody-by-that-name"))
    assert res.status == "success"
    assert res.data["items"] == []
    assert res.data["total"] == 0
    assert "no" in res.summary.lower() or "0" in res.summary


@pytest.mark.asyncio
async def test_inactive_users_are_included_by_default(gw):
    from models_user_search import FindUsersParams
    res = await hs.fn_find_users(None, FindUsersParams())
    assert "imp_u_dormant001" in _ids(res), "a deactivated account must still be findable"


# ─── get_user_details (360°) ──────────────────────────────────────────── #

@pytest.mark.asyncio
async def test_profile_is_reachable_by_id_email_name_and_company(gw):
    from models_user_search import UserDetailsParams
    for selector in ("imp_u_2o4S1CJA4u", "robert.kerr@acme-industrial.com",
                     "Robert Kerr", "Acme Industrial"):
        res = await hp.fn_get_user_details(None, UserDetailsParams(user=selector))
        assert res.status == "success", f"failed to resolve by {selector!r}"
        assert res.data["imperal_id"] == "imp_u_2o4S1CJA4u"


@pytest.mark.asyncio
async def test_profile_carries_every_section(gw):
    from models_user_search import UserDetailsParams
    res = await hp.fn_get_user_details(None, UserDetailsParams(user="imp_u_2o4S1CJA4u"))
    d = res.data
    # identity
    assert d["email"] == "robert.kerr@acme-industrial.com"
    assert d["full_name"] == "Robert J. Kerr"
    assert d["email_verified"] is True
    # business
    assert d["company_name"] == "Acme Industrial Ltd"
    assert d["company"]["tax_id_value"] == "GB123456789"
    assert d["tax_id"] == "GB123456789"
    # contact / location
    assert d["phone"] == "+44 20 7946 0000"
    assert d["country"] == "GB"
    assert d["city"] == "Manchester"
    # access
    assert d["role"] == "user"
    assert d["is_active"] is True
    assert d["scopes"] == ["chat:use"]
    # billing
    assert d["plan"] == "Pro"
    assert d["balance"] == 12500
    # activity
    assert d["recent_actions_count"] >= 2


@pytest.mark.asyncio
async def test_ambiguous_selector_asks_instead_of_guessing(gw):
    """Two people match 'a' — the tool must NOT silently pick one."""
    from models_user_search import UserDetailsParams
    res = await hp.fn_get_user_details(None, UserDetailsParams(user="o"))
    assert res.status == "error"
    assert "match" in (res.error or "").lower()


@pytest.mark.asyncio
async def test_unknown_user_profile_is_a_clear_error(gw):
    from models_user_search import UserDetailsParams
    res = await hp.fn_get_user_details(None, UserDetailsParams(user="ghost@nowhere.tld"))
    assert res.status == "error"
    assert "no user" in (res.error or "").lower() or "not" in (res.error or "").lower()


@pytest.mark.asyncio
async def test_profile_survives_billing_outage(gw, monkeypatch):
    """A billing hiccup must not blank the whole profile."""
    async def _flaky(method, path, data=None, acting=None):
        if path.startswith("/v1/users"):
            return {"items": USERS}
        if path.startswith("/v1/audit"):
            return {"entries": AUDIT}
        raise RuntimeError("billing down")

    for mod in (hs, hp, _app):
        monkeypatch.setattr(mod, "_gw_request", _flaky, raising=False)

    from models_user_search import UserDetailsParams
    res = await hp.fn_get_user_details(None, UserDetailsParams(user="imp_u_2o4S1CJA4u"))
    assert res.status == "success"
    assert res.data["email"] == "robert.kerr@acme-industrial.com"


# ─── get_user_activity (logs) ─────────────────────────────────────────── #

@pytest.mark.asyncio
async def test_activity_returns_that_users_log_entries(gw):
    from models_user_search import UserActivityParams
    res = await hp.fn_get_user_activity(None, UserActivityParams(user="imp_u_2o4S1CJA4u"))
    assert res.status == "success"
    assert res.data["total"] == 2
    actions = {e["action"] for e in res.data["items"]}
    assert actions == {"user.login", "billing.topup"}


@pytest.mark.asyncio
async def test_activity_matches_actor_id_too(gw):
    """Admin actions are recorded under actor_id, not user_id."""
    from models_user_search import UserActivityParams
    res = await hp.fn_get_user_activity(None, UserActivityParams(user="imp_u_9xKmQ2ZzLp"))
    assert res.data["total"] == 1
    assert res.data["items"][0]["action"] == "admin.role_change"


@pytest.mark.asyncio
async def test_activity_can_filter_by_action(gw):
    from models_user_search import UserActivityParams
    res = await hp.fn_get_user_activity(
        None, UserActivityParams(user="imp_u_2o4S1CJA4u", action="billing"),
    )
    assert res.data["total"] == 1
    assert res.data["items"][0]["action"] == "billing.topup"


@pytest.mark.asyncio
async def test_activity_is_newest_first(gw):
    from models_user_search import UserActivityParams
    res = await hp.fn_get_user_activity(None, UserActivityParams(user="imp_u_2o4S1CJA4u"))
    stamps = [e["timestamp"] for e in res.data["items"]]
    assert stamps == sorted(stamps, reverse=True)


@pytest.mark.asyncio
async def test_quiet_user_gets_an_honest_empty_log(gw):
    from models_user_search import UserActivityParams
    res = await hp.fn_get_user_activity(None, UserActivityParams(user="imp_u_dormant001"))
    assert res.status == "success"
    assert res.data["items"] == []
