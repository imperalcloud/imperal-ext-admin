"""Regression: LLM Pricing must support a GUARANTEED (hard) delete.

INCIDENT (2026-08-29, admin): "у меня еще есть LLM Pricing страница ... и
фишка в том, что я не могу удалять, а мне многое что оттуда нужно удалить,
причем удаление должно быть гарантированным, чтобы исчезало и из базы и из
Редис ... в общем полноценное правильное удаление".

BEFORE: delete_llm_model_rate only ever called DELETE .../model-rates/{id}
with no query flag, and the gateway route only ever did
`UPDATE ... SET is_available=false` — there was no way to actually remove a
row from llm_model_rates. Rows accumulated forever.

FIX: a new hard_delete_llm_model_rate function calls the SAME endpoint with
`hard=true`, which the gateway route now uses to run a real DELETE instead
of the soft UPDATE. There is no Redis step because llm_model_rates has no
Redis cache and no sync job (imperal_kernel/billing/resolver.py documents
this explicitly) — deleting the one row IS the complete, guaranteed delete.

These tests verify (from THIS repo, source-inspection style, matching the
established pattern in test_llm_single_key_qwen.py): both delete paths share
one HTTP-calling helper (no duplicated request/error-handling logic), the
hard path passes hard=true, the soft path does not, and the panel offers a
destructive confirm before calling the hard path.
"""
from __future__ import annotations

import inspect

import handlers_pricing
import panels_pricing


def test_soft_and_hard_delete_share_one_http_helper():
    """No duplicated request/error-handling logic between the two paths."""
    soft_src = inspect.getsource(handlers_pricing.fn_delete_llm_model_rate)
    hard_src = inspect.getsource(handlers_pricing.fn_hard_delete_llm_model_rate)
    assert "_call_delete_rate" in soft_src
    assert "_call_delete_rate" in hard_src
    # neither handler builds its own httpx client / URL — that lives in the
    # shared helper exactly once.
    assert "shared_http" not in soft_src
    assert "shared_http" not in hard_src


def test_hard_delete_passes_hard_true_soft_delete_does_not():
    helper_src = inspect.getsource(handlers_pricing._call_delete_rate)
    assert '"hard": "true"' in helper_src
    hard_src = inspect.getsource(handlers_pricing.fn_hard_delete_llm_model_rate)
    assert "hard=True" in hard_src
    soft_src = inspect.getsource(handlers_pricing.fn_delete_llm_model_rate)
    assert "hard=False" in soft_src


def test_hard_delete_is_marked_destructive_and_documented_no_redis_step():
    # action_type="destructive" is what makes the host demand confirmation
    # even if a caller forgot to pass confirm= explicitly.
    src = inspect.getsource(handlers_pricing)
    assert 'action_type="destructive"' in src
    hard_fn_src = inspect.getsource(handlers_pricing.fn_hard_delete_llm_model_rate)
    assert "no Redis" in hard_fn_src or "no Redis cache" in hard_fn_src


def test_panel_offers_hard_delete_with_destructive_confirm_text():
    src = inspect.getsource(panels_pricing)
    assert "hard_delete_llm_model_rate" in src
    # host-level confirm= gate (same pattern as panels_extensions.py Purge) —
    # this is the "guaranteed, but only after the admin explicitly confirms"
    # requirement, without inventing a second modal mechanism in this app.
    assert "confirm=(f\"Permanently delete the rate row" in src
    assert "cannot be undone" not in src.lower() or "for good" in src
