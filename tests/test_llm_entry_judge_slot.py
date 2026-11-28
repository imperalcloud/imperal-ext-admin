"""The entry judge has its own model slot (owner 2026-11-28: "a variable for the entry judge's model, in the admin
extension's settings, so I can pick something cheap, fast and simple"). The kernel reads the flat keys
``entry_model`` / ``entry_provider`` (purpose=entry) and falls to the judge's model when the slot is blank."""
import inspect

import handlers_llm
import panels_llm
import panels_llm_form as form
from models_llm_config import SaveLlmConfigParams


def test_the_slot_stands_in_the_per_purpose_list_right_after_the_judge():
    keys = [k for k, *_ in form._PURPOSE_MODELS]
    assert "entry" in keys and keys.index("entry") == keys.index("judge") + 1


def test_the_save_tool_holds_the_slots_model_provider_and_sampling():
    fields = set(SaveLlmConfigParams.model_fields)
    assert {"entry_model", "entry_provider"} <= fields
    assert {f"purpose_entry_{s}" for s in ("temperature", "top_p", "presence_penalty", "frequency_penalty")} <= fields


def test_the_handler_infers_the_provider_and_clears_a_blank_slot_like_every_other_purpose():
    src = inspect.getsource(handlers_llm)
    assert src.count('"entry"') >= 3 and '"purpose_entry_temperature"' in src


def test_the_page_reads_the_stored_model_into_the_form():
    assert 'cfg.get("entry_model"' in inspect.getsource(panels_llm)
    assert "entry_model" in inspect.signature(form.build_llm_form).parameters


def test_the_routing_report_shows_the_slot_and_what_a_blank_one_runs_on():
    from models_llm_routing import PURPOSE_SLOTS, resolve_slot
    assert "entry" in [p for p, _ in PURPOSE_SLOTS]
    cfg = {"model": "base/one", "provider": "openrouter", "judge_model": "big/judge", "judge_provider": "openrouter"}
    blank = resolve_slot("entry", "Entry", cfg, {}, {})
    assert (blank.effective_model, blank.source, blank.provider) == ("big/judge", "inherited_judge", "openrouter")
    named = resolve_slot("entry", "Entry", {**cfg, "entry_model": "fast/one", "entry_provider": "deepseek"}, {}, {})
    assert (named.effective_model, named.source, named.provider) == ("fast/one", "explicit", "deepseek")
    bare = resolve_slot("entry", "Entry", {"model": "base/one", "provider": "openrouter"}, {}, {})
    assert (bare.effective_model, bare.source) == ("base/one", "inherited_default")
    # every other slot resolves as before
    other = resolve_slot("execution", "Execution", cfg, {}, {})
    assert (other.effective_model, other.source, other.provider) == ("base/one", "inherited_default", "openrouter")
