"""Regression: no more copy-pasted _money / _panel_acting definitions.

Before this test, ``_money`` was defined identically in THREE files
(panels_billing_analytics.py, panels_credits.py, handlers_billing_mode.py)
and ``_panel_acting`` was defined identically in TWO
(panels_billing_analytics.py, panels_credits.py). Both now live in one
place (fmt.py / app.py respectively) and every other caller imports them.

This sweep fails loudly if a future panel/handler file re-introduces its
own copy of either name instead of importing the shared one.
"""
from __future__ import annotations

import ast
import glob


def _files_defining(func_name: str) -> list[str]:
    hits = []
    for fn in sorted(glob.glob("panels_*.py") + glob.glob("handlers_*.py") + ["app.py", "fmt.py"]):
        try:
            tree = ast.parse(open(fn, encoding="utf-8").read())
        except (SyntaxError, FileNotFoundError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
                hits.append(fn)
    return hits


def test_money_is_defined_exactly_once_outside_its_home_module():
    # fmt.py owns `money`; handlers_billing_mode.py keeps a thin `_money`
    # wrapper (different default behaviour on zero, by design -- see
    # fmt.py docstring). No panel file should define its own `_money`
    # anymore -- they must import fmt.money.
    hits = _files_defining("_money")
    assert hits == ["handlers_billing_mode.py"], (
        f"_money should only be (re)defined in handlers_billing_mode.py "
        f"(a deliberate thin wrapper around fmt.money) -- found in: {hits}. "
        "Other files must `from fmt import money as _money`."
    )


def test_acting_is_defined_exactly_once():
    # app.py owns the canonical _acting (the X-Acting-User helper used by
    # write handlers). Was duplicated identically in FIVE handler files
    # before this sweep -- none of them may define their own copy again.
    hits = _files_defining("_acting")
    assert hits == ["app.py"], (
        f"_acting should only be defined in app.py -- found in: {hits}. "
        "Other handler files must `from app import _acting`."
    )


def test_aslist_is_defined_exactly_once():
    # app.py owns the canonical _aslist (gateway list-response normalizer).
    # Was duplicated identically in handlers_admin_reads.py and
    # handlers_email.py before this sweep.
    hits = _files_defining("_aslist")
    assert hits == ["app.py"], (
        f"_aslist should only be defined in app.py -- found in: {hits}. "
        "Other handler files must `from app import _aslist`."
    )


def test_panel_acting_is_defined_exactly_once_outside_its_deliberate_variant():
    # app.py owns the canonical _panel_acting. panels_user_profile.py keeps
    # its own slightly different variant on purpose (documented in both
    # docstrings). No OTHER panel file should define its own copy.
    hits = _files_defining("_panel_acting")
    assert set(hits) == {"app.py", "panels_user_profile.py"}, (
        f"_panel_acting should only be defined in app.py (canonical) and "
        f"panels_user_profile.py (deliberate variant) -- found in: {hits}. "
        "Other files must `from app import _panel_acting`."
    )
