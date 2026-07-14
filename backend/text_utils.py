import re

WHITESPACE_RE = re.compile(r"\s+")
NON_DIGIT_RE = re.compile(r"[^0-9]")


def clean_text(value) -> str | None:
    """Strip and collapse whitespace/newlines. Returns None for empty input."""
    if value is None:
        return None
    text = str(value).replace("\r", " ").replace("\n", " ").replace("\t", " ")
    text = WHITESPACE_RE.sub(" ", text).strip()
    return text or None


def parse_price(value) -> int | None:
    """Parse a price from an Excel cell (int/float/str) or scraped DOM text
    (e.g. '98,120원') into a plain KRW integer amount."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(round(value))
    digits = NON_DIGIT_RE.sub("", str(value))
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None
