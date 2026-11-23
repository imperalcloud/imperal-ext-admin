"""Admin · LLM Config · the model pickers of a section that has many of them.

Every model list on this page is the whole list: each model of each provider
that has a key. Measured 2026-11-23 that is 318 OpenRouter models alone,
27 KB as one ui.Select - and "Per-Purpose Models" has 12 such pickers, 330 KB
against the kernel's 256 KB reply cap. So a section with many model slots
draws ONE of them as the list; the others show the model they hold and a
button that opens their list. A save sends the open slot (and the section's
other inputs) and leaves the closed slots as they are: save_llm_config
touches only the fields a save carried.
"""
from __future__ import annotations

from imperal_sdk import ui

ALL = "*"            # every slot drawn as a list (the whole-page render of the tests)


def opened(slots: list[str], asked: str) -> str:
    """Which slot of a section is drawn as the list: the one asked for when it
    is this section's, else the first."""
    if asked == ALL:
        return ALL
    return asked if asked in slots else (slots[0] if slots else "")


def with_current(options: list[dict], value: str) -> list[dict]:
    """The options plus the saved model when the list does not hold it (a model
    typed by hand, or one its provider no longer lists): the select must not
    show a held value as blank."""
    if not value or any(o.get("value") == value for o in options):
        return options
    head = [o for o in options if not o.get("value")]
    return head + [{"value": value, "label": f"{value} (saved; not in the lists)"}] + [o for o in options if o.get("value")]


def model_slot(param_name: str, value: str, options: list[dict], placeholder: str,
               view: str, open_slot: str, on_open=None) -> list:
    """The nodes of one model slot. ``on_open(param_name)`` is the action that
    opens a closed slot; without it the slot belongs to LLM Config's ``view``."""
    if open_slot in (ALL, param_name):
        return [ui.Select(options=with_current(options, value), value=value, param_name=param_name,
                          placeholder=placeholder)]
    action = on_open(param_name) if on_open else ui.Call(
        "__panel__tools", section="llm", llm_view=view, llm_slot=param_name, run_test="")
    return [ui.Stack(direction="h", gap=1, children=[
        ui.Text(value or placeholder, variant="body"),
        ui.Button(label="Choose model", variant="ghost", size="sm", on_click=action),
    ])]
