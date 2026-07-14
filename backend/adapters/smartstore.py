import time
from urllib.parse import urlparse

from browser_session import BrowserSessionManager
from adapters.base import CrawlArtifacts, ImageCandidate, PlatformAdapter
from text_utils import clean_text, parse_price

LOGIN_WAIT_SECONDS = 20


class SmartstoreAdapter(PlatformAdapter):
    """smartstore.naver.com requires an authenticated Naver session for
    almost every product page; without one it redirects straight to
    nid.naver.com. A headful, persistent Chrome profile doesn't change that
    (there is no login cookie in the profile and we don't automate logging
    in), so this adapter's job is mainly to detect that redirect quickly,
    record it precisely, and get out — not to force a way through it."""

    def match_url(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return "smartstore.naver.com" in host

    def crawl(self, url: str, artifact_dir: str) -> CrawlArtifacts:
        manager = BrowserSessionManager.instance()
        # All Playwright calls below must run on BrowserSessionManager's one
        # dedicated worker thread (see browser_session.py) — never on
        # whatever FastAPI threadpool thread happens to call crawl().
        return manager.run_task(lambda page: self._crawl_on_page(page, url, artifact_dir))

    def _crawl_on_page(self, page, url: str, artifact_dir: str) -> CrawlArtifacts:
        actions: list[str] = []

        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        actions.append("navigated_to_gate_url")

        login_or_captcha = False
        deadline = time.time() + LOGIN_WAIT_SECONDS
        while time.time() < deadline:
            host = urlparse(page.url).hostname or ""
            if host == "nid.naver.com":
                login_or_captcha = True
                break
            if self._has_captcha_iframe(page):
                login_or_captcha = True
                break
            if host == "smartstore.naver.com" and self._product_dom_present(page):
                break
            time.sleep(1)

        final_url = page.url
        page_title = page.title()
        page_content = page.content()

        if login_or_captcha:
            actions.append("redirected_to_naver_login_or_captcha")
            screenshot_path = f"{artifact_dir}\\page_full.png"
            page.screenshot(path=screenshot_path, full_page=True)
            return CrawlArtifacts(
                final_page_url=final_url,
                page_title=page_title,
                page_content=page_content,
                screenshot_path=screenshot_path,
                status_reason="naver_login_or_captcha",
                images=[],
                platform="smartstore",
                debug={"actions": actions},
            )

        actions.append("redirected_to_product_url")

        self._click_if_present(page, ["text=상세정보", "text=더보기", "text=상품정보"], "clicked_expand_button", actions)

        for step in range(1, 9):
            page.mouse.wheel(0, 1600)
            actions.append(f"scrolled_step_{step}")
            time.sleep(0.6)
        actions.append("reached_page_bottom")
        time.sleep(1)

        product_name = self._text(page, "h3.top_product_info_title, h3[class*=title]") or clean_text(page_title)
        seller_name = self._text(page, "[class*=seller_info] strong, a[class*=seller_name]")
        price_text = self._text(page, "[class*=lowestPrice] strong, [class*=price] strong")
        price = parse_price(price_text)
        category = self._extract_category(page)

        main_raw = page.evaluate(
            """() => Array.from(document.querySelectorAll('[class*=thumbnail] img, [class*=Thumbnail] img')).map(el => ({
                src: el.getAttribute('src') || el.getAttribute('data-src')
            }))"""
        )

        detail_raw = []
        detail_frame = None
        for frame in page.frames:
            if "NaverPay" not in (frame.url or "") and "product" in (frame.url or "").lower():
                detail_frame = frame
                break
        if detail_frame is None:
            # SmartStore usually renders the detail description inline
            # (no iframe) inside a dedicated content container.
            detail_raw = page.evaluate(
                """() => Array.from(document.querySelectorAll('[class*=se-main-container] img, [class*=detail] img')).map(el => ({
                    src: el.getAttribute('src') || el.getAttribute('data-src'),
                    w: el.naturalWidth || el.width,
                    h: el.naturalHeight || el.height
                }))"""
            )
            if detail_raw:
                actions.append("entered_detail_iframe")
        else:
            actions.append("entered_detail_iframe")
            try:
                detail_frame.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:
                pass
            detail_raw = detail_frame.evaluate(
                """() => Array.from(document.querySelectorAll('img')).map(el => ({
                    src: el.getAttribute('src') || el.getAttribute('data-src'),
                    w: el.naturalWidth || el.width,
                    h: el.naturalHeight || el.height
                }))"""
            )

        screenshot_path = f"{artifact_dir}\\page_full.png"
        page.screenshot(path=screenshot_path, full_page=True)

        images: list[ImageCandidate] = []
        for item in main_raw:
            src = item.get("src")
            if src and not src.startswith("data:"):
                images.append(ImageCandidate(url=src, role="main"))
        if images:
            actions.append("extracted_main_images")

        for item in detail_raw:
            src = item.get("src")
            width, height = int(item.get("w") or 0), int(item.get("h") or 0)
            if not src or src.startswith("data:"):
                continue
            if width <= 1 or height <= 1:
                continue
            images.append(ImageCandidate(url=src, role="detail"))
        if detail_raw:
            actions.append("extracted_detail_images")

        unique_images = list(dict.fromkeys((img.url, img.role) for img in images))

        return CrawlArtifacts(
            final_page_url=final_url,
            page_title=page_title,
            page_content=page_content,
            screenshot_path=screenshot_path,
            images=[ImageCandidate(url=u, role=role) for u, role in unique_images],
            platform="smartstore",
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

    def _has_captcha_iframe(self, page) -> bool:
        try:
            return page.locator("iframe[id*=captcha], iframe[id*=ncaptcha]").count() > 0
        except Exception:
            return False

    def _product_dom_present(self, page) -> bool:
        try:
            return page.locator("h3.top_product_info_title, [class*=se-main-container]").count() > 0
        except Exception:
            return False

    def _click_if_present(self, page, selectors: list[str], action_name: str, actions: list[str]) -> None:
        for selector in selectors:
            try:
                locator = page.locator(selector).first
                if locator.count() == 0:
                    continue
                locator.click(timeout=3000)
                actions.append(action_name)
                time.sleep(0.8)
                return
            except Exception:
                continue
        actions.append(f"skipped_{action_name}")

    def _text(self, page, selector: str) -> str | None:
        try:
            locator = page.locator(selector).first
            if locator.count() == 0:
                return None
            return clean_text(locator.inner_text(timeout=2000))
        except Exception:
            return None

    def _extract_category(self, page) -> str | None:
        try:
            segments = page.evaluate(
                """() => Array.from(document.querySelectorAll('[class*=breadcrumb] a, [class*=Breadcrumb] a')).map(a => a.innerText.trim())"""
            )
            segments = [s for s in segments if s]
            return " > ".join(segments) if segments else None
        except Exception:
            return None
