"""Admin · Guest role · which extensions a guest may use.

A guest (a visitor without an account, the guest chat on the site) reaches an
extension only when that extension's access policy opens it: ``guest_enabled``
and the list ``guest_allowed_functions`` (deny by default; only read functions
may be listed). The policy is the extension's own row of the configuration in
the database - the same row the Extensions -> Access page edits and the kernel
enforces. This page is that setting seen from the role: every extension open
to guests in one list, and the form to open, close or narrow one of them.

Owner, 2026-11-23: "для гостя нужно еще дать возможность выбора extensions
которые ему все же доступны ... чтобы можно было настроить тот же file reader
для гостевого чата".

Opened with section="guest_access" (its own section, so a click in the sidebar
leaves it); ``guest_app`` names the extension whose form is drawn.
"""
from __future__ import annotations

import asyncio
import logging

from imperal_sdk import ui

from app import _gw_request, _tenant_id
from panels_ext_access_policy import _fetch_app_functions
from panels_sections import _fetch_extensions_checked

log = logging.getLogger("admin")

SECTION = "guest_access"
_READS_AT_ONCE = 12


def _guest_part(policy: dict) -> tuple[bool, list[str]]:
    raw = policy.get("guest_allowed_functions")
    fns = [str(f).strip() for f in raw if str(f).strip()] if isinstance(raw, list) else []
    return policy.get("guest_enabled") is True, fns


async def _policy(app_id: str, tenant_id: str, gate: asyncio.Semaphore) -> tuple[dict, str]:
    """An extension's access policy, or why it could not be read. An extension
    that has no row yet has no policy: closed to guests."""
    async with gate:
        try:
            cfg = await _gw_request("GET", f"/v1/internal/config/app/{app_id}?tenant_id={tenant_id}&app_id={app_id}")
        except Exception as e:
            return {}, f"{type(e).__name__}: {e}"
    if isinstance(cfg, dict) and cfg.get("error"):
        why = str(cfg["error"])
        return {}, "" if "404" in why or "not found" in why.lower() else why
    policy = ((cfg or {}).get("config") or {}).get("access_policy") if isinstance(cfg, dict) else None
    return (policy if isinstance(policy, dict) else {}), ""


def _open(app_id: str = "") -> object:
    return ui.Call("__panel__tools", section=SECTION, guest_app=app_id)


def _form(app_id: str, name: str, enabled: bool, fns: list[str], readable: list[str]) -> object:
    """The guest access of one extension: the same two controls as its Access page."""
    return ui.Section(title=f"Guest access to {name}", children=[
        ui.Text(
            "Closed to guests unless switched on here, and then only the functions listed below. "
            "Only functions that read (never ones that write or delete) can be listed.", variant="caption"),
        ui.Form(
            action="set_access_policy",
            submit_label="Save",
            defaults={"app_id": app_id, "guest_enabled": enabled},
            children=[ui.Toggle(param_name="guest_enabled", label=f"Guests may use {name}", value=enabled)],
        ),
        ui.Text("Functions a guest may call", variant="caption"),
        *([ui.Stack([ui.Badge(label=fn, color="green" if enabled else "gray") for fn in fns],
                    direction="h", gap=1, wrap=True)] if fns
          else [ui.Text("None - with the switch on a guest still reaches nothing here.", variant="caption")]),
        ui.TagInput(
            values=fns, suggestions=readable, placeholder="Add a function...",
            param_name="guest_allowed_functions",
            on_change=ui.Call("set_access_policy", app_id=app_id),
        ),
        *([] if readable else [ui.Text(
            "This extension lists no read function, so nothing of it can be opened to guests.", variant="caption")]),
    ])


async def build_guest_access(ctx, guest_app: str = "", **kwargs):
    """Every extension's guest access, and the form of the chosen one."""
    extensions, store_problems = await _fetch_extensions_checked()
    apps = sorted(
        ({"app_id": str(e.get("app_id") or ""), "name": str(e.get("display_name") or e.get("app_id") or "")}
         for e in extensions if e.get("app_id")),
        key=lambda a: a["name"].lower())
    tenant_id = _tenant_id(ctx)
    gate = asyncio.Semaphore(_READS_AT_ONCE)
    answers = await asyncio.gather(*[_policy(a["app_id"], tenant_id, gate) for a in apps])

    open_rows: list = []
    unread: list[str] = []
    state: dict[str, tuple[bool, list[str]]] = {}
    for app, (policy, why) in zip(apps, answers):
        if why:
            unread.append(app["name"])
            continue
        state[app["app_id"]] = _guest_part(policy)
    for app in apps:
        enabled, fns = state.get(app["app_id"], (False, []))
        if not enabled:
            continue
        open_rows.append(ui.Stack(direction="h", gap=2, children=[
            ui.Text(app["name"], variant="body"),
            ui.Badge(f"{len(fns)} function(s)" if fns else "no function listed", color="green" if fns else "yellow"),
            ui.Button(label="Change", variant="ghost", size="sm", on_click=_open(app["app_id"])),
        ]))

    children: list = [
        ui.Button(label="← Back to Roles", variant="ghost",
                  on_click=ui.Call("__panel__tools", section="roles", active="roles")),
        ui.Header("Guest · extensions", level=3,
                  subtitle="Which extensions a visitor without an account may use"),
    ]
    problems = [f"Extensions, {p}" for p in store_problems]
    if unread:
        problems.append(f"the access policy of {len(unread)} extension(s) could not be read: {', '.join(unread[:8])}")
    if problems:
        children.append(ui.Alert(title="Not everything could be read", message="; ".join(problems), type="warning"))

    chosen = next((a for a in apps if a["app_id"] == guest_app), None)
    if chosen and chosen["app_id"] in state:
        enabled, fns = state[chosen["app_id"]]
        readable = await _fetch_app_functions(chosen["app_id"])
        children.append(_form(chosen["app_id"], chosen["name"], enabled, fns, readable))
    elif chosen:
        children.append(ui.Alert(title=f"{chosen['name']}: its access policy could not be read",
                                 message="Nothing is drawn for it, so nothing can be saved over an unknown state.",
                                 type="error"))

    children.append(ui.Section(title=f"Open to guests ({len(open_rows)})", children=open_rows or [
        ui.Text("No extension is open to guests.", variant="caption")]))
    children.append(ui.Section(title="Open or change another extension", children=[
        ui.Text("Choose an extension to see and set what a guest may use in it.", variant="caption"),
        ui.Select(
            options=[{"value": a["app_id"], "label": a["name"]} for a in apps if a["app_id"] in state],
            value=guest_app if chosen else "", param_name="guest_app", placeholder="Choose an extension",
            on_change=ui.Call("__panel__tools", section=SECTION),
        ),
    ]))
    return ui.Stack(children=children)
