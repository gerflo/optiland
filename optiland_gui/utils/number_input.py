"""Parsing of numbers the user types into the GUI's tables."""

from __future__ import annotations


def parse_user_float(value: str) -> float:
    """Parse a user-entered number, accepting a comma decimal separator.

    A single comma without a dot is treated as a decimal comma
    (``"97,1"`` -> 97.1); commas alongside a dot are treated as
    thousands separators (``"1,234.5"`` -> 1234.5).

    Args:
        value: The text as typed, possibly with (non-breaking) spaces.

    Returns:
        The parsed number.

    Raises:
        ValueError: If the text is not a number.
    """
    text = str(value).strip().replace(" ", "").replace(" ", "")
    if "," in text:
        if "." not in text and text.count(",") == 1:
            text = text.replace(",", ".")
        else:
            text = text.replace(",", "")
    return float(text)
