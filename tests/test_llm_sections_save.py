"""Admin · LLM Config: one section = one form = one Save.

Until 2026-11-23 the page was ONE form (141 inputs, one button): every save
re-sent every setting. The page is now a form per section, which is only
correct if a save touches nothing it did not carry - pinned here on the
handler, because the old handler cleared every per-purpose model and AI
parameter that a save did not mention.
"""
from __future__ import annotations

import asyncio
import json

import handlers_llm as HL
from models_llm_config import SaveLlmConfigParams
from tests.test_llm_thinking_effort import _call_form


def _nodes(x):
    if isinstance(x, dict):
        yield x
        for v in x.values():
            yield from _nodes(v)
    elif isinstance(x, (list, tuple)):
        for v in x:
            yield from _nodes(v)


def _inputs(node) -> set[str]:
    return {n["props"]["param_name"] for n in _nodes(node)
            if isinstance(n.get("props"), dict) and n["props"].get("param_name")}


def _forms(tree) -> list[dict]:
    return [n["props"] for n in _nodes(tree) if n.get("type") == "Form"]


def test_every_section_with_inputs_is_its_own_form():
    tree = _call_form().to_dict()
    assert tree["type"] != "Form", "the page is one form again"
    forms = _forms(tree)
    assert len(forms) >= 8
    labels = [f["submit_label"] for f in forms]
    assert len(set(labels)) == len(labels), labels          # each Save names its section
    assert all(f["action"] == "save_llm_config" for f in forms)
    assert "Save Provider & Connection" in labels and "Save Failover" in labels


def test_no_input_is_outside_a_form_and_none_is_in_two():
    tree = _call_form().to_dict()
    per_form = [_inputs(f) for f in _forms(tree)]
    in_forms = set().union(*per_form)
    assert _inputs(tree) == in_forms
    assert sum(len(s) for s in per_form) == len(in_forms)
    assert len(in_forms) > 100                               # nothing was lost in the split


def test_a_form_sends_only_its_own_section():
    """Form defaults are submitted with the form: they must not carry the page."""
    for form in _forms(_call_form().to_dict()):
        extra = set(form.get("defaults") or {}) - _inputs(form)
        assert not extra, f"{form['submit_label']} would also send {sorted(extra)[:5]}"


class _Redis:
    def __init__(self, stored: dict):
        self.stored = stored

    async def get(self, key):
        return json.dumps(self.stored)

    async def set(self, key, value):
        self.stored = json.loads(value)

    async def delete(self, *a):
        return 1

    async def publish(self, *a):
        return 0

    async def aclose(self):
        return None


def _save(monkeypatch, stored: dict, **sent) -> tuple[dict, object]:
    fake = _Redis(dict(stored))
    import redis.asyncio as aioredis
    monkeypatch.setattr(aioredis, "from_url", lambda *a, **k: fake)
    out = asyncio.run(HL.fn_save_llm_config(None, SaveLlmConfigParams(**sent)))
    return fake.stored, out


STORED = {
    "provider": "openrouter", "model": "a/main", "api_key": "sk-stored",
    "execution_model": "a/exec", "execution_provider": "openrouter",
    "judge_model": "a/judge", "judge_provider": "openrouter",
    "failover_enabled": True, "failover_model": "b/fo", "failover_provider": "openai",
    "purpose": {"routing": {"temperature": 0.2}, "judge": {"top_p": 0.9}},
}


def test_saving_one_section_leaves_the_others_as_they_were(monkeypatch):
    after, out = _save(monkeypatch, STORED, provider="openrouter", model="a/new", base_url="")
    assert out.status == "success", getattr(out, "error", None)
    assert after["model"] == "a/new"
    for key in ("execution_model", "execution_provider", "judge_model", "judge_provider",
                "failover_enabled", "failover_model", "failover_provider", "api_key", "purpose"):
        assert after[key] == STORED[key], key


def test_a_blank_that_was_sent_still_clears(monkeypatch):
    """'Same as default' in the section that owns the field keeps working."""
    after, _ = _save(monkeypatch, STORED, execution_model="", purpose_routing_temperature="")
    assert "execution_model" not in after and "execution_provider" not in after
    assert after["judge_model"] == "a/judge"
    assert after["purpose"] == {"judge": {"top_p": 0.9}}


def test_the_receipt_never_carries_a_key(monkeypatch):
    after, out = _save(monkeypatch, STORED, model="a/new")
    assert after["api_key"] == "sk-stored"                   # stored as it was
    assert "sk-stored" not in json.dumps(out.data, default=str)


# ── one section on screen at a time ───────────────────────────────────────

import panels_llm as PL
import panels_llm_models as PM
from panels_llm_form import MAP_VIEW

KERNEL_REPLY_CAP = 262144


def _buttons(tree) -> list[dict]:
    return [n["props"] for n in _nodes(tree) if n.get("type") == "Button"]


def _view_ids(tree) -> list[str]:
    return [b["on_click"]["params"]["llm_view"] for b in _buttons(tree)
            if isinstance(b.get("on_click"), dict)
            and "llm_view" in (b["on_click"].get("params") or {})]


def test_the_page_draws_one_section_and_a_way_to_every_other():
    first = _call_form(view="", extra_views=PL.EXTRA_VIEWS).to_dict()
    ids = _view_ids(first)
    assert ids[0] == "provider-connection" and "failover" in ids
    assert ids[-2:] == [e[0] for e in PL.EXTRA_VIEWS] and MAP_VIEW in ids
    assert len(_forms(first)) == 1 and _forms(first)[0]["submit_label"] == "Save Provider & Connection"

    everything = _inputs(_call_form().to_dict())
    reached: set[str] = set()
    for vid in ids:
        tree = _call_form(view=vid, extra_views=PL.EXTRA_VIEWS).to_dict()
        assert len(_forms(tree)) <= 1, vid
        reached |= _inputs(tree)
    assert reached == everything          # no setting became unreachable


def test_a_view_button_does_not_repeat_a_provider_test():
    for b in _buttons(_call_form(view="").to_dict()):
        params = (b.get("on_click") or {}).get("params") or {}
        if "llm_view" in params:
            assert params.get("run_test") == ""


def test_the_heaviest_view_fits_the_reply_cap_with_the_real_list_length():
    """13 vendors x OPENROUTER_PER_VENDOR models, in every select of a view."""
    n = 13 * PM.OPENROUTER_PER_VENDOR
    catalog = {"anthropic": [f"claude-x-{i}" for i in range(8)],
               "openai": [f"gpt-x-{i}" for i in range(12)],
               "openrouter": [f"vendor{i % 13}/some-model-name-{i}" for i in range(n)]}
    sizes = {}
    for vid in _view_ids(_call_form(view="").to_dict()):
        tree = _call_form(view=vid, model_catalog=catalog).to_dict()
        sizes[vid] = len(json.dumps(tree))
    heaviest = max(sizes, key=sizes.get)
    assert sizes[heaviest] < KERNEL_REPLY_CAP * 0.75, (heaviest, sizes[heaviest])


# ── the OpenRouter list ───────────────────────────────────────────────────

def _m(mid, created, tools=True, out=("text",)):
    return {"id": mid, "created": created,
            "architecture": {"output_modalities": list(out)},
            "supported_parameters": ["tools", "temperature"] if tools else ["temperature"]}


def test_openrouter_models_are_picked_by_what_they_can_do():
    picked = PM._pick_openrouter([
        _m("google/gemini-new", 300), _m("google/gemini-old", 100),
        _m("google/lyria-music", 400, tools=False),          # passes the name rules, cannot use tools
        _m("google/gemini-new:batch", 500),                  # cannot answer live requests
        _m("x-ai/grok-new", 200),
        _m("unknown-vendor/model", 900),
    ])
    assert picked == ["google/gemini-new", "google/gemini-old", "x-ai/grok-new"]


def test_every_vendor_keeps_its_newest_models():
    """The old cut took the first 25 of an alphabetical sort: whole vendors vanished."""
    many = [_m(f"google/gemini-{i:02d}", i) for i in range(40)] + [_m("mistralai/mistral-large", 5)]
    picked = PM._pick_openrouter(many)
    google = [p for p in picked if p.startswith("google/")]
    assert len(google) == PM.OPENROUTER_PER_VENDOR and google[0] == "google/gemini-39"
    assert "mistralai/mistral-large" in picked


def test_a_model_without_capability_fields_is_not_dropped_for_that():
    assert PM._pick_openrouter([{"id": "qwen/qwen-x", "created": 1}]) == ["qwen/qwen-x"]


def test_any_vendor_slash_model_id_is_an_openrouter_model():
    assert PM.provider_for_model("x-ai/grok-5") == "openrouter"
    assert PM.provider_for_model("moonshotai/kimi-k3") == "openrouter"   # was "kimi"
    assert PM.provider_for_model("qwen/qwen3.5-plus") == "openrouter"    # was "qwen"
    assert PM.provider_for_model("kimi-k3") == "kimi" and PM.provider_for_model("qwen-plus") == "qwen"
    assert PM.provider_for_model("models/gemini-2.0") == "google"
    assert PM.provider_for_model("some-unknown-model") == ""


# ── a test result between re-renders ──────────────────────────────────────

def test_a_re_render_does_not_call_the_provider_again(monkeypatch):
    calls = []

    async def _fake(cfg, target):
        calls.append(target)
        return {"ok": True, "message": "x"}
    monkeypatch.setattr(PL, "_run_test", _fake)
    PL._test_seen.clear()
    cfg = {"provider": "openai", "model": "m"}
    asyncio.run(PL._run_test_once(cfg, "main"))
    asyncio.run(PL._run_test_once(cfg, "main"))                       # the panel re-rendered
    assert calls == ["main"]
    asyncio.run(PL._run_test_once({"provider": "openai", "model": "other"}, "main"))   # the slot changed
    assert calls == ["main", "main"]
    PL._test_seen.clear()
