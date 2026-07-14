import re
from urllib.parse import urlparse


BLOCKED_TOKENS = [
    "just a moment",
    "cloudflare",
    "access denied",
    "captcha",
    "로그인",
    "login",
]

# Short English tokens that also occur as substrings of unrelated identifiers
# (e.g. a RequireJS module path "cjos/util/logininfo" contains "login" but is
# not a login wall). These are matched on word boundaries instead of as a bare
# substring; the rest of BLOCKED_TOKENS are long/specific enough that a plain
# substring match doesn't produce false positives.
_WORD_BOUNDARY_TOKENS = {"login", "captcha"}


def detect_blocked_page(
    final_page_url: str | None, page_title: str | None, page_content: str | None
) -> str | None:
    url = (final_page_url or "").lower()
    title = (page_title or "").lower()
    content = (page_content or "").lower()
    host = (urlparse(final_page_url or "").hostname or "").lower()

    if host == "nid.naver.com":
        return "redirected_to_naver_login"

    parsed_path = urlparse(final_page_url or "").path.lower()
    if host == "link.gmarket.co.kr" and "/gate/" in parsed_path:
        return "gmarket_gate_page"

    haystack = " ".join([title, content[:5000]])
    for token in BLOCKED_TOKENS:
        if token in _WORD_BOUNDARY_TOKENS:
            if re.search(rf"\b{re.escape(token)}\b", haystack):
                return f"blocked_page_detected:{token}"
        elif token in haystack:
            return f"blocked_page_detected:{token}"

    if "smartstore.naver.com" not in url and host == "nid.naver.com":
        return "not_a_product_page"

    return None
