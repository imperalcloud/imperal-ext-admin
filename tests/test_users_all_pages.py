"""Every count and search over users reads ALL of them, not the gateway's first page.

Owner report 2026-11-23: the Dashboard showed a wrong number of users. The tenant had 58; the
gateway serves /v1/users 50 per page (200 at most) with the real number in "total", and eight
places in this extension counted or searched the first page only.
"""
from __future__ import annotations

import pathlib

import pytest

import app as admin_app
import panels_sections

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _gateway(total: int, calls: list):
    """A gateway that serves `total` users the way the real one does: by limit and offset."""
    everyone = [{"imperal_id": f"imp_u_{i:04d}", "email": f"u{i}@x.io", "is_active": i % 7 != 0} for i in range(total)]

    async def gw(method, path, data=None, acting=None):
        calls.append(path)
        q = dict(kv.split("=") for kv in path.split("?", 1)[1].split("&"))
        limit, offset = int(q.get("limit", 50)), int(q.get("offset", 0))
        return {"items": everyone[offset:offset + limit], "total": total, "limit": limit, "offset": offset}
    return gw


@pytest.mark.asyncio
@pytest.mark.parametrize("total,pages", [(0, 1), (58, 1), (200, 1), (201, 2), (450, 3)])
async def test_all_users_are_read_whatever_their_number(total, pages):
    calls: list = []
    users = await admin_app._gw_users_all(_gateway(total, calls))
    assert len(users) == total
    assert len({u["imperal_id"] for u in users}) == total      # nobody twice, nobody missing
    assert len(calls) == pages
    assert all("include_inactive=true" in c and "limit=200" in c for c in calls)


@pytest.mark.asyncio
async def test_a_gateway_error_is_handed_back_as_it_came_not_as_an_empty_list():
    async def gw(method, path, data=None, acting=None):
        return {"error": "HTTP 503: db down"}
    assert await admin_app._gw_users_all(gw) == {"error": "HTTP 503: db down"}


@pytest.mark.asyncio
async def test_the_dashboard_and_the_users_list_count_all_58(monkeypatch):
    calls: list = []
    monkeypatch.setattr(panels_sections, "_gw_request", _gateway(58, calls))
    users = await panels_sections._fetch_users_raw()
    assert len(users) == 58


def test_no_code_reads_the_user_list_without_paging():
    """A bare /v1/users?include_inactive=true is the first 50 users only."""
    bare = 'v1/users?include_inactive=true"'
    sources = [p for p in ROOT.glob("*.py") if not p.name.startswith(".")]   # not macOS side files
    offenders = [p.name for p in sources if bare in p.read_text()]
    assert offenders == [], f"these read only the gateway's first page of users: {offenders}"
