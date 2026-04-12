"""Tests for CardKit transport helpers."""

from __future__ import annotations

import json

from hermes_feishu_plugin.card.cardkit import _card_json_payload


def test_card_json_payload_uses_cardkit_wrapper_shape() -> None:
    """CardKit updates should send ``type=card_json`` wrapper payloads."""
    payload = _card_json_payload({"schema": "2.0", "body": {"elements": []}})

    assert payload["type"] == "card_json"
    assert json.loads(payload["data"]) == {"schema": "2.0", "body": {"elements": []}}
