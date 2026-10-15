"""
Mask personal data before a trace leaves your process: kalytera.init(redact=True).

Replaced with a placeholder: email addresses, phone numbers (10-15 digits) and
card numbers (13-19 digits that pass the Luhn check). Applied to step input and
output, tool-call arguments and metadata. Rules are checked on the real values in
your process, so blocking is unaffected.

Pattern matching, not a guarantee: names, addresses and unusual formats are not
caught, and a long numeric ID can be masked as a phone number.
"""
import re
from typing import Any

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
DIGIT_RUN = re.compile(r"(?<![\w.])\+?\d[\d \-().]{8,22}\d(?![\w])")


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


def _digits(match: "re.Match[str]") -> str:
    raw = match.group(0)
    digits = re.sub(r"\D", "", raw)
    if 13 <= len(digits) <= 19 and _luhn(digits):
        return "[card]"
    if 10 <= len(digits) <= 15:
        return "[phone]"
    return raw


def mask_text(text: str) -> str:
    return DIGIT_RUN.sub(_digits, EMAIL.sub("[email]", text))


def mask(value: Any) -> Any:
    """Mask strings anywhere in a JSON-like value. Numbers stay numbers (amounts, counts)."""
    if isinstance(value, str):
        return mask_text(value)
    if isinstance(value, dict):
        return {k: mask(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [mask(v) for v in value]
    return value
