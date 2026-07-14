from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ImageCandidate:
    url: str
    role: str = "unknown"


@dataclass
class CrawlArtifacts:
    final_page_url: str
    page_title: str | None = None
    page_content: str | None = None
    screenshot_path: str | None = None
    status_reason: str | None = None
    images: list[ImageCandidate] = field(default_factory=list)
    # Meta scraped from the actual product page DOM (None when the adapter
    # doesn't implement extraction yet, or the page was blocked/unreachable).
    platform: str | None = None
    category: str | None = None
    seller_name: str | None = None
    seller_name_source: str | None = None
    product_name: str | None = None
    price: int | None = None
    debug: dict[str, object] = field(default_factory=dict)


class PlatformAdapter(ABC):
    @abstractmethod
    def match_url(self, url: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def crawl(self, url: str, artifact_dir: str) -> CrawlArtifacts:
        raise NotImplementedError

    @abstractmethod
    def extract_images(self, url: str) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def extract_meta(self, url: str) -> dict:
        raise NotImplementedError
