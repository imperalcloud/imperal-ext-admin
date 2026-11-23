"""Admin · Dashboard: every number from its own source, a failure shown as a failure.

Owner report 2026-11-23: "the Dashboard shows wrong numbers of users... and not
only". No number on the Dashboard had a test before this file.
"""
from __future__ import annotations

import asyncio
import json

import panels_dashboard as PD
import panels_sections as PS


def _ret(value):
    async def _f(*a, **k):
        return value
    return _f


def _nodes(x):
    if isinstance(x, dict):
        yield x
        for v in x.values():
            yield from _nodes(v)
    elif isinstance(x, (list, tuple)):
        for v in x:
            yield from _nodes(v)


def _stats(tree) -> dict:
    return {n["props"]["label"]: n["props"] for n in _nodes(tree) if n.get("type") == "Stat"}


def _cards(tree) -> list[str]:
    return [n["props"].get("title") for n in _nodes(tree) if n.get("type") == "Card"]


def _text(tree) -> str:
    return json.dumps(tree, default=str, ensure_ascii=False)


class _Ctx:
    user_id = "imp_u_ADMIN"


USERS = [{"imperal_id": f"imp_u_{i}", "is_active": i < 55} for i in range(58)]
ROLES = [{"name": n} for n in ("user", "admin", "whm_stuff", "Private Federals")]
EXTS = ([{"app_id": f"a{i}", "status": "active"} for i in range(30)]
        + [{"app_id": "d1", "status": "draft"}, {"app_id": "d2", "status": "draft"},
           {"app_id": "s1", "status": "suspended"}])
ACTIONS = {"total_actions": 1200, "completed": 900, "failed": 60, "cancelled": 40,
           "partial_failure": 0, "fabrication": 0, "integrity_failure": 0, "month": "2026-11",
           "llm_total_calls": 5000, "llm_total_tokens": 9_000_000,
           "llm_by_model": [{"model": "m1", "calls": 4000}]}
LLM = {"calls": 200, "byollm_calls": 7, "input_tokens": 1000, "output_tokens": 500,
       "failover_calls": 0, "total_latency_ms": 400_000}
BILLING = {"paid": {"paying_with_card": 5, "mrr_cents": 14500, "card_mode_without_card": 2},
           "upcoming": {"buckets": {"next_7d": {"cents": 2900}}}}


def _dash(monkeypatch, *, users=(USERS, ""), roles=(ROLES, ""), exts=(EXTS, []),
          actions=(ACTIONS, ""), llm=(LLM, ""), billing=BILLING, health="Operational") -> dict:
    async def _gw(path):
        return roles if path == "/v1/roles" else llm
    seen = {}

    async def _actions(acting):
        seen["acting"] = acting
        return actions
    monkeypatch.setattr(PD, "_fetch_users_checked", _ret(users))
    monkeypatch.setattr(PD, "_gw_checked", _gw)
    monkeypatch.setattr(PD, "_fetch_extensions_checked", _ret(exts))
    monkeypatch.setattr(PD, "_fetch_action_stats_checked", _actions)
    monkeypatch.setattr(PD, "_fetch_analytics", _ret(billing))
    monkeypatch.setattr(PD, "_check_health", _ret(health) if isinstance(health, str)
                        else (lambda name, url: _ret(health[name])()))
    tree = asyncio.run(PD.build_dashboard(_Ctx())).to_dict()
    tree["_seen"] = seen
    return tree


def test_every_overview_number_is_the_count_of_its_source(monkeypatch):
    tree = _dash(monkeypatch)
    s = _stats(tree)
    assert s["Users"]["value"] == "58" and "Users: 55 active, 3 inactive" in _text(tree)
    assert s["Active users"]["value"] == "55"
    assert s["Roles"]["value"] == "4"
    # drafts and suspended apps are not "extensions on the platform"
    assert s["Active extensions"]["value"] == "30"
    assert "Extensions: 33 in all, of them 2 draft, 1 suspended" in _text(tree)


def test_actions_are_asked_as_the_viewing_admin(monkeypatch):
    """The gateway's door requires user_id; without it every number was 0."""
    assert _dash(monkeypatch)["_seen"]["acting"] == "imp_u_ADMIN"


def test_action_stats_reader_sends_user_id_and_keeps_the_refusal(monkeypatch):
    asked = []

    async def _gw(method, path, *a, **k):
        asked.append(path)
        return {"error": "HTTP 422: user_id field required"}
    monkeypatch.setattr(PS, "_gw_request", _gw)
    assert asyncio.run(PS._fetch_action_stats_checked("imp_u_ADMIN")) == (
        {}, "HTTP 422: user_id field required")
    assert asked == ["/v1/internal/actions/stats?admin=true&user_id=imp_u_ADMIN"]
    assert asyncio.run(PS._fetch_action_stats_checked(""))[1]      # no admin id: said, not asked
    assert len(asked) == 1


def test_success_rate_is_over_ended_actions_and_absent_without_any(monkeypatch):
    tree = _dash(monkeypatch)
    s = _stats(tree)
    assert s["Total Actions"]["value"] == "1200"
    assert s["Success Rate"]["value"] == "90%"                     # 900 of 1000 ended
    assert "900 of 1000 ended actions" in _text(tree)
    assert "Ended otherwise: 40 cancelled" in _text(tree)
    none = dict(ACTIONS, total_actions=0, completed=0, failed=0, cancelled=0)
    assert "Success Rate" not in _stats(_dash(monkeypatch, actions=(none, "")))


def test_llm_today_uses_the_gateway_counters(monkeypatch):
    s = _stats(_dash(monkeypatch))
    assert s["Calls"]["value"] == "200"
    assert s["BYOLLM Calls"]["value"] == "7"
    assert s["Avg Latency"]["value"] == "2.00s"


def test_a_source_that_failed_is_named_and_its_numbers_are_not_drawn(monkeypatch):
    tree = _dash(monkeypatch, users=([], "HTTP 503: db down"),
                 actions=({}, "HTTP 422: user_id field required"),
                 llm=(None, "HTTP 500: redis"), exts=([], ["registry: HTTP 502"]), billing={})
    alert = [n["props"] for n in _nodes(tree) if n.get("type") == "Alert"][0]
    assert alert["variant"] == "error" and alert["title"].startswith("5 source(s)")
    for why in ("HTTP 503: db down", "user_id field required", "HTTP 500: redis",
                "registry: HTTP 502", "Billing"):
        assert why in alert["message"], why
    s = _stats(tree)
    for gone in ("Users", "Active users", "Active extensions", "Total Actions", "Success Rate",
                 "Calls", "MRR committed"):
        assert gone not in s, gone
    assert s["Roles"]["value"] == "4"                              # what answered is still shown
    assert "Revenue" not in _cards(tree)
    assert "5 data source(s) unread" in _text(tree) and "All checks passed" not in _text(tree)


def test_the_status_badge_is_the_result_of_checks(monkeypatch):
    assert "All checks passed" in _text(_dash(monkeypatch))
    down = _dash(monkeypatch, health={"auth_gateway": "Operational", "registry": "Unreachable"})
    assert "A service does not answer" in _text(down) and "All checks passed" not in _text(down)
    assert "Unreachable" in _text(down)


def test_nothing_is_announced_that_was_not_checked(monkeypatch):
    text = _text(_dash(monkeypatch))
    for claim in ("All systems operational", "subsystems operational", "synchronized"):
        assert claim not in text, claim


def test_an_error_dict_from_the_gateway_is_never_read_as_numbers(monkeypatch):
    async def _gw(method, path, *a, **k):
        return {"error": "HTTP 500: boom"}
    monkeypatch.setattr(PS, "_gw_request", _gw)
    assert asyncio.run(PS._gw_checked("/v1/roles")) == (None, "HTTP 500: boom")
    assert asyncio.run(PS._fetch_llm_usage_raw()) == {}


def test_stats_carry_only_what_the_deploy_check_accepts(monkeypatch):
    """5.23.0 was rejected at deploy: ui.Stat(description=...) is not in the
    check's list (label, value, color, icon, trend), though the SDK takes it."""
    import ast
    import pathlib
    allowed = {"label", "value", "color", "icon", "trend"}
    src = (pathlib.Path(PD.__file__)).read_text()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "Stat":
            extra = {k.arg for k in node.keywords} - allowed
            assert not extra, f"line {node.lineno}: ui.Stat({sorted(extra)})"
