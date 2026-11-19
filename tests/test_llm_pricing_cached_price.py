"""A model's rate row states the provider's price of cached input (2026-11-19).

The kernel prices a call term by term, so a Webbee Code turn costs its real
provider cost x the coding markup. The admin extension is the one writer of the
row: omitted = the row keeps its cached price, empty/null = it states none.
"""
from __future__ import annotations

import asyncio

import pytest

import handlers_pricing
import panels_pricing
from handlers_pricing import SaveLlmModelRateParams


class _Resp:
    status_code = 200
    text = ""
    def json(self): return {"action": "updated"}


class _Client:
    sent: list = []
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def put(self, url, headers=None, json=None):
        _Client.sent.append((url, json))
        return _Resp()


def _save(monkeypatch, **kw):
    _Client.sent = []
    monkeypatch.setattr(handlers_pricing, "shared_http", lambda timeout=5.0: _Client())
    monkeypatch.setattr(handlers_pricing, "AUTH_GW", "http://gw")
    monkeypatch.setattr(handlers_pricing, "AUTH_SERVICE_TOKEN", "t")
    base = dict(model_id="m", tier="economy", input_cost_per_1k=0.000825, output_cost_per_1k=0.004125)
    base.update(kw)
    res = asyncio.run(handlers_pricing.fn_save_llm_model_rate(None, SaveLlmModelRateParams(**base)))
    return res, (_Client.sent[-1][1] if _Client.sent else None)


def test_a_stated_cached_price_is_sent(monkeypatch):
    _, body = _save(monkeypatch, cached_input_cost_per_1k=0.0000825)
    assert body["cached_input_cost_per_1k"] == pytest.approx(0.0000825)


def test_an_omitted_cached_price_is_not_sent_so_the_row_keeps_its_own(monkeypatch):
    _, body = _save(monkeypatch)
    assert "cached_input_cost_per_1k" not in body


def test_an_emptied_field_clears_the_cached_price(monkeypatch):
    for blank in ("", "  ", None):
        _, body = _save(monkeypatch, cached_input_cost_per_1k=blank)
        assert "cached_input_cost_per_1k" in body and body["cached_input_cost_per_1k"] is None


def test_a_form_string_is_read_as_a_number(monkeypatch):
    _, body = _save(monkeypatch, cached_input_cost_per_1k="0.0000825")
    assert body["cached_input_cost_per_1k"] == pytest.approx(0.0000825)


def test_a_cached_price_above_the_input_price_is_refused_before_any_call(monkeypatch):
    _, body = _save(monkeypatch, cached_input_cost_per_1k=0.01)
    assert body is None


def test_prices_are_shown_per_million_without_rounding_small_ones_away():
    assert panels_pricing._per_million(0.0000825) == "$0.0825"
    assert panels_pricing._per_million(0.003) == "$3"
    assert panels_pricing._per_million(0.000825) == "$0.825"
    assert panels_pricing._per_million(None) == "—"
    assert panels_pricing._per_million(0) == "$0"
