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
    assert ids[-len(PL.EXTRA_VIEWS):] == [e[0] for e in PL.EXTRA_VIEWS] and MAP_VIEW in ids
    assert len(_forms(first)) == 1 and _forms(first)[0]["submit_label"] == "Save Provider & Connection"

    everything = _inputs(_call_form().to_dict())
    reached: set[str] = set()
    for vid in ids:
        tree = _call_form(view=vid, extra_views=PL.EXTRA_VIEWS).to_dict()
        assert len(_forms(tree)) <= 1, vid
        reached |= _inputs(tree)
        for slot in _slot_buttons(tree):                 # a section with many model lists opens one at a time
            opened = _call_form(view=vid, extra_views=PL.EXTRA_VIEWS, slot=slot).to_dict()
            assert slot in _inputs(opened), (vid, slot)
            reached |= _inputs(opened)
    assert reached == everything          # no setting became unreachable


def _slot_buttons(tree) -> list[str]:
    return [b["on_click"]["params"]["llm_slot"] for b in _buttons(tree)
            if ((b.get("on_click") or {}).get("params") or {}).get("llm_slot")]


def test_a_many_slot_section_draws_one_model_list_and_names_the_others():
    tree = _call_form(view="per-purpose-models", model_catalog={"openrouter": ["a/b"]},
                      code_model="a/b").to_dict()
    selects = [n for n in _nodes(tree) if n.get("type") == "Select"]
    assert [n["props"]["param_name"] for n in selects] == ["resolve_model"]
    closed = _slot_buttons(tree)
    assert "code_model" in closed and "routing_fallback_model" in closed and "resolve_model" not in closed
    assert all(b["on_click"]["params"]["llm_view"] == "per-purpose-models" for b in _buttons(tree)
               if ((b.get("on_click") or {}).get("params") or {}).get("llm_slot"))
    assert "a/b" in json.dumps(tree), "a closed slot shows the model it holds"

    opened = _call_form(view="per-purpose-models", slot="code_model").to_dict()
    assert [n["props"]["param_name"] for n in _nodes(opened) if n.get("type") == "Select"] == ["code_model"]
    # the open slot is the only model field the form sends: the others stay as saved
    sent = _forms(opened)[0]["defaults"]
    assert "code_model" in sent and "resolve_model" not in sent

    tiers = _call_form(view="webbee-code-model-tiers").to_dict()
    tier_selects = [n["props"]["param_name"] for n in _nodes(tiers) if n.get("type") == "Select"]
    assert [x for x in tier_selects if x.endswith("_model")] == ["webbeesmart_model"]


def test_a_saved_model_the_lists_do_not_hold_is_still_shown():
    tree = _call_form(view="per-purpose-models", model_catalog={"openrouter": ["a/b"]},
                      resolve_model="gone/model").to_dict()
    select = next(n for n in _nodes(tree) if n.get("type") == "Select")
    assert select["props"]["value"] == "gone/model"
    assert any(o["value"] == "gone/model" and "saved" in o["label"] for o in select["props"]["options"])


def test_a_view_button_does_not_repeat_a_provider_test():
    for b in _buttons(_call_form(view="").to_dict()):
        params = (b.get("on_click") or {}).get("params") or {}
        if "llm_view" in params:
            assert params.get("run_test") == ""


def test_every_view_fits_the_reply_cap_with_the_whole_list():
    """Measured 2026-11-23: 318 usable OpenRouter models. Twice that, plus the
    other providers, in every view and with every slot of it opened in turn."""
    catalog = {"anthropic": [f"claude-x-{i}" for i in range(30)],
               "openai": [f"gpt-x-{i}" for i in range(60)],
               "qwen": [f"qwen-x-{i}" for i in range(60)],
               "openrouter": [f"vendor{i % 53}/some-model-name-{i}" for i in range(640)]}
    sizes = {}
    for vid in _view_ids(_call_form(view="").to_dict()):
        tree = _call_form(view=vid, model_catalog=catalog).to_dict()
        sizes[vid] = len(json.dumps(tree))
        for slot in _slot_buttons(tree):
            sizes[f"{vid}/{slot}"] = len(json.dumps(_call_form(view=vid, model_catalog=catalog, slot=slot).to_dict()))
    heaviest = max(sizes, key=sizes.get)
    assert sizes[heaviest] < KERNEL_REPLY_CAP * 0.75, (heaviest, sizes[heaviest])


# ── the OpenRouter list ───────────────────────────────────────────────────

def _m(mid, created, tools=True, out=("text",), endpoints=("/api/v1/chat/completions", "/api/v1/responses")):
    return {"id": mid, "created": created,
            "architecture": {"output_modalities": list(out)},
            "supported_parameters": ["tools", "temperature"] if tools else ["temperature"],
            "endpoints": list(endpoints)}


def test_openrouter_models_are_picked_by_what_they_can_do():
    """Owner 2026-11-23: every model that can be used, none that cannot ("типа
    модели видеогенерации"). What a model can do is what OpenRouter says of it,
    never its name or its vendor."""
    picked = PM._pick_openrouter([
        _m("google/gemini-new", 300), _m("google/gemini-old", 100),
        _m("google/lyria-music", 400, tools=False),                       # accepts no tools
        _m("google/gemini-new:batch", 500, endpoints=("/api/v1/batches",)),   # not served on the chat endpoint
        _m("google/veo-video", 600, out=("text", "video")),               # answers with a video
        _m("openai/gpt-image", 700, out=("image", "text")),               # answers with an image
        _m("x-ai/grok-new", 200),
        _m("unknown-vendor/model", 900),                                  # no list of favourite vendors
        _m("~deepseek/deepseek-latest", 50),                              # an alias is a usable model
        _m("meta-llama/llama:free", 10),
    ])
    assert picked == ["~deepseek/deepseek-latest", "google/gemini-new", "google/gemini-old",
                      "meta-llama/llama:free", "unknown-vendor/model", "x-ai/grok-new"]


def test_no_openrouter_model_is_cut():
    """The cuts that were: the first 25 of an alphabetical sort, then 8 per vendor."""
    many = [_m(f"google/gemini-{i:02d}", i) for i in range(40)] + [_m("mistralai/mistral-large", 5)]
    picked = PM._pick_openrouter(many)
    assert len(picked) == 41 and picked[0] == "google/gemini-39" and picked[-1] == "mistralai/mistral-large"
    assert not hasattr(PM, "OPENROUTER_PER_VENDOR") and not hasattr(PM, "_filter_openrouter")


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

    async def _fake(ctx, cfg, target):
        calls.append(target)
        return {"ok": True, "message": "x"}
    monkeypatch.setattr(PL, "_run_test", _fake)
    PL._test_seen.clear()
    cfg = {"provider": "openai", "model": "m"}
    asyncio.run(PL._run_test_once(None, cfg, "main"))
    asyncio.run(PL._run_test_once(None, cfg, "main"))                 # the panel re-rendered
    assert calls == ["main"]
    asyncio.run(PL._run_test_once(None, {"provider": "openai", "model": "other"}, "main"))   # the slot changed
    assert calls == ["main", "main"]
    PL._test_seen.clear()
