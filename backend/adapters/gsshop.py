import json
import re
import time
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from adapters.base import CrawlArtifacts, ImageCandidate, PlatformAdapter
from text_utils import clean_text, parse_price


class GsShopAdapter(PlatformAdapter):
    def match_url(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return "gsshop.com" in host

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
            required_info = self._extract_required_info(page)
            seller_name, seller_name_source = self._extract_seller_name(required_info)

            dom_main = page.evaluate(
                """() => Array.from(document.querySelectorAll('#slideWrap img, .prd_zoom img')).map(el => ({
                    src: el.getAttribute('src')
                }))"""
            )

            detail_raw = []
            frame = page.frame(name="prdDetailIfr")
            if frame:
                try:
                    frame.wait_for_load_state("domcontentloaded", timeout=15000)
                except Exception:
                    pass
                time.sleep(1)
                detail_raw = frame.evaluate(
                    """() => Array.from(document.querySelectorAll('img')).map(el => ({
                        src: el.getAttribute('src') || el.getAttribute('data-src') || el.getAttribute('data-original'),
                        w: el.naturalWidth || el.width,
                        h: el.naturalHeight || el.height
                    }))"""
                )

            product_name = (
                clean_text((product or {}).get("name"))
                or self._text(page, "p.product-title")
                or self._text(page, "p.tit")
            )
            offers = (product or {}).get("offers") or {}
            price_text = self._text(page, ".price-definition-ins strong")
            price = parse_price(price_text)
            if price is None and isinstance(offers, dict):
                price = parse_price(offers.get("price"))

            browser.close()

        ld_images = (product or {}).get("image") or []
        if isinstance(ld_images, str):
            ld_images = [ld_images]

        images: list[ImageCandidate] = []
        for src in ld_images:
            if src and not self._is_placeholder(src):
                images.append(ImageCandidate(url=src, role="main"))
        if not images:
            for item in dom_main:
                src = item.get("src")
                if src and not self._is_placeholder(src) and (not product_no or product_no in src):
                    images.append(ImageCandidate(url=src, role="main"))

        for item in detail_raw:
            src = item.get("src")
            width = int(item.get("w") or 0)
            height = int(item.get("h") or 0)
            if not src or self._is_placeholder(src):
                continue
            if height <= 1 or width <= 1:
                continue
            # Detail asset URLs are namespaced by product id
            # (…/orgdesc/{prdid}/…), which keeps this scoped to this product
            # only and excludes any ads/recommendations rendered inside the frame.
            if product_no and product_no not in src:
                continue
            images.append(ImageCandidate(url=src, role="detail"))

        unique_images = list(dict.fromkeys((img.url, img.role) for img in images))

        return CrawlArtifacts(
            final_page_url=final_url,
            page_title=page_title,
            page_content=page_content,
            screenshot_path=screenshot_path,
            images=[ImageCandidate(url=u, role=role) for u, role in unique_images],
            platform="GS SHOP",
            category=None,
            seller_name=seller_name,
            seller_name_source=seller_name_source,
            product_name=product_name,
            price=price,
            debug={
                "required_info": required_info,
                "as_manager_raw": required_info.get("A/S 책임자와 전화번호"),
                "manufacturer_importer_raw": required_info.get("제조자, 수입품의 경우 수입자를 함께 표기"),
                "consignment_info_raw": required_info.get("위탁판매자 정보") or required_info.get("위탁판매자정보"),
            },
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
            candidates = data.get("@graph") if isinstance(data, dict) else None
            if not candidates:
                candidates = [data]
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

    def _extract_product_no(self, url: str) -> str | None:
        match = re.search(r"prdid=(\d+)", url)
        return match.group(1) if match else None

    def _extract_required_info(self, page) -> dict[str, str]:
        self._open_required_info_tab(page)
        try:
            page.locator("#ProTab04 .prd_info_tbl, #ProTab04 table").first.wait_for(
                state="visible", timeout=10000
            )
        except Exception:
            pass
        rows = page.evaluate(
            """() => {
                const root = document.querySelector('#ProTab04') || document.querySelector('.normalN.ProTabContent') || document;
                const result = {};
                const pairs = [];
                for (const tr of root.querySelectorAll('tr')) {
                    const label = (tr.querySelector('th')?.innerText || '').replace(/\\s+/g, ' ').trim();
                    const value = (tr.querySelector('td')?.innerText || '').replace(/\\s+/g, ' ').trim();
                    if (label && value) pairs.push([label, value]);
                }
                for (const dl of root.querySelectorAll('dl')) {
                    const label = (dl.querySelector('dt')?.innerText || '').replace(/\\s+/g, ' ').trim();
                    const value = (dl.querySelector('dd')?.innerText || '').replace(/\\s+/g, ' ').trim();
                    if (label && value) pairs.push([label, value]);
                }
                for (const [label, value] of pairs) {
                    result[label] = value;
                }
                return result;
            }"""
        )
        return {clean_text(k) or "": clean_text(v) or "" for k, v in rows.items() if clean_text(k) and clean_text(v)}

    def _open_required_info_tab(self, page) -> None:
        try:
            locator = page.locator("a.tab, button, a").filter(has_text="필수정보").first
            locator.click(timeout=10000)
            time.sleep(1)
            return
        except Exception:
            pass
        try:
            page.locator('a[href="#ProTabN04"]').first.click(timeout=10000)
            time.sleep(1)
        except Exception:
            pass

    def _extract_seller_name(self, required_info: dict[str, str]) -> tuple[str, str]:
        as_raw = required_info.get("A/S 책임자와 전화번호")
        as_name = self._extract_name_from_as_manager(as_raw)
        if as_name:
            return as_name, "as_manager"

        manufacturer_raw = required_info.get("제조자, 수입품의 경우 수입자를 함께 표기")
        manufacturer_name = self._extract_name_from_manufacturer(manufacturer_raw)
        if manufacturer_name:
            return manufacturer_name, "manufacturer_importer"

        consignment_raw = required_info.get("위탁판매자 정보") or required_info.get("위탁판매자정보")
        consignment_name = self._extract_name_from_consignment(consignment_raw)
        if consignment_name:
            return consignment_name, "consignment_info"

        return "GS SHOP", "platform_fallback"

    def _extract_name_from_as_manager(self, raw: str | None) -> str | None:
        if not raw:
            return None
        text = clean_text(raw)
        if not text:
            return None
        text = re.split(r",|/|\\|\\(|\\)|\\[|\\]", text)[0]
        text = re.split(r"0\\d{1,2}-\\d{3,4}-\\d{4}", text)[0]
        text = re.sub(r"[\\s\\-_:]+", "", text or "")
        if not text or self._is_invalid_seller_text(text):
            return None
        return text

    def _extract_name_from_manufacturer(self, raw: str | None) -> str | None:
        if not raw:
            return None
        parts = [clean_text(part) for part in re.split(r"[/,|]", raw)]
        for part in parts:
            if not part:
                continue
            if self._looks_like_brand_only(part):
                continue
            if self._is_invalid_seller_text(part):
                continue
            return re.sub(r"[\\s\\-_:]+", "", part)
        return None

    def _extract_name_from_consignment(self, raw: str | None) -> str | None:
        if not raw:
            return None
        text = clean_text(raw)
        if not text:
            return None
        if "GS SHOP 고객센터" in text or "고객센터" in text:
            return None
        text = re.split(r"0\\d{1,2}-\\d{3,4}-\\d{4}", text)[0]
        text = re.sub(r"[\\(\\)\\[\\],]+", " ", text)
        text = clean_text(text)
        if not text or self._is_invalid_seller_text(text):
            return None
        return re.sub(r"[\\s\\-_:]+", "", text)

    def _looks_like_brand_only(self, text: str) -> bool:
        lowered = text.lower()
        generic_tokens = {
            "아디다스",
            "adidas",
            "나이키",
            "nike",
            "뉴발란스",
            "puma",
            "푸마",
            "일반수입",
            "병행수입",
            "수입자",
            "제조자",
        }
        return lowered in generic_tokens

    def _is_invalid_seller_text(self, text: str) -> bool:
        lowered = text.lower()
        if not text:
            return True
        if re.fullmatch(r"[0-9\\-\\s]+", text):
            return True
        if "gsshop고객센터" in lowered or "고객센터" in text:
            return True
        if "gs shop" in lowered and len(text) <= 10:
            return True
        return False
