"""The imperal-mcp frame price is edited with the rest of the coding pricing (one place for prices)."""
import pytest

import handlers_system_pricing as hsp


@pytest.mark.asyncio
async def test_save_coding_pricing_sends_the_mcp_frame_price(ctx, monkeypatch):
    sent = {}

    async def fake_put(path, body, acting=None, forbidden_message=""):
        sent[path] = body
        return {"action": "saved"}, None

    monkeypatch.setattr(hsp, "_admin_put_checked", fake_put)
    monkeypatch.setattr(hsp, "AUTH_GW", "http://gw")
    monkeypatch.setattr(hsp, "AUTH_SERVICE_TOKEN", "t")
    res = await hsp.fn_save_coding_pricing(ctx, hsp.SaveCodingPricingParams(
        markup=3.0, credits_per_dollar=1000, min_charge=0, grace_cap=1000, low_warn_threshold=500, mcp_frame=5))
    assert sent["/v1/internal/billing/coding-pricing"]["mcp_frame"] == 5
    assert res.data["mcp_frame"] == 5 and "frame 5" in res.summary


def test_a_negative_mcp_frame_price_is_refused():
    with pytest.raises(Exception):
        hsp.SaveCodingPricingParams(markup=3.0, credits_per_dollar=1000, min_charge=0, grace_cap=1000,
                                    low_warn_threshold=500, mcp_frame=-1)


def test_the_panel_form_carries_the_mcp_frame_price():
    import inspect
    import panels_system_pricing as psp
    src = inspect.getsource(psp)
    assert 'param_name="mcp_frame"' in src and '"mcp_frame": int(coding.get("mcp_frame"' in src
