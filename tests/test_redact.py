"""init(redact=True): personal data is masked before a trace leaves the process; rules see real values."""
from unittest.mock import patch

import kalytera
from kalytera import tracer
from kalytera.redact import mask, mask_text


def test_masks_emails_phones_and_cards() -> None:
    text = ("Refund jane.doe@example.com, call +1 (415) 555-0132 or 0044 20 7946 0958, "
            "card 4111 1111 1111 1111.")
    assert mask_text(text) == "Refund [email], call [phone] or [phone], card [card]."


def test_leaves_amounts_ids_dates_and_bad_card_numbers() -> None:
    text = "Refund $900 for order A4100 on 2026-10-14T03:09:44, ref 12345, card 4111 1111 1111 1112."
    assert mask_text(text) == text  # 4111…1112 fails the card check, and 16 digits is too long for a phone
    assert mask_text("Order 98765 costs 1,250.00") == "Order 98765 costs 1,250.00"


def test_masks_inside_tool_arguments_but_keeps_numbers() -> None:
    calls = [{"name": "refund_api", "input": {"email": "a@b.co", "amount": 900, "notes": ["call 415-555-0132"]}}]
    assert mask(calls) == [{"name": "refund_api", "input": {"email": "[email]", "amount": 900,
                                                            "notes": ["call [phone]"]}}]


def test_trace_payload_is_masked_only_when_turned_on() -> None:
    with patch.object(tracer, "_redact", False):
        p = tracer._build_payload("s", 1, "x", "mail a@b.co", "ok", [], {}, "agent", False)
        assert p["input"] == "mail a@b.co"
    with patch.object(tracer, "_redact", True):
        p = tracer._build_payload("s", 1, "x", "mail a@b.co", "card 4111111111111111",
                                  [{"name": "t", "input": {"to": "a@b.co"}}], {"user": "a@b.co"}, "agent", False)
        assert (p["input"], p["output"]) == ("mail [email]", "card [card]")
        assert p["tool_calls"][0]["input"]["to"] == "[email]" and p["metadata"]["user"] == "[email]"


def test_init_turns_it_on(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    saved = tracer._redact
    try:
        kalytera.init(api_key="kly_live_x", agent_id="a", verify=False, instrument=False, redact=True)
        assert tracer._redact is True
        monkeypatch.setenv("KALYTERA_REDACT", "1")
        kalytera.init(api_key="kly_live_x", agent_id="a", verify=False, instrument=False)
        assert tracer._redact is True
        monkeypatch.delenv("KALYTERA_REDACT")
        kalytera.init(api_key="kly_live_x", agent_id="a", verify=False, instrument=False)
        assert tracer._redact is False
    finally:
        tracer._redact = saved
