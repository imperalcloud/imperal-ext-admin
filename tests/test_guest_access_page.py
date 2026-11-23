"""Guest role: which extensions a guest may use (owner, 2026-11-23: "возможность выбора extensions которые ему
все же доступны ... настроить тот же file reader для гостевого чата")."""
from __future__ import annotations

import asyncio
import types

import panels
import panels_guest_access as PG


def _tree(x):
    x = x.to_dict() if hasattr(x, "to_dict") else x
    if isinstance(x, dict):
        yield x
        for v in x.values():
            yield from _tree(v)
    elif isinstance(x, (list, tuple)):
        for v in x:
            yield from _tree(v)


APPS = [{"app_id": "file-reader", "display_name": "File Reader"}, {"app_id": "web-tools", "display_name": "Web Tools"},
        {"app_id": "mail", "display_name": "Mail"}, {"app_id": "broken", "display_name": "Broken"}]
POLICIES = {
    "file-reader": {"config": {"access_policy": {"mode": "public", "guest_enabled": False,
                                                 "guest_allowed_functions": ["read_file"]}}},
    "web-tools": {"config": {"access_policy": {"guest_enabled": True, "guest_allowed_functions": ["fetch", "search"]}}},
    "mail": {"error": "HTTP 404: Config not found for scope=app scope_id=mail"},
    "broken": {"error": "HTTP 503: gateway away"},
}


def _page(monkeypatch, guest_app=""):
    async def _exts():
        return APPS, []

    async def _gw(method, path, data=None, acting=None, ctx=None):
        app_id = path.split("/config/app/")[1].split("?")[0]
        assert "tenant_id=default" in path and f"app_id={app_id}" in path
        return POLICIES[app_id]

    async def _fns(app_id):
        return ["read_file", "list_files"] if app_id == "file-reader" else []
    monkeypatch.setattr(PG, "_fetch_extensions_checked", _exts)
    monkeypatch.setattr(PG, "_gw_request", _gw)
    monkeypatch.setattr(PG, "_fetch_app_functions", _fns)
    monkeypatch.setattr(PG, "_tenant_id", lambda ctx: "default")
    return asyncio.run(PG.build_guest_access(types.SimpleNamespace(), guest_app=guest_app)).to_dict()


def _text(tree) -> str:
    return " | ".join(str(n["props"].get(k)) for n in _tree(tree) if isinstance(n.get("props"), dict)
                      for k in ("content", "text", "title", "message", "label") if n["props"].get(k))


def test_the_page_lists_what_is_open_and_offers_every_other_extension(monkeypatch):
    page = _page(monkeypatch)
    text = _text(page)
    assert "Open to guests (1)" in text and "Web Tools" in text and "2 function(s)" in text
    select = next(n["props"] for n in _tree(page) if n.get("type") == "Select")
    assert [o["value"] for o in select["options"]] == ["file-reader", "mail", "web-tools"]
    assert select["param_name"] == "guest_app" and select["on_change"]["params"]["section"] == "guest_access"
    assert not [n for n in _tree(page) if n.get("type") == "Form"], "no extension chosen, no form"


def test_an_extension_with_no_policy_row_is_closed_and_one_that_failed_is_said_so(monkeypatch):
    page = _page(monkeypatch)
    alert = next(n["props"] for n in _tree(page) if n.get("type") == "Alert")
    assert "1 extension(s) could not be read: Broken" in alert["message"]
    select = next(n["props"] for n in _tree(page) if n.get("type") == "Select")
    assert "broken" not in [o["value"] for o in select["options"]], "an unknown state is not offered for saving"


def test_choosing_file_reader_draws_its_switch_and_its_read_functions(monkeypatch):
    page = _page(monkeypatch, guest_app="file-reader")
    form = next(n["props"] for n in _tree(page) if n.get("type") == "Form")
    assert form["action"] == "set_access_policy" and form["defaults"] == {"app_id": "file-reader", "guest_enabled": False}
    toggle = next(n["props"] for n in _tree(page) if n.get("type") == "Toggle")
    assert toggle["param_name"] == "guest_enabled" and toggle["value"] is False
    tags = next(n["props"] for n in _tree(page) if n.get("type") == "TagInput")
    assert tags["values"] == ["read_file"] and tags["suggestions"] == ["read_file", "list_files"]
    assert tags["param_name"] == "guest_allowed_functions"
    assert tags["on_change"]["function"] == "set_access_policy" and tags["on_change"]["params"] == {"app_id": "file-reader"}


def test_an_extension_whose_policy_was_not_read_gets_no_form(monkeypatch):
    page = _page(monkeypatch, guest_app="broken")
    assert not [n for n in _tree(page) if n.get("type") == "Form"]
    assert "Broken: its access policy could not be read" in _text(page)


def test_the_page_is_its_own_section_and_the_guest_role_links_to_it():
    assert panels._BUILDERS["guest_access"] is PG.build_guest_access
    import inspect
    import panels_roles as PR
    assert 'section="guest_access"' in inspect.getsource(PR._guest_item)
