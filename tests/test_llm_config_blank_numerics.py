"""Regression: blank Optional[int]/[bool] fields must not crash the save.

INCIDENT (2026-08-29): the admin edited one field on LLM Config and hit
Save. The whole request failed with:

    1 validation error for SaveLlmConfigParams
    code_max_tokens
    Input should be a valid integer, unable to parse string as an integer

The form always submits EVERY field it renders, not just the one the admin
touched. Every "blank = inherit" numeric/boolean field the admin did NOT
touch arrives as an empty string ``""`` (ui.Input's blank state), not as
``None`` -- and Pydantic v2 does not coerce ``""`` to ``None`` for
``Optional[int]``/``Optional[bool]`` on its own. code_max_tokens was hit
first only because it was the newest such field (added the same day) and
happened to render a literal "" default -- but this was never a one-field
bug: EVERY Optional[int]/Optional[bool] field on this model shared the same
exposure, and any one of them left blank could have thrown next.

The fix is a single generic `model_validator(mode="before")` on
SaveLlmConfigParams that walks `model_fields` and turns "" into None for any
field whose annotation includes int or bool -- so a newly added
Optional[int]/[bool] field is covered automatically, with no per-field
patch and nothing to remember next time.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from models_llm_config import SaveLlmConfigParams


def _all_optional_int_and_bool_fields() -> list[str]:
    names = []
    for name, field in SaveLlmConfigParams.model_fields.items():
        args = getattr(field.annotation, "__args__", ())
        if int in args or bool in args:
            names.append(name)
    return names


def test_every_optional_numeric_field_survives_being_left_blank():
    """Simulates a real save: the form submits ALL its fields at once, and
    only ONE was actually edited -- every other Optional[int]/[bool] field
    arrives as "" exactly like code_max_tokens did in the incident."""
    fields = _all_optional_int_and_bool_fields()
    assert fields, "expected at least one Optional[int]/[bool] field to exist"
    payload = {name: "" for name in fields}
    params = SaveLlmConfigParams(**payload)
    for name in fields:
        assert getattr(params, name) is None, (
            f"{name}: blank ('') must normalise to None, not raise or keep "
            f"the empty string -- got {getattr(params, name)!r}"
        )


def test_code_max_tokens_blank_does_not_raise():
    """The exact field and exact input from the admin's reported incident."""
    params = SaveLlmConfigParams(code_max_tokens="")
    assert params.code_max_tokens is None


def test_real_numeric_value_still_parses_and_still_validates():
    """The fix must not swallow real values or real out-of-bounds errors."""
    params = SaveLlmConfigParams(code_max_tokens="32000")
    assert params.code_max_tokens == 32000

    with pytest.raises(ValidationError):
        # routing_max_tokens is bounded le=32000 -- a real out-of-range
        # value must still be rejected, not silently coerced to None.
        SaveLlmConfigParams(routing_max_tokens="999999")


def test_bool_field_blank_does_not_raise():
    fields = [
        n for n, f in SaveLlmConfigParams.model_fields.items()
        if bool in getattr(f.annotation, "__args__", ())
    ]
    assert fields, "expected at least one Optional[bool] field to exist"
    for name in fields:
        params = SaveLlmConfigParams(**{name: ""})
        assert getattr(params, name) is None
