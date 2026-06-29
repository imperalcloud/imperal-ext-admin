"""Admin · Email panel — durable log + per-case template control.

Single source of truth: every read/write goes to the auth-gateway email
endpoints (/v1/internal/email/*); the gateway owns the ONE sender + the
append-only log. Three sub-views switched by the `email_view` kwarg:
  • templates (default) — all cases, enable/disable, open editor
  • edit       — subject/body override + enabled + send-test for ONE case
  • log        — filterable durable log (every send attempt, never deleted)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from imperal_sdk import ui

from app import _gw_request

log = logging.getLogger("admin")

_STATUS_COLORS = {
    "sent": "green",
    "failed": "red",
    "skipped_disabled": "gray",
    "skipped_dedup": "blue",
}


def _label(case: str) -> str:
    return (case or "").replace("_", " ").title()


def _rel_time(ts) -> str:
    if not ts:
        return "—"
    try:
        then = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        diff = datetime.now(timezone.utc) - then
        m = int(diff.total_seconds() // 60)
        if m < 1:
            return "now"
        if m < 60:
            return f"{m}m ago"
        if m < 1440:
            return f"{m // 60}h ago"
        if m < 43200:
            return f"{m // 1440}d ago"
        return then.strftime("%Y-%m-%d")
    except Exception:
        return str(ts)[:19]


def _nav(active_view: str) -> object:
    def _btn(view, label):
        return ui.Button(label=label,
                         variant="primary" if view == active_view else "ghost",
                         on_click=ui.Call("__panel__tools", section="email", email_view=view))
    return ui.Stack(direction="h", gap=1, children=[_btn("templates", "Templates"), _btn("log", "Log")])


async def _fetch(path: str):
    return await _gw_request("GET", path)


# ── Templates overview ────────────────────────────────────────────

async def _build_templates() -> object:
    res = await _fetch("/v1/internal/email/templates")
    items = res.get("items", []) if isinstance(res, dict) else []
    if isinstance(res, dict) and "error" in res:
        return ui.Stack(children=[ui.Header("Email", level=3), _nav("templates"),
                                  ui.Alert(title="Gateway error", message=res["error"], type="error")])

    rows = []
    for t in items:
        case = t.get("case", "")
        enabled = bool(t.get("enabled", True))
        has_body = bool(t.get("has_custom_body"))
        custom_subj = bool(t.get("subject") and t.get("subject") != t.get("default_subject"))
        meta = "custom" if (has_body or custom_subj) else "default"
        expanded = [
            ui.KeyValue(items=[
                {"key": "Subject", "value": t.get("subject") or t.get("default_subject") or "—"},
                {"key": "Custom body", "value": "yes" if has_body else "no (built-in default)"},
                {"key": "Last edit", "value": (f"{t.get('updated_by') or '—'} · {_rel_time(t.get('updated_at'))}"
                                                if t.get("updated_at") else "never")},
            ], columns=1),
            ui.Stack(direction="h", gap=2, children=[
                ui.Button(label="Edit template", icon="Pencil", variant="secondary",
                          on_click=ui.Call("__panel__tools", section="email", email_view="edit", case=case)),
                ui.Button(label=("Disable" if enabled else "Enable"),
                          icon=("BellOff" if enabled else "Bell"),
                          variant=("ghost" if enabled else "primary"),
                          on_click=ui.Call("email_toggle_case", case=case, enabled=(not enabled))),
            ]),
        ]
        rows.append(ui.ListItem(
            id=case,
            title=_label(case),
            subtitle=t.get("description") or "",
            badge=ui.Badge("Enabled" if enabled else "Disabled", color="green" if enabled else "red"),
            meta=meta,
            expandable=True,
            expanded_content=expanded,
        ))

    return ui.Stack(gap=2, children=[
        ui.Header("Email", level=3),
        _nav("templates"),
        ui.Text(f"{len(items)} cases · one centralized sender · durable log never deleted", variant="caption"),
        ui.List(items=rows, searchable=True),
    ])


# ── Per-case editor ───────────────────────────────────────────────

async def _build_edit(case: str) -> object:
    if not case:
        return await _build_templates()
    t = await _fetch(f"/v1/internal/email/templates/{case}")
    if isinstance(t, dict) and "error" in t:
        return ui.Stack(children=[ui.Header(f"Edit: {_label(case)}", level=3),
                                  ui.Button(label="← Back", variant="ghost",
                                            on_click=ui.Call("__panel__tools", section="email", email_view="templates")),
                                  ui.Alert(title="Not found", message=t["error"], type="error")])

    default_subject = t.get("default_subject") or ""
    return ui.Stack(gap=2, children=[
        ui.Stack(direction="h", gap=2, children=[
            ui.Button(label="← Templates", variant="ghost",
                      on_click=ui.Call("__panel__tools", section="email", email_view="templates")),
            ui.Header(f"Edit: {_label(case)}", level=3),
            ui.Badge("Enabled" if t.get("enabled", True) else "Disabled",
                     color="green" if t.get("enabled", True) else "red"),
        ]),
        ui.Text(t.get("description") or "", variant="caption"),
        ui.Alert(title="How overrides work",
                 message="Leave a field blank to use the branded built-in default. "
                         "Placeholders like {plan}, {name}, {renews}, {days_left}, {last4} are filled at send time.",
                 type="info"),
        ui.Form(action="email_save_template", submit_label="Save template",
                defaults={"case": case,
                          "subject": t.get("subject") or "",
                          "html_body": t.get("html_body") or "",
                          "text_body": t.get("text_body") or "",
                          "enabled": bool(t.get("enabled", True))},
                children=[
                    ui.Section(title="Template", children=[
                        ui.Text(f"Subject (blank = default: “{default_subject}”)", variant="caption"),
                        ui.Input(param_name="subject", value=t.get("subject") or "", placeholder=default_subject),
                        ui.Text("HTML body (blank = built-in branded template)", variant="caption"),
                        ui.TextArea(param_name="html_body", value=t.get("html_body") or "",
                                    placeholder="(blank = use the built-in default)", rows=10),
                        ui.Text("Plain-text body (blank = built-in default)", variant="caption"),
                        ui.TextArea(param_name="text_body", value=t.get("text_body") or "",
                                    placeholder="(blank = use the built-in default)", rows=4),
                        ui.Toggle(label="Enabled — send this email", param_name="enabled",
                                  value=bool(t.get("enabled", True))),
                    ]),
                ]),
        ui.Divider(),
        ui.Header("Send a test", level=4),
        ui.Form(action="email_send_test", submit_label="Send test", defaults={"case": case}, children=[
            ui.Text("Sends this case with sample data; appears in the log.", variant="caption"),
            ui.Input(param_name="to", placeholder="you@example.com"),
        ]),
    ])


# ── Durable log ───────────────────────────────────────────────────

async def _build_log(kwargs: dict) -> object:
    case_filter = kwargs.get("email_case", "")
    status_filter = kwargs.get("email_status", "")

    tpls = await _fetch("/v1/internal/email/templates")
    cases = [t.get("case", "") for t in (tpls.get("items", []) if isinstance(tpls, dict) else [])]

    q = []
    if case_filter:
        q.append(f"case={case_filter}")
    if status_filter:
        q.append(f"status={status_filter}")
    q.append("limit=200")
    res = await _fetch("/v1/internal/email/log?" + "&".join(q))
    entries = res.get("items", []) if isinstance(res, dict) else []

    filter_bar = ui.Stack(direction="h", gap=2, children=[
        ui.Select(param_name="email_case", value=case_filter,
                  options=[{"value": "", "label": "All cases"}] + [{"value": c, "label": _label(c)} for c in cases],
                  on_change=ui.Call("__panel__tools", section="email", email_view="log", email_status=status_filter)),
        ui.Select(param_name="email_status", value=status_filter,
                  options=[{"value": "", "label": "All statuses"}] + [
                      {"value": s, "label": s} for s in ("sent", "failed", "skipped_disabled", "skipped_dedup")],
                  on_change=ui.Call("__panel__tools", section="email", email_view="log", email_case=case_filter)),
    ])

    if isinstance(res, dict) and "error" in res:
        return ui.Stack(gap=2, children=[ui.Header("Email", level=3), _nav("log"), filter_bar,
                                         ui.Alert(title="Gateway error", message=res["error"], type="error")])
    if not entries:
        return ui.Stack(gap=2, children=[ui.Header("Email", level=3), _nav("log"), filter_bar,
                                         ui.Empty(message="No email log entries match.", icon="Mail")])

    rows = []
    for e in entries:
        status = e.get("status", "")
        rows.append(ui.ListItem(
            id=str(e.get("id", "")),
            title=_label(e.get("case", "")),
            subtitle=e.get("to_email", "") or "—",
            badge=ui.Badge(status or "?", color=_STATUS_COLORS.get(status, "gray")),
            meta=_rel_time(e.get("created_at")),
            expandable=True,
            expanded_content=[ui.KeyValue(items=[
                {"key": "Sent at", "value": str(e.get("created_at") or "—")},
                {"key": "Recipient", "value": e.get("to_email") or "—"},
                {"key": "User", "value": e.get("user_id") or "—"},
                {"key": "Subject", "value": e.get("subject") or "—"},
                {"key": "Provider msg id", "value": e.get("provider_message_id") or "—"},
                {"key": "Dedup key", "value": e.get("dedup_key") or "—"},
                {"key": "Tag", "value": e.get("tag") or "—"},
                {"key": "Error", "value": e.get("error") or "—"},
            ], columns=1)],
        ))

    return ui.Stack(gap=2, children=[
        ui.Header("Email", level=3),
        _nav("log"),
        filter_bar,
        ui.Text(f"{len(entries)} entries (newest first)", variant="caption"),
        ui.List(items=rows, searchable=True),
    ])


# ── Entry point ───────────────────────────────────────────────────

async def build_email(ctx, **kwargs) -> object:
    view = kwargs.get("email_view", "templates")
    try:
        if view == "log":
            return await _build_log(kwargs)
        if view == "edit":
            return await _build_edit(kwargs.get("case", ""))
        return await _build_templates()
    except Exception as e:
        log.error("build_email view=%s error=%s", view, e)
        return ui.Alert(title="Error loading Email", message=str(e), type="error")
