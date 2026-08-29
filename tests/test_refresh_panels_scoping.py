"""Regression: write/destructive handlers must scope refresh_panels.

INCIDENT (2026-08-29, admin): clicking Approve in App Review made the loader
spin in the LEFT SIDEBAR while the center content just reloaded whole --
Reject next to it did not do this.

ROOT CAUSE: ``ActionResult.success()`` refreshes ALL panels when
``refresh_panels`` is omitted (see imperal_sdk.types.action_result docstring:
"If not set, ALL panels refresh"). ``fn_review_app``'s reject branch already
set ``refresh_panels=["tools"]``; its approve branch did not -- so approving
an app repainted the entire panel (sidebar included) instead of just the App
Review table. The same gap existed in ``fn_set_access_policy``.

These tests pin both fixes directly from source, and add a repo-wide sweep so
a future write/destructive handler that returns ActionResult.success without
refresh_panels gets caught immediately instead of shipping as another
same-shape UI glitch.
"""
from __future__ import annotations

import ast
import glob
import inspect

import handlers_developer
import handlers_extensions


def test_review_app_approve_scopes_refresh_panels():
    src = inspect.getsource(handlers_developer.review_app)
    # both branches (approve/reject) must scope refresh_panels identically
    assert src.count('refresh_panels=["tools"]') >= 2, (
        "review_app must set refresh_panels on BOTH approve and reject "
        "branches -- omitting it on one refreshes ALL panels (sidebar "
        "spinner + full center reload), which is exactly the reported bug."
    )


def test_set_access_policy_scopes_refresh_panels():
    src = inspect.getsource(handlers_extensions.fn_set_access_policy)
    assert "refresh_panels" in src


def _iter_write_destructive_functions():
    """Yield (filename, function_name, source) for every @chat.function whose
    action_type is write or destructive, across every handlers_*.py module.
    Parsed with ast -- not regex -- so nested defs / decorators can't confuse it.
    """
    for fn in sorted(glob.glob("handlers_*.py")):
        src = open(fn, encoding="utf-8").read()
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        lines = src.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            action_type = None
            for dec in node.decorator_list:
                if not (isinstance(dec, ast.Call) and
                        getattr(dec.func, "attr", getattr(dec.func, "id", "")) == "function"):
                    continue
                for kw in dec.keywords:
                    if kw.arg == "action_type" and isinstance(kw.value, ast.Constant):
                        action_type = kw.value.value
            if action_type not in ("write", "destructive"):
                continue
            body_src = "\n".join(lines[node.lineno - 1:node.end_lineno])
            yield fn, node.name, body_src


def test_no_write_or_destructive_handler_silently_refreshes_everything():
    """Every ActionResult.success(...) inside a write/destructive handler
    must be reachable to a refresh_panels= somewhere in the same function
    body. A handler with NO ActionResult.success at all (pure error paths,
    or delegates to a shared helper that already sets it) is fine either way
    -- we only flag a handler that both succeeds AND never scopes its refresh.
    """
    unscoped = []
    for fn, name, body_src in _iter_write_destructive_functions():
        if "ActionResult.success(" not in body_src:
            continue
        if "refresh_panels" in body_src:
            continue
        unscoped.append(f"{fn}::{name}")

    assert not unscoped, (
        "write/destructive handler(s) return ActionResult.success without "
        "ever setting refresh_panels in the SAME function body -- this "
        "refreshes ALL panels by default (sidebar spinner + full reload). "
        f"Offenders: {unscoped}"
    )
