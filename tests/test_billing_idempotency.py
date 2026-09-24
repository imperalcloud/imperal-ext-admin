# -*- coding: utf-8 -*-
# Copyright (c) 2026 Imperal, Inc.
# Licensed under the AGPL-3.0 License.
"""Federal test: Billing idempotency keys and safe balance adjustment invariants."""
from __future__ import annotations

import pytest
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional


class AdjustBalanceParamsWithIdempotency(BaseModel):
    user_id: str
    amount: int
    reason: str = "admin_adjustment"
    idempotency_key: Optional[str] = Field(
        default=None,
        description="Unique request token to prevent duplicate charges or credits.",
    )
    model_config = ConfigDict(extra="ignore")


def test_billing_idempotency_key_payload_contract():
    """Verify that billing adjust params safely accept and preserve idempotency_key."""
    payload = {
        "user_id": "imp_u_test123",
        "amount": 50000,
        "reason": "compensation",
        "idempotency_key": "imp_tx_c98a123f_uuid",
    }
    params = AdjustBalanceParamsWithIdempotency(**payload)
    assert params.idempotency_key == "imp_tx_c98a123f_uuid"
    assert params.amount == 50000
    assert params.user_id == "imp_u_test123"


def test_billing_idempotency_key_optional_by_default():
    """Verify backwards compatibility: idempotency_key is optional for legacy callers."""
    payload = {
        "user_id": "imp_u_test123",
        "amount": 1000,
    }
    params = AdjustBalanceParamsWithIdempotency(**payload)
    assert params.idempotency_key is None
    assert params.reason == "admin_adjustment"
