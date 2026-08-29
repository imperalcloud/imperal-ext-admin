"""Regression: every destructive @chat.function must be wired behind a confirm=.

Before this sweep, SEVEN destructive buttons fired instantly with no
confirmation modal at all: suspend_extension, draft_extension,
deny_extension, delete_llm_model_rate, delete_role, deactivate_user (x2
call sites), plus delete_scope and hard_delete_user (x2 call sites) found
in an earlier pass. The worst of these was hard_delete_user -- a
permanent, unrecoverable account wipe that could previously be triggered
by one misclick.

This sweep parses every handlers_*.py for @chat.function(..., action_type=
"destructive") names, then checks every ui.Call(name, ...) site in
panels_*.py for a confirm= argument (including the conditional
dict-spread form `**({"confirm": ...} if cond else {})` used where the
button's action itself is conditional, e.g. Suspend/Restore toggles).
"""
from __future__ import annotations

import glob
import re


def _destructive_function_names() -> list[str]:
    names = []
    for fn in sorted(glob.glob("handlers_*.py")):
        src = open(fn, encoding="utf-8").read()
        for m in re.finditer(
            r'@chat\.function\(\s*"(\w+)"\s*,\s*action_type\s*=\s*"destructive"', src
        ):
            names.append(m.group(1))
    return names


def _call_sites_missing_confirm(name: str) -> list[str]:
    """Return panel files with a ui.Call(name, ...) site lacking confirm=.

    Uses a generous window after the call opener so the conditional
    dict-spread form (confirm hidden inside a **({...} if cond else {}))
    is still detected, not just a literal `confirm=` kwarg.
    """
    missing = []
    for fn in sorted(glob.glob("panels_*.py")):
        src = open(fn, encoding="utf-8").read()
        for m in re.finditer(rf'ui\.Call\(\s*"{name}"', src):
            window = src[m.start():m.start() + 600]
            # Cut the window at the matching top-level close of this Call(...)
            # by tracking paren depth from the opening "(" right after Call.
            depth = 0
            end = len(window)
            started = False
            for i, ch in enumerate(window):
                if ch == "(":
                    depth += 1
                    started = True
                elif ch == ")":
                    depth -= 1
                    if started and depth == 0:
                        end = i + 1
                        break
            call_text = window[:end]
            if "confirm" not in call_text:
                missing.append(fn)
    return missing


def test_every_destructive_action_has_a_confirm_gate():
    destructive = _destructive_function_names()
    assert destructive, "expected to find destructive @chat.function handlers"

    problems = {}
    for name in destructive:
        missing = _call_sites_missing_confirm(name)
        if missing:
            problems[name] = missing

    assert not problems, (
        "These destructive actions have a ui.Call(...) site with no confirm= "
        f"gate (no modal shown before firing): {problems}. Every destructive "
        "button must pass confirm=\"...\" (or the conditional dict-spread form) "
        "so the panel shows a confirmation modal first."
    )


def _danger_buttons_missing_confirm() -> dict[str, list[str]]:
    """Return {file: [line snippets]} for every ui.Button(variant="danger")

    whose on_click has no confirm= gate.

    WHY THIS EXISTS SEPARATELY from the destructive-handler sweep above:
    2026-08-29 found THREE red "danger" buttons (Reject app, Reject payout,
    Reset LLM override) with no confirm modal at all -- invisible to the
    other test because their handlers are declared action_type="write", not
    "destructive". A button's own visual promise ("this is dangerous, look
    red") must be backed by a confirm gate regardless of how its handler
    happens to be classified -- the operator reads the button, not the
    source code.
    """
    problems: dict[str, list[str]] = {}
    for fn in sorted(glob.glob("panels_*.py")):
        src = open(fn, encoding="utf-8").read()
        idx = 0
        n = len(src)
        while True:
            m = re.search(r"ui\.Button\(", src[idx:])
            if not m:
                break
            start = idx + m.start()
            popen = idx + m.end() - 1
            depth = 0
            i = popen
            while i < n:
                if src[i] == "(":
                    depth += 1
                elif src[i] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                i += 1
            block = src[start:i + 1]
            idx = i + 1
            has_danger = 'variant="danger"' in block or "variant='danger'" in block
            if not has_danger:
                continue
            # A ternary variant (danger only on one branch, e.g. toggle
            # buttons) is fine as long as SOME confirm gate is present for
            # that branch -- the conditional dict-spread form used by
            # Suspend/Restore and Deactivate/Activate toggles.
            has_confirm = "confirm=" in block or '"confirm"' in block or "'confirm'" in block
            if not has_confirm:
                line_no = src[:start].count("\n") + 1
                problems.setdefault(fn, []).append(f"line {line_no}")
    return problems


def test_every_danger_variant_button_has_a_confirm_gate():
    problems = _danger_buttons_missing_confirm()
    assert not problems, (
        "These ui.Button(variant=\"danger\") sites have no confirm= gate on "
        f"their on_click (no modal shown before firing): {problems}. A red "
        "danger button makes a visual promise of consequence; back it with "
        "confirm=\"...\" regardless of the handler's own action_type."
    )
