"""Admin · AI Models tab — an inherited default must never LOOK chosen.

The reported symptom: opening WordPress Hub's AI Models tab showed a model
already selected in every slot, as though someone had deliberately pinned one.
Nothing was pinned. The tab rendered the RESOLVED config (Registry merges its
own DEFAULT_CONFIG, the Gateway merges PLATFORM_DEFAULTS) straight into each
Select's ``value=``, so "inherited" and "explicitly chosen" were pixel-identical
— and the next Save turned the illusion into a real, stored pin.

The tab now renders from the app's OWN stored section and shows the resolved
value only as a hint. These tests hold that line, using the exact shapes taken
from production: an app that stores nothing, one carrying the old form's
residue, and one with a genuine pin.
"""
from __future__ import annotations

import pytest

from panels_ext_settings_ai import build_models_tab


# The resolved view every app gets back today: platform defaults merged in.
RESOLVED = {
    "models": {
        "primary_model": "claude-sonnet-4-6",
        "intake_model": "gpt-4o-mini",
        "analysis_model": "claude-opus-4-6",
        "router_model": "gpt-4o-mini",
        "temperature": 0.7,
        "max_tokens": 2048,
        "thinking_mode": "auto",
    }
}

# wordpress-hub in production: no app-scope models row at all.
OWN_NOTHING: dict = {}

# billing in production: pure residue of the old form — blank models, but
# temperature/max_tokens/thinking_mode stored because the form always wrote them.
OWN_RESIDUE = {
    "primary_model": "", "intake_model": "", "analysis_model": "", "router_model": "",
    "temperature": 0.7, "max_tokens": 2048, "thinking_mode": "auto",
}

# admin in production: one deliberate pin plus a raised token ceiling.
OWN_DELIBERATE = {
    "primary_model": "", "intake_model": "", "analysis_model": "claude-opus-4-6",
    "router_model": "", "temperature": 0.7, "max_tokens": 8192, "thinking_mode": "auto",
}


def _props(node) -> dict:
    return getattr(node, "props", {}) or {}


def _find(nodes, kind):
    return [n for n in nodes if getattr(n, "type", None) == kind]


def _form(nodes):
    forms = _find(nodes, "Form")
    assert forms, "the tab rendered no form"
    return forms[0]


def _defaults(nodes) -> dict:
    return _props(_form(nodes)).get("defaults", {}) or {}


def _walk(node):
    """Yield a node and every descendant, whatever depth it sits at.

    The tab nests some controls inside a Section, so a shallow scan of the
    form's direct children silently misses them — and a test that misses a
    control passes no matter how that control behaves.
    """
    yield node
    for child in (_props(node).get("children") or []):
        yield from _walk(child)


def _controls(nodes, kind):
    out = []
    for node in _walk(_form(nodes)):
        if getattr(node, "type", None) == kind:
            out.append(node)
    return out


def _selects(nodes):
    return _controls(nodes, "Select")


def _by_param(nodes, param):
    for node in _walk(_form(nodes)):
        if _props(node).get("param_name") == param:
            return node
    return None


# ── nothing stored: the reported bug ─────────────────────────────────────── #

def test_app_that_pinned_nothing_shows_nothing_selected():
    """The exact WordPress Hub case. Every field must come back blank."""
    out = build_models_tab("wordpress-hub", RESOLVED, OWN_NOTHING)
    defaults = _defaults(out)
    for key in ("primary_model", "intake_model", "analysis_model", "router_model",
                "temperature", "max_tokens", "thinking_mode"):
        assert defaults.get(key) == "", (
            f"{key} came back pre-filled from the resolved config — an inherited "
            f"default is being presented as a deliberate choice"
        )


def test_nothing_pinned_is_stated_in_plain_words():
    out = build_models_tab("wordpress-hub", RESOLVED, OWN_NOTHING)
    alerts = _find(out, "Alert")
    assert alerts, "no banner explaining that the app follows the defaults"
    assert "default" in _props(alerts[0]).get("title", "").lower()


def test_every_model_slot_is_rendered():
    """A slot that vanishes from the tab silently keeps whatever it had."""
    out = build_models_tab("x", RESOLVED, OWN_NOTHING)
    for slot in ("primary_model", "intake_model", "analysis_model", "router_model"):
        assert _by_param(out, slot) is not None, f"{slot} is missing from the tab"


def test_inherited_model_is_still_visible_as_a_hint():
    """Blank must not mean uninformative: the admin still sees what they get."""
    out = build_models_tab("wordpress-hub", RESOLVED, OWN_NOTHING)
    first = _selects(out)[0]
    label = (_props(first).get("options") or [{}])[0].get("label", "")
    assert "inherit" in label.lower()
    assert "claude-sonnet-4-6" in label, (
        "the inherit option must name the model it resolves to, otherwise the "
        "admin cannot tell what leaving it blank actually selects"
    )


def test_saving_an_untouched_inherited_tab_would_pin_nothing():
    """The defaults ARE the payload on an untouched Save — it must be empty."""
    defaults = _defaults(build_models_tab("wordpress-hub", RESOLVED, OWN_NOTHING))
    meaningful = {k: v for k, v in defaults.items() if k != "app_id" and v != ""}
    assert meaningful == {}, (
        f"an untouched Save would store {meaningful} and shadow the cascade"
    )


# ── residue from the old form ────────────────────────────────────────────── #

def test_old_form_residue_is_surfaced_not_hidden():
    out = build_models_tab("billing", RESOLVED, OWN_RESIDUE)
    alerts = _find(out, "Alert")
    assert alerts, "an app carrying overrides must say so"
    assert "override" in _props(alerts[0]).get("title", "").lower()


def test_residue_values_are_shown_so_they_can_be_cleared():
    """They must appear in the form, or the admin cannot blank them."""
    defaults = _defaults(build_models_tab("billing", RESOLVED, OWN_RESIDUE))
    assert defaults.get("temperature") == "0.7"
    assert defaults.get("max_tokens") == "2048"
    assert defaults.get("thinking_mode") == "auto"


def test_residue_does_not_invent_model_pins():
    """Blank models stay blank even while other keys are stored."""
    defaults = _defaults(build_models_tab("billing", RESOLVED, OWN_RESIDUE))
    for slot in ("primary_model", "intake_model", "analysis_model", "router_model"):
        assert defaults.get(slot) == ""


# ── a real, deliberate pin ───────────────────────────────────────────────── #

def test_deliberate_pin_is_preserved_exactly():
    defaults = _defaults(build_models_tab("admin", RESOLVED, OWN_DELIBERATE))
    assert defaults.get("analysis_model") == "claude-opus-4-6"
    assert defaults.get("max_tokens") == "8192"


def test_unpinned_slots_stay_blank_next_to_a_pinned_one():
    """The bug would have filled these from the resolved view."""
    defaults = _defaults(build_models_tab("admin", RESOLVED, OWN_DELIBERATE))
    for slot in ("primary_model", "intake_model", "router_model"):
        assert defaults.get(slot) == "", (
            f"{slot} is inheriting but rendered as chosen"
        )


# ── degraded mode ────────────────────────────────────────────────────────── #

def test_unreadable_own_config_falls_back_instead_of_lying():
    """If the unresolved read fails we must not claim everything inherits.

    Showing blanks we cannot vouch for would invite a Save that wipes real
    pins. Falling back to the old, imprecise rendering is the safe failure.
    """
    out = build_models_tab("x", RESOLVED, None)
    defaults = _defaults(out)
    assert defaults.get("primary_model") == "claude-sonnet-4-6"
    assert not _find(out, "Alert"), (
        "no claim about inheritance may be made when the source could not be read"
    )


def test_missing_resolved_section_does_not_crash():
    out = build_models_tab("x", {}, {})
    assert _defaults(out).get("primary_model") == ""


def test_thinking_mode_offers_an_explicit_inherit_option():
    """'auto' is a stored choice; inherit is the absence of one.

    Without a blank option the key can only ever be written, never cleared —
    which is exactly how every app ended up with thinking_mode pinned.
    """
    out = build_models_tab("x", RESOLVED, OWN_NOTHING)
    thinking = _by_param(out, "thinking_mode")
    assert thinking is not None, "thinking_mode is not rendered at all"
    options = _props(thinking).get("options") or []
    assert options, "thinking_mode has no options to choose from"
    values = [o.get("value") for o in options]
    labels = [(o.get("label") or "").lower() for o in options]
    assert "" in values, "no inherit option — the key can never be un-set"
    assert any("inherit" in lb for lb in labels)
    # 'auto' must remain available as a DELIBERATE choice, distinct from inherit.
    assert "auto" in values


# ── the model lists are the live ones (2026-11-23) ────────────────────────

def _tree(x):
    x = x.to_dict() if hasattr(x, "to_dict") else x
    if isinstance(x, dict):
        yield x
        for v in x.values():
            yield from _tree(v)
    elif isinstance(x, (list, tuple)):
        for v in x:
            yield from _tree(v)


def _model_selects(tab):
    return [n["props"] for n in _tree(tab) if n.get("type") == "Select"
            and str(n["props"].get("param_name", "")).endswith("_model")]


def test_the_tab_has_no_built_in_model_list():
    """It offered 15 hardcoded Claude and GPT ids, whatever keys existed."""
    import panels_ext_settings_ai as tab
    assert not hasattr(tab, "_MODEL_OPTIONS")
    selects = _model_selects(build_models_tab("app", RESOLVED, {}, models=None, slot="*"))
    assert len(selects) == 4
    assert all([o["value"] for o in s["options"]] == [""] for s in selects), "no key, no model to pick"


def test_the_tab_offers_the_live_list_one_slot_at_a_time():
    live = [{"value": "vendor/model-a", "label": "vendor/model-a (openrouter)"},
            {"value": "qwen-plus", "label": "qwen-plus (qwen)"}]
    tab = build_models_tab("app", RESOLVED, {"intake_model": "vendor/model-a"}, models=live, slot="")
    selects = _model_selects(tab)
    assert [s["param_name"] for s in selects] == ["primary_model"]
    assert [o["value"] for o in selects[0]["options"]] == ["", "vendor/model-a", "qwen-plus"]
    opens = [n["props"]["on_click"]["params"] for n in _tree(tab)
             if n.get("type") == "Button" and "model_slot" in ((n["props"].get("on_click") or {}).get("params") or {})]
    assert [p["model_slot"] for p in opens] == ["intake_model", "analysis_model", "router_model"]
    assert all(p["section"] == "ext_settings" and p["app_id"] == "app" and p["tab"] == "models" for p in opens)
    # a save still sends all four: the closed slots travel in the form's defaults
    form = next(n["props"] for n in _tree(tab) if n.get("type") == "Form")
    assert form["defaults"]["intake_model"] == "vendor/model-a" and "router_model" in form["defaults"]

    opened = _model_selects(build_models_tab("app", RESOLVED, {"intake_model": "vendor/model-a"},
                                             models=live, slot="intake_model"))
    assert [s["param_name"] for s in opened] == ["intake_model"] and opened[0]["value"] == "vendor/model-a"


def test_a_pinned_model_the_lists_do_not_hold_is_still_shown():
    selects = _model_selects(build_models_tab("app", RESOLVED, {"primary_model": "claude-opus-4-7"},
                                              models=[], slot=""))
    assert selects[0]["value"] == "claude-opus-4-7"
    assert any(o["value"] == "claude-opus-4-7" and "saved" in o["label"] for o in selects[0]["options"])
