import json
import re
import time
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from adapters.base import CrawlArtifacts, ImageCandidate, PlatformAdapter
from text_utils import clean_text, parse_price


class CjOnstyleAdapter(PlatformAdapter):
    def match_url(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return "cjonstyle.com" in host

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
            page.goto(url, wait_until="networkidle", timeout=60000)
            time.sleep(2)
            for _ in range(6):
                page.mouse.wheel(0, 1600)
                time.sleep(0.5)

            final_url = page.url
            page_title = page.title()
            page_content = page.content()
            screenshot_path = f"{artifact_dir}\\page_full.png"
            page.screenshot(path=screenshot_path, full_page=True)

            product = self._extract_json_ld_product(page)
            product_no = self._extract_product_no(final_url)

            main_raw = page.evaluate(
                """() => Array.from(document.querySelectorAll('.prd_img img')).map(el => ({
                    src: el.getAttribute('src'), w: el.naturalWidth || el.width, h: el.naturalHeight || el.height
                }))"""
            )

            category_segments = page.evaluate(
                """() => Array.from(document.querySelectorAll('.u_breadcrumbs_wrap ul li a')).map(a => a.innerText.trim())"""
            )
            category_segments = [s for s in category_segments if s]

            product_name = clean_text((product or {}).get("name")) or self._text(page, "h3.prd_tit")
            offers = (product or {}).get("offers") or {}
            price = parse_price(offers.get("price")) if isinstance(offers, dict) else None

            detail_raw = []
            detail_frame = None
            for frame in page.frames:
                if "itemExplainAreaInfo" in (frame.url or ""):
                    detail_frame = frame
                    break
            if detail_frame:
                try:
                    detail_frame.wait_for_load_state("domcontentloaded", timeout=15000)
                except Exception:
                    pass
                time.sleep(1)
                detail_raw = detail_frame.evaluate(
                    """() => Array.from(document.querySelectorAll('img')).map(el => ({
                        src: el.getAttribute('src') || el.getAttribute('data-src') || el.getAttribute('data-original'),
                        w: el.naturalWidth || el.width,
                        h: el.naturalHeight || el.height
                    }))"""
                )

            browser.close()

        images: list[ImageCandidate] = []
        # `.prd_img` is reused by more than one widget on the page (e.g. a
        # "recently viewed" thumb alongside the real product photo), and the CDN
        # serves the same underlying file at multiple sizes via a
        # `fit-in/{w}x{h}/` prefix. Group by the file identity (URL minus that
        # size prefix) and keep only the largest-resolution copy of each.
        best_by_identity: dict[str, tuple[int, str]] = {}
        for item in main_raw:
            src = item.get("src")
            if not src or self._is_placeholder(src):
                continue
            if product_no and product_no not in src:
                continue
            normalized = self._normalize(src)
            identity, area = self._image_identity_and_size(normalized)
            if identity not in best_by_identity or area > best_by_identity[identity][0]:
                best_by_identity[identity] = (area, normalized)
        for _, url_ in best_by_identity.values():
            images.append(ImageCandidate(url=url_, role="main"))

        for item in detail_raw:
            src = item.get("src")
            width = int(item.get("w") or 0)
            height = int(item.get("h") or 0)
            if not src or self._is_placeholder(src):
                continue
            if height <= 1 or width <= 1:
                continue
            # CJ온스타일 marks its own detail badge/icon assets with an "ICON"
            # path segment; those are UI decoration, not product evidence.
            if "icon" in src.lower():
                continue
            images.append(ImageCandidate(url=self._normalize(src), role="detail"))

        unique_images = list(dict.fromkeys((img.url, img.role) for img in images))

        return CrawlArtifacts(
            final_page_url=final_url,
            page_title=page_title,
            page_content=page_content,
            screenshot_path=screenshot_path,
            images=[ImageCandidate(url=u, role=role) for u, role in unique_images],
            platform="cjonstyle",
            category=" > ".join(category_segments) if category_segments else None,
            seller_name="CJ온스타일",
            product_name=product_name,
            price=price,
        )

    def extract_images(self, url: str) -> list[str]:
        artifacts = self.crawl(url, artifact_dir=".")
        return [img.url for img in artifacts.images]

    def extract_meta(self, url: str) -> dict:
        return {}

    def _extract_json_ld_product(self, page) -> dict | None:
        try:
            blocks = page.evaluate(
                "() => Array.from(document.querySelectorAll('script[type=\"application/ld+json\"]'))"
                ".map(s => s.textContent)"
            )
        except Exception:
            return None
        for block in blocks:
            try:
                data = json.loads(block)
            except (ValueError, TypeError):
                continue
            candidates = data if isinstance(data, list) else [data]
            for item in candidates:
                if isinstance(item, dict) and item.get("@type") == "Product":
                    return item
        return None

    def _text(self, page, selector: str) -> str | None:
        try:
            locator = page.locator(selector).first
            if locator.count() == 0:
                return None
            return clean_text(locator.inner_text(timeout=2000))
        except Exception:
            return None

    def _is_placeholder(self, url: str) -> bool:
        return url.startswith("data:") or not url.strip()

    def _normalize(self, url: str) -> str:
        return f"https:{url}" if url.startswith("//") else url

    def _image_identity_and_size(self, url: str) -> tuple[str, int]:
        match = re.search(r"/fit-in/(\d+)x(\d+)/", url)
        if not match:
            return url, 0
        width, height = int(match.group(1)), int(match.group(2))
        identity = url[: match.start()] + url[match.end() :]
        return identity, width * height

    def _extract_product_no(self, url: str) -> str | None:
        match = re.search(r"/p/item/(\d+)", url)
        return match.group(1) if match else None
