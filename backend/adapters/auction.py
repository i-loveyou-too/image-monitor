import time
from urllib.parse import urlparse

from adapters.base import CrawlArtifacts, ImageCandidate, PlatformAdapter
from selenium_session import SeleniumSessionManager
from text_utils import clean_text, parse_price

CLOUDFLARE_WAIT_SECONDS = 30
REDIRECT_WAIT_SECONDS = 15
OVERALL_BUDGET_SECONDS = 60
CHALLENGE_TITLE_TOKENS = ["just a moment", "잠시만 기다리십시오", "잠시만 기다려", "please wait"]

# Assets served alongside the real product image from the same seller CDN but
# that are generic template UI (shipping-cost caution banner, AS-policy
# banner, section title labels, claim badge) rather than product evidence.
NON_PRODUCT_DETAIL_TOKENS = ["tit_info", "tit_dinfo", "caution", "claim_a", "_as.gif", "/all-"]


class AuctionAdapter(PlatformAdapter):
    """Auction (link.auction.co.kr) sits behind Cloudflare. A headless or
    headless-fingerprinted Playwright session never gets past the "Just a
    moment..." challenge (verified: it still shows 30s later). A headful
    Selenium session with Chrome's own automation-detection switches turned
    off does reach the real item page, so this adapter drives that instead of
    the shared Playwright BrowserSessionManager used by the other adapters."""

    def match_url(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return "auction.co.kr" in host

    def crawl(self, url: str, artifact_dir: str) -> CrawlArtifacts:
        actions: list[str] = []
        start = time.time()
        manager = SeleniumSessionManager.instance()

        with manager.tab_session() as driver:
            driver.get(url)
            actions.append("navigated_to_gate_url")

            redirect_deadline = time.time() + REDIRECT_WAIT_SECONDS
            while time.time() < redirect_deadline:
                if (urlparse(driver.current_url).hostname or "") != "link.auction.co.kr":
                    actions.append("redirected_to_product_url")
                    break
                time.sleep(0.5)

            resolved, failure_reason = self._wait_for_challenge_clear(driver, actions)
            final_url = driver.current_url
            page_title = driver.title

            if not resolved:
                screenshot_path = self._screenshot(driver, artifact_dir)
                return CrawlArtifacts(
                    final_page_url=final_url,
                    page_title=page_title,
                    page_content=driver.page_source,
                    screenshot_path=screenshot_path,
                    status_reason=failure_reason,
                    images=[],
                    platform="auction",
                    debug={"actions": actions},
                )

            self._click_if_present(
                driver, ["#itemInfo_tab"], "clicked_product_detail_tab", actions
            )
            # Note: a generic "더보기"/".dropdown" click was tried here but
            # removed — on Auction's item page that selector also matches the
            # category breadcrumb's "더보기" link, whose href runs
            # NavigationBar.goUrl(...) and navigates away to the category
            # browse page instead of expanding anything on the product page.
            # The detail description iframe (hIfrmExplainView) renders on its
            # own without needing an expand click, so this is a no-op skip.
            actions.append("skipped_clicked_expand_button")

            ld_product = self._extract_json_ld_product(driver)
            seller_name = self._extract_seller_name(driver)
            category = self._extract_category(driver)
            price = self._extract_price(driver, ld_product)
            product_name = (
                clean_text((ld_product or {}).get("name"))
                or self._text(driver, ".itemtit")
                or clean_text(driver.title)
            )

            detail_images: list[str] = []
            if self._time_left(start) > 5:
                detail_frame = self._find_element(driver, "id", "hIfrmExplainView")
                if detail_frame is not None:
                    try:
                        driver.switch_to.frame(detail_frame)
                        actions.append("entered_detail_iframe")
                        time.sleep(1.5)
                        detail_images = self._extract_detail_images(driver)
                    finally:
                        driver.switch_to.default_content()

            self._scroll_to_bottom(driver, actions, start)

            page_content = driver.page_source
            screenshot_path = self._screenshot(driver, artifact_dir)

        images: list[ImageCandidate] = []
        main_image = (ld_product or {}).get("image")
        if isinstance(main_image, list):
            main_image = main_image[0] if main_image else None
        if main_image:
            images.append(ImageCandidate(url=self._normalize(main_image), role="main"))
            actions.append("extracted_main_images")

        if detail_images:
            for src in detail_images:
                images.append(ImageCandidate(url=self._normalize(src), role="detail"))
            actions.append("extracted_detail_images")

        unique_images = list(dict.fromkeys((img.url, img.role) for img in images))

        return CrawlArtifacts(
            final_page_url=final_url,
            page_title=page_title,
            page_content=page_content,
            screenshot_path=screenshot_path,
            images=[ImageCandidate(url=u, role=role) for u, role in unique_images],
            platform="auction",
            category=category,
            seller_name=seller_name,
            product_name=product_name,
            price=price,
            debug={"actions": actions},
        )

    def extract_images(self, url: str) -> list[str]:
        artifacts = self.crawl(url, artifact_dir=".")
        return [img.url for img in artifacts.images]

    def extract_meta(self, url: str) -> dict:
        return {}

    def _time_left(self, start: float) -> float:
        return OVERALL_BUDGET_SECONDS - (time.time() - start)

    def _wait_for_challenge_clear(self, driver, actions: list[str]) -> tuple[bool, str | None]:
        """Wait for the Cloudflare challenge title to go away AND the real
        product DOM to actually render (the title can briefly show a generic
        site/category title while the SPA is still transitioning, which is
        not the same as the product page being ready)."""
        deadline = time.time() + CLOUDFLARE_WAIT_SECONDS
        challenge_seen = False
        while time.time() < deadline:
            title = (driver.title or "").lower()
            is_challenge = any(token in title for token in CHALLENGE_TITLE_TOKENS)
            if is_challenge:
                challenge_seen = True
            elif self._product_dom_ready(driver):
                actions.append(
                    "cloudflare_challenge_resolved" if challenge_seen else "product_dom_ready"
                )
                return True, None
            time.sleep(1)
        if challenge_seen:
            return False, "cloudflare_challenge_not_resolved"
        return False, "product_dom_not_found"

    def _product_dom_ready(self, driver) -> bool:
        try:
            el = driver.find_element("css selector", ".itemtit")
            return bool(el.text.strip())
        except Exception:
            return False

    def _click_if_present(self, driver, selectors: list[str], action_name: str, actions: list[str]) -> None:
        for selector in selectors:
            try:
                if selector.startswith("text="):
                    els = driver.find_elements(
                        "xpath", f"//*[contains(text(), '{selector[5:]}')]"
                    )
                    el = els[0] if els else None
                else:
                    els = driver.find_elements("css selector", selector)
                    el = els[0] if els else None
                if el is None:
                    continue
                el.click()
                actions.append(action_name)
                time.sleep(0.8)
                return
            except Exception:
                continue
        actions.append(f"skipped_{action_name}")

    def _text(self, driver, selector: str) -> str | None:
        try:
            el = driver.find_element("css selector", selector)
            return clean_text(el.text)
        except Exception:
            return None

    def _find_element(self, driver, by: str, value: str):
        try:
            return driver.find_element(by, value)
        except Exception:
            return None

    def _scroll_to_bottom(self, driver, actions: list[str], start: float, max_steps: int = 8) -> None:
        last_height = driver.execute_script("return document.body.scrollHeight")
        for step in range(1, max_steps + 1):
            if self._time_left(start) < 8:
                break
            driver.execute_script("window.scrollBy(0, 1600);")
            actions.append(f"scrolled_step_{step}")
            time.sleep(0.6)
            new_height = driver.execute_script("return document.body.scrollHeight")
            at_bottom = driver.execute_script(
                "return (window.innerHeight + window.scrollY) >= document.body.scrollHeight - 50"
            )
            if at_bottom and new_height == last_height:
                break
            last_height = new_height
        actions.append("reached_page_bottom")
        time.sleep(1)  # let any lazy-loaded images finish requesting

    def _screenshot(self, driver, artifact_dir: str) -> str:
        screenshot_path = f"{artifact_dir}\\page_full.png"
        driver.save_screenshot(screenshot_path)
        return screenshot_path

    def _extract_json_ld_product(self, driver) -> dict | None:
        import json

        try:
            blocks = driver.execute_script(
                "return Array.from(document.querySelectorAll('script[type=\"application/ld+json\"]'))"
                ".map(s => s.textContent)"
            )
        except Exception:
            return None
        for block in blocks or []:
            try:
                data = json.loads(block)
            except (TypeError, ValueError):
                continue
            candidates = data if isinstance(data, list) else [data]
            for item in candidates:
                if isinstance(item, dict) and item.get("@type") == "Product":
                    return item
        return None

    def _extract_seller_name(self, driver) -> str | None:
        try:
            els = driver.find_elements("css selector", "[class*=seller]")
        except Exception:
            return None
        for el in els:
            text = clean_text(el.text)
            if text and len(text) <= 30 and "\n" not in (el.text or ""):
                return text
        return None

    def _extract_category(self, driver) -> str | None:
        try:
            el = driver.find_element("css selector", ".category_wrap a.dropdown")
            text = el.text.replace("더보기", "").strip()
            return clean_text(text)
        except Exception:
            return None

    def _extract_price(self, driver, ld_product: dict | None) -> int | None:
        try:
            els = driver.find_elements("css selector", "[class*=price] strong")
            for el in els:
                text = el.text.replace("판매가", "").strip()
                price = parse_price(text)
                if price:
                    return price
        except Exception:
            pass
        if ld_product:
            description = ld_product.get("description")
            price = parse_price(description)
            if price:
                return price
        return None

    def _extract_detail_images(self, driver) -> list[str]:
        # Unlike Playwright's page.evaluate(), Selenium's execute_script() runs
        # the string as a plain function BODY — an arrow-function expression
        # with no `return` just gets defined and discarded, always yielding
        # None. This needs an explicit `return`. Also retried briefly since
        # the detail iframe can still be mid-navigation right after switching
        # into it.
        raw = None
        for _ in range(5):
            raw = driver.execute_script(
                """return Array.from(document.querySelectorAll('img')).map(function(el) {
                    return {
                        src: el.getAttribute('src') || el.getAttribute('data-src') || el.getAttribute('data-original'),
                        w: el.naturalWidth || el.width,
                        h: el.naturalHeight || el.height
                    };
                });"""
            )
            if raw is not None:
                break
            time.sleep(0.5)
        results = []
        for item in raw or []:
            src = item.get("src")
            width, height = int(item.get("w") or 0), int(item.get("h") or 0)
            if not src or src.startswith("data:"):
                continue
            if height <= 1 or width <= 1:
                continue
            lowered = src.lower()
            if any(token in lowered for token in NON_PRODUCT_DETAIL_TOKENS):
                continue
            results.append(src)
        return results

    def _normalize(self, url: str) -> str:
        return f"https:{url}" if url.startswith("//") else url
