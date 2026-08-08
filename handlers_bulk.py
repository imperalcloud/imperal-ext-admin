"""Admin · bulk user operations.

Admin work is inherently plural — "deactivate these five", "credit everyone
who hit the bug", "reset those two sessions". Before this module the only
bulk tool was bulk_assign_role, so every other mass action meant calling a
single-user tool N times: N confirmation gates, N round trips, and one bad
identifier aborting the whole intent.

Every handler here follows the same contract:

  * targets are resolved FIRST, flexibly (imperal_id, email, display name or
    a partial of any) via the same resolver the single-user tools use, so a
    bulk call is never stricter about naming than its single counterpart;
  * duplicates collapse on the RESOLVED imperal_id, so passing both an email
    and an id for one person acts once, not twice;
  * partial success is reported as success — the caller always learns which
    targets went through and which did not, instead of an error that hides
    the work that actually happened.
"""
from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel, Field

from app import chat, ActionResult, _gw_request, _resolve_user_flexible

log = logging.getLogger("admin.handlers_bulk")

_MAX_TARGETS = 100


# ─── Models ───────────────────────────────────────────────────────────── #

class BulkUsersParams(BaseModel):
    """Target SEVERAL users at once."""
    user_ids: list[str] = Field(
        description=(
            "The users to act on. Each entry may be an imperal_id (imp_u_*), "
            "an email, a display name, or a partial of any of those — they "
            "are resolved the same way the single-user tools resolve them. "
            "Pass EVERY user the admin named in ONE call; do not loop."
        ),
        min_length=1,
        max_length=_MAX_TARGETS,
    )


class BulkAdjustBalanceParams(BulkUsersParams):
    """Credit or deduct the SAME token amount for several users."""
    amount: int = Field(
        description=(
            "Token amount applied to EACH listed user "
            "(positive = credit, negative = deduct)."
        ),
    )
    reason: str = Field(
        default="admin_bulk_adjustment",
        description="Reason recorded for every adjustment in the batch.",
    )


class BulkSetActiveParams(BulkUsersParams):
    """Activate or deactivate several users."""
    is_active: bool = Field(
        description=(
            "True = reactivate the listed users, "
            "False = deactivate them (reversible)."
        ),
    )


class BulkReceipt(BaseModel):
    """Uniform outcome shape for every bulk admin action."""
    model_config = {"extra": "allow"}

    action: str = ""
    succeeded: list[str] = Field(default_factory=list)
    failed: list[str] = Field(default_factory=list)
    total: int = 0
    success_count: int = 0
    failure_count: int = 0


# ─── Shared plumbing ──────────────────────────────────────────────────── #

async def _resolve_targets(raw: list[str]) -> tuple[list[tuple[str, str]], list[str]]:
    """Resolve every identifier up front.

    Returns ``(targets, failures)`` where targets is ``(original, imperal_id)``
    de-duped on the resolved id, and failures are ready-to-show strings.
    Resolving before acting means an unknown name is reported as one clean
    line instead of aborting the batch halfway through, having already
    mutated some accounts.
    """
    targets: list[tuple[str, str]] = []
    failures: list[str] = []
    seen: set[str] = set()
    for item in raw:
        term = (item or "").strip()
        if not term:
            continue
        uid, err = await _resolve_user_flexible(term)
        if not uid:
            failures.append(f"{term} — {err or 'not found'}")
            continue
        if uid in seen:
            continue
        seen.add(uid)
        targets.append((term, uid))
    return targets, failures


def _receipt(action: str, ok: list[str], failed: list[str], **extra) -> ActionResult:
    """One uniform shape + honest summary for every bulk action."""
    data = {
        "action": action,
        "succeeded": ok,
        "failed": failed,
        "total": len(ok) + len(failed),
        "success_count": len(ok),
        "failure_count": len(failed),
        **extra,
    }
    if ok and not failed:
        summary = f"{action}: {len(ok)} ok — {', '.join(ok)}."
    elif ok and failed:
        summary = (
            f"{action}: {len(ok)} ok ({', '.join(ok)}); "
            f"{len(failed)} failed — {'; '.join(failed)}."
        )
    else:
        summary = f"{action}: nothing done — {'; '.join(failed)}."
    # Partial success is still success: an error here would hide the accounts
    # that were genuinely changed, which is worse than a mixed report.
    if not ok and failed:
        return ActionResult.error(summary)
    return ActionResult.success(
        data=data, summary=summary, refresh_panels=["tools"],
    )


# ─── Handlers ─────────────────────────────────────────────────────────── #

@chat.function(
    "bulk_set_user_active",
    action_type="write",
    effects=["update:user_status"],
    data_model=BulkReceipt,
    description=(
        "Deactivate or reactivate SEVERAL users in one call. Use whenever the "
        "admin names more than one person ('deactivate X, Y and Z') instead "
        "of calling deactivate_user repeatedly."
    ),
)
async def fn_bulk_set_user_active(ctx, params: BulkSetActiveParams) -> ActionResult:
    """Activate/deactivate many users; reports per-user outcomes."""
    targets, failures = await _resolve_targets(params.user_ids)
    verb = "Reactivated" if params.is_active else "Deactivated"
    ok: list[str] = []
    for term, uid in targets:
        try:
            if params.is_active:
                res = await _gw_request("PATCH", f"/v1/users/{uid}", {"is_active": True})
            else:
                res = await _gw_request("DELETE", f"/v1/users/{uid}")
            if isinstance(res, dict) and res.get("error"):
                failures.append(f"{term} — {res['error']}")
            else:
                ok.append(uid)
        except Exception as exc:                      # noqa: BLE001
            log.warning("bulk_set_user_active %s: %s", uid, exc)
            failures.append(f"{term} — {str(exc)[:120]}")
    return _receipt(verb, ok, failures, is_active=params.is_active)


@chat.function(
    "bulk_adjust_balance",
    action_type="write",
    effects=["update:user_balance"],
    data_model=BulkReceipt,
    description=(
        "Credit or deduct the SAME token amount for SEVERAL users at once "
        "(positive = credit, negative = deduct). Use for compensations and "
        "mass corrections instead of calling adjust_balance repeatedly."
    ),
)
async def fn_bulk_adjust_balance(ctx, params: BulkAdjustBalanceParams) -> ActionResult:
    """Apply one token delta to many wallets."""
    if params.amount == 0:
        return ActionResult.error("Amount must be non-zero")

    targets, failures = await _resolve_targets(params.user_ids)
    ok: list[str] = []
    for term, uid in targets:
        try:
            # Reuse the single-user handler so wallet keying, floor checks and
            # ledger writes stay in ONE place — a second implementation here
            # would be the perfect way to silently corrupt balances.
            from handlers_billing import AdjustBalanceParams, fn_adjust_balance
            res = await fn_adjust_balance(
                ctx,
                AdjustBalanceParams(
                    user_id=uid, amount=params.amount, reason=params.reason,
                ),
            )
            if getattr(res, "ok", True) is False or getattr(res, "error", None):
                failures.append(f"{term} — {getattr(res, 'error', 'failed')}")
            else:
                ok.append(uid)
        except Exception as exc:                      # noqa: BLE001
            log.warning("bulk_adjust_balance %s: %s", uid, exc)
            failures.append(f"{term} — {str(exc)[:120]}")

    verb = f"Credited {params.amount}" if params.amount > 0 else f"Deducted {abs(params.amount)}"
    return _receipt(verb, ok, failures, amount=params.amount, reason=params.reason)


@chat.function(
    "bulk_reset_conversation",
    action_type="write",
    effects=["update:user_session"],
    data_model=BulkReceipt,
    description=(
        "Reset the chat history/session of SEVERAL users at once. Money, "
        "usage, billing and installed apps are preserved. Use when clearing "
        "state for a group after an incident."
    ),
)
async def fn_bulk_reset_conversation(ctx, params: BulkUsersParams) -> ActionResult:
    """Clear conversational state for many users."""
    targets, failures = await _resolve_targets(params.user_ids)
    ok: list[str] = []
    for term, uid in targets:
        try:
            res = await _gw_request("POST", f"/v1/users/{uid}/reset-conversation", {})
            if isinstance(res, dict) and res.get("error"):
                failures.append(f"{term} — {res['error']}")
            else:
                ok.append(uid)
        except Exception as exc:                      # noqa: BLE001
            log.warning("bulk_reset_conversation %s: %s", uid, exc)
            failures.append(f"{term} — {str(exc)[:120]}")
    return _receipt("Reset conversation", ok, failures)
