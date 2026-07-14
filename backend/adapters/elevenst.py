import time
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright

from adapters.base import CrawlArtifacts, ImageCandidate, PlatformAdapter
from text_utils import clean_text, parse_price


class ElevenStAdapter(PlatformAdapter):
    def match_url(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return "11st.co.kr" in host

    def crawl(self, url: str, artifact_dir: str) -> CrawlArtifacts:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1440, "height": 2200},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            )
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            time.sleep(3)

            for _ in range(8):
                page.mouse.wheel(0, 1800)
                time.sleep(1)

            final_url = page.url
            page_title = page.title()
            page_content = page.content()
            screenshot_path = f"{artifact_dir}\\page_full.png"
            page.screenshot(path=screenshot_path, full_page=True)

            main_images = page.locator("img").evaluate_all(
                """els => els.map(el => ({
                    src: el.getAttribute('src'),
                    dataSrc: el.getAttribute('data-src'),
                    dataOriginal: el.getAttribute('data-original'),
                    srcset: el.getAttribute('srcset'),
                    width: el.naturalWidth || el.width,
                    height: el.naturalHeight || el.height,
                    alt: el.getAttribute('alt')
                }))"""
            )

            detail_images = []
            frame = page.frame(name="prdDescIfrm")
            if frame:
                time.sleep(2)
                detail_images = frame.locator("img").evaluate_all(
                    """els => els.map(el => ({
                        src: el.getAttribute('src'),
                        dataSrc: el.getAttribute('data-src'),
                        dataOriginal: el.getAttribute('data-original'),
                        srcset: el.getAttribute('srcset'),
                        width: el.naturalWidth || el.width,
                        height: el.naturalHeight || el.height,
                        alt: el.getAttribute('alt')
                    }))"""
                )

            meta = self._extract_meta_from_page(page)

            browser.close()

        product_no = self._extract_product_no(final_url)
        images: list[ImageCandidate] = []
        for item in main_images:
            candidate = self._pick_url(item)
            if candidate and self._is_useful_main_image(candidate, item, product_no):
                images.append(ImageCandidate(url=candidate, role="main"))
        for item in detail_images:
            candidate = self._pick_url(item)
            if candidate and self._is_useful_detail_image(candidate, item):
                images.append(ImageCandidate(url=candidate, role="detail"))

        unique_images = list(dict.fromkeys((img.url, img.role) for img in images))
        return CrawlArtifacts(
            final_page_url=final_url,
            page_title=page_title,
            page_content=page_content,
            screenshot_path=screenshot_path,
            images=[ImageCandidate(url=u, role=role) for u, role in unique_images],
            platform="11st",
            category=meta["category"],
            seller_name=meta["seller_name"],
            product_name=meta["product_name"],
            price=meta["price"],
        )

    def _extract_meta_from_page(self, page) -> dict:
        """Extract seller_name / product_name / price / category from the actual
        11st product page DOM. Every lookup is best-effort: a missing element
        yields None rather than raising, so a partial page never breaks the crawl."""

        def text_of(selector: str) -> str | None:
            try:
                locator = page.locator(selector).first
                if locator.count() == 0:
                    return None
                return clean_text(locator.inner_text(timeout=2000))
            except Exception:
                return None

        product_name = text_of("h1.title")

        seller_name = text_of("h1.c_product_store_title") or text_of(
            "a[href*='shop.11st.co.kr/stores']"
        )

        price_text = text_of("#finalDscPrcArea .price .value") or text_of(
            ".b_product_info_price .price .value"
        )
        price = parse_price(price_text)

        category = None
        try:
            segments_locator = page.locator(".c_product_category_path em.selected")
            segments = []
            for i in range(segments_locator.count()):
                segment = clean_text(segments_locator.nth(i).inner_text(timeout=1000))
                if segment:
                    segments.append(segment)
            if segments:
                category = " > ".join(segments)
        except Exception:
            category = None

        return {
            "product_name": product_name,
            "seller_name": seller_name,
            "price": price,
            "category": category,
        }

    def extract_images(self, url: str) -> list[str]:
        artifacts = self.crawl(url, artifact_dir=".")
        return [img.url for img in artifacts.images]

    def extract_meta(self, url: str) -> dict:
        return {}

    def _pick_url(self, item: dict) -> str | None:
        for key in ("src", "dataSrc", "dataOriginal", "srcset"):
            value = item.get(key)
            if not value:
                continue
            if key == "srcset":
                value = value.split(",")[0].strip().split(" ")[0]
            if value.startswith("data:"):
                continue
            return value
        return None

    def _is_useful_main_image(
        self, url: str, item: dict, product_no: str | None
    ) -> bool:
        width = int(item.get("width") or 0)
        height = int(item.get("height") or 0)
        alt = (item.get("alt") or "").lower()
        if width < 200 or height < 200:
            return False
        if "qr" in alt or "icon" in alt:
            return False
        return bool(product_no and f"/product/{product_no}/" in url)

    def _is_useful_detail_image(self, url: str, item: dict) -> bool:
        width = int(item.get("width") or 0)
        height = int(item.get("height") or 0)
        if width <= 1 or height <= 1:
            return False
        return width >= 300 and height >= 300

    def _extract_product_no(self, url: str) -> str | None:
        parsed = urlparse(url)
        if "/products/" in parsed.path:
            try:
                return parsed.path.split("/products/")[1].split("/")[0]
            except Exception:
                return None
        query = parse_qs(parsed.query)
        if "prdNo" in query and query["prdNo"]:
            return query["prdNo"][0]
        return None
