# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors.
# Licensed under the AGPL-3.0 License.
"""Admin · Email tab handlers — durable log + per-case template control via the
auth-gateway single send path (/v1/internal/email/*). The gateway owns the ONE
sender + the append-only log; these tools READ that log and MANAGE templates.
No mail is rendered or sent here (single source of truth)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from app import chat, ActionResult, EmptyParams, _gw_request, _user_id, _verify_write_reflected
from models_email import (
    EmailLogResponse, EmailTemplatesResponse, EmailTemplateFull,
    EmailTemplateSaved, EmailTestResult,
)


def _aslist(r) -> list:
    if isinstance(r, list):
        return r
    if isinstance(r, dict) and "error" not in r:
        return r.get("items") or []
    return []


# ── Param models ──────────────────────────────────────────────────

class _LogQuery(BaseModel):
    case: str = Field("", description="Filter by case (e.g. renewal_success). Blank = all cases.")
    status: str = Field("", description="Filter by status: sent | failed | skipped_disabled | skipped_dedup. Blank = all.")
    user_id: str = Field("", description="Filter by recipient imperal_id. Blank = all.")
    limit: int = Field(50, description="Max rows to return (1–200), newest first.")
    offset: int = Field(0, description="Skip this many newest rows — page older entries (the log is append-only and never deleted).")


class _CaseParam(BaseModel):
    case: str = Field(description="Email case key, e.g. plan_activated, renewal_failed, expiry_reminder.")


class _SaveTemplateParams(BaseModel):
    case: str = Field(description="Email case key to edit.")
    subject: Optional[str] = Field(None, description="Subject override. Empty string = use the built-in default. Omit to leave unchanged.")
    html_body: Optional[str] = Field(None, description="HTML body override. Empty = use built-in default template. Omit = unchanged.")
    text_body: Optional[str] = Field(None, description="Plain-text body override. Empty = use built-in default. Omit = unchanged.")
    enabled: Optional[bool] = Field(None, description="Whether this case is sent at all. Omit = unchanged.")


class _ToggleParams(BaseModel):
    case: str = Field(description="Email case key.")
    enabled: bool = Field(description="Enable (True) or disable (False) sending this case — body untouched.")


class _TestParams(BaseModel):
    case: str = Field(description="Email case key to send a sample of.")
    to: str = Field(description="Recipient email address for the test send.")


# ── Read tools ────────────────────────────────────────────────────

@chat.function("email_list_log", action_type="read", data_model=EmailLogResponse,
               description="The durable email log (EVERY send attempt, never deleted): case, recipient, status, time, error. Filter by case/status/user.")
async def fn_email_list_log(ctx, params: _LogQuery) -> ActionResult:
    q = []
    if params.case:
        q.append(f"case={params.case}")
    if params.status:
        q.append(f"status={params.status}")
    if params.user_id:
        q.append(f"user_id={params.user_id}")
    limit = max(1, min(params.limit, 200))
    offset = max(0, params.offset)
    q.append(f"limit={limit}")
    q.append(f"offset={offset}")
    items = _aslist(await _gw_request("GET", "/v1/internal/email/log?" + "&".join(q)))
    # `total` here is the page size, NOT the grand total (the durable log has no
    # cheap count); report it honestly so the count is never mistaken for the all-time total.
    more = len(items) == limit
    return ActionResult.success(
        data={"items": items, "total": len(items)},
        summary=(f"{len(items)} email log entr(ies) (newest first, offset {offset}"
                 + ("; more older entries exist — raise offset to page" if more else "") + ")"))


@chat.function("email_list_templates", action_type="read", data_model=EmailTemplatesResponse,
               description="All email cases with template status: effective subject, enabled flag, whether a custom body is set.")
async def fn_email_list_templates(ctx, params: EmptyParams) -> ActionResult:
    items = _aslist(await _gw_request("GET", "/v1/internal/email/templates"))
    return ActionResult.success(data={"items": items, "total": len(items)},
                                summary=f"{len(items)} email templates")


@chat.function("email_get_template", action_type="read", data_model=EmailTemplateFull,
               description="Full editable template for one case: the current override (empty = none) + the built-in default preview.")
async def fn_email_get_template(ctx, params: _CaseParam) -> ActionResult:
    r = await _gw_request("GET", f"/v1/internal/email/templates/{params.case}")
    if isinstance(r, dict) and "error" in r:
        return ActionResult.error(r["error"])
    return ActionResult.success(data=r, summary=f"template '{params.case}' (enabled={r.get('enabled')})")


# ── Write tools ───────────────────────────────────────────────────

@chat.function("email_save_template", action_type="write", event="email_template_saved",
               data_model=EmailTemplateSaved,
               description="Edit an email case: subject/body override + enabled. Empty subject/body = use the built-in default; omitted fields stay unchanged. To ONLY enable/disable a case without touching its template, use email_toggle_case instead.")
async def fn_email_save_template(ctx, params: _SaveTemplateParams) -> ActionResult:
    # Only send fields the caller actually provided — None = leave unchanged.
    # This lets the LLM toggle `enabled` without wiping a custom body.
    body = {"updated_by": _user_id(ctx) or "admin"}
    for k in ("subject", "html_body", "text_body"):
        v = getattr(params, k)
        if v is not None:
            body[k] = v
    if params.enabled is not None:
        body["enabled"] = params.enabled
    if len(body) == 1:
        return ActionResult.error("nothing to change — provide subject, body, or enabled")
    r = await _gw_request("PUT", f"/v1/internal/email/templates/{params.case}", body, acting=_user_id(ctx))
    if isinstance(r, dict) and "error" in r:
        return ActionResult.error(r["error"])
    drift = _verify_write_reflected(r, {"enabled": params.enabled})
    if drift:
        return ActionResult.error(drift)
    return ActionResult.success(data=r, summary=f"Saved template '{params.case}' (enabled={r.get('enabled')}).",
                                refresh_panels=["tools"])


@chat.function("email_toggle_case", action_type="write", event="email_case_toggled",
               data_model=EmailTemplateSaved,
               description="Enable or disable an email case WITHOUT touching its subject/body.")
async def fn_email_toggle_case(ctx, params: _ToggleParams) -> ActionResult:
    r = await _gw_request("PUT", f"/v1/internal/email/templates/{params.case}",
                          {"enabled": params.enabled, "updated_by": _user_id(ctx) or "admin"},
                          acting=_user_id(ctx))
    if isinstance(r, dict) and "error" in r:
        return ActionResult.error(r["error"])
    drift = _verify_write_reflected(r, {"enabled": params.enabled})
    if drift:
        return ActionResult.error(drift)
    return ActionResult.success(data=r, summary=f"Case '{params.case}' {'enabled' if params.enabled else 'disabled'}.",
                                refresh_panels=["tools"])


@chat.function("email_send_test", action_type="write", event="email_test_sent",
               data_model=EmailTestResult,
               description="Send a sample of one email case to an address (uses sample data, logged like any send).")
async def fn_email_send_test(ctx, params: _TestParams) -> ActionResult:
    if "@" not in (params.to or ""):
        return ActionResult.error("provide a valid recipient email in `to`")
    r = await _gw_request("POST", "/v1/internal/email/test", {"case": params.case, "to": params.to},
                          acting=_user_id(ctx))
    if isinstance(r, dict) and "error" in r:
        return ActionResult.error(r["error"])
    st = r.get("status")
    return ActionResult.success(
        data=r,
        summary=(f"Test '{params.case}' sent to {params.to}." if st == "sent"
                 else f"Test '{params.case}' → {st}: {r.get('error') or 'see log'}"),
        refresh_panels=["tools"])
