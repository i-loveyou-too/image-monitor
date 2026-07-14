from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from adapters.base import CrawlArtifacts, ImageCandidate, PlatformAdapter

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


class GenericAdapter(PlatformAdapter):
    def match_url(self, url: str) -> bool:
        return True

    def crawl(self, url: str, artifact_dir: str) -> CrawlArtifacts:
        final_url = url
        page_title = None
        page_content = None
        screenshot_path = None

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    viewport={"width": 1440, "height": 2200},
                    user_agent=HEADERS["User-Agent"],
                )
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                final_url = page.url
                page_title = page.title()
                page_content = page.content()
                screenshot_path = f"{artifact_dir}\\page_full.png"
                page.screenshot(path=screenshot_path, full_page=True)
                browser.close()
        except Exception:
            pass

        soup, response = self._get_soup(url)
        if response is not None:
            final_url = response.url
            if page_content is None:
                page_content = response.text
        if page_title is None and soup is not None:
            title_tag = soup.find("title")
            page_title = title_tag.text.strip() if title_tag else None

        images: list[ImageCandidate] = []
        if soup is not None:
            for img in soup.find_all("img"):
                src = (
                    img.get("src")
                    or img.get("data-src")
                    or img.get("data-original")
                    or _first_srcset_url(img.get("srcset"))
                )
                if not src:
                    continue
                images.append(ImageCandidate(url=urljoin(final_url, src), role="unknown"))

        unique_images = list(dict.fromkeys((img.url, img.role) for img in images))
        return CrawlArtifacts(
            final_page_url=final_url,
            page_title=page_title,
            page_content=page_content,
            screenshot_path=screenshot_path,
            images=[ImageCandidate(url=u, role=role) for u, role in unique_images],
        )

    def _get_soup(self, url: str) -> tuple[BeautifulSoup | None, requests.Response | None]:
        try:
            res = requests.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
            res.raise_for_status()
            return BeautifulSoup(res.text, "html.parser"), res
        except Exception:
            return None, None

    def extract_images(self, url: str) -> list[str]:
        artifacts = self.crawl(url, artifact_dir=".")
        return [img.url for img in artifacts.images]

    def extract_meta(self, url: str) -> dict:
        soup, _ = self._get_soup(url)
        title_tag = soup.find("title") if soup else None
        return {"title": title_tag.text.strip() if title_tag else None}


def _first_srcset_url(srcset: str | None) -> str | None:
    if not srcset:
        return None
    return srcset.split(",")[0].strip().split(" ")[0]
