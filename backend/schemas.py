from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class SellerCreate(BaseModel):
    platform: str
    product_url: str
    seller_name: Optional[str] = None
    memo: Optional[str] = None


class SellerOut(BaseModel):
    id: str
    platform: str
    product_url: str
    seller_name: Optional[str]
    status: str
    memo: Optional[str]
    created_at: datetime

    # Excel row matched by product_url, imported once and preserved as-is.
    source_platform_name: Optional[str] = None
    source_category: Optional[str] = None
    source_seller_name: Optional[str] = None
    source_product_name: Optional[str] = None
    source_price: Optional[int] = None

    # Extracted from the live product page DOM on the most recent successful crawl.
    scraped_platform: Optional[str] = None
    scraped_category: Optional[str] = None
    scraped_seller_name: Optional[str] = None
    seller_name_source: Optional[str] = None
    scraped_product_name: Optional[str] = None
    scraped_price: Optional[int] = None
    scraped_at: Optional[datetime] = None

    # Final display values: scraped_* if present, else source_* (falls back
    # further to existing seller fields / a URL-derived label where applicable).
    display_platform: Optional[str] = None
    display_category: Optional[str] = None
    display_seller_name: Optional[str] = None
    display_product_name: Optional[str] = None
    display_price: Optional[int] = None

    class Config:
        from_attributes = True


class CrawlJobOut(BaseModel):
    id: str
    seller_id: str
    status: str
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    error_message: Optional[str]
    final_page_url: Optional[str]
    screenshot_path: Optional[str]
    status_reason: Optional[str]

    class Config:
        from_attributes = True


class CrawlJobSummary(BaseModel):
    id: str
    seller_id: str
    status: str
    status_reason: Optional[str]
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    final_page_url: Optional[str]
    screenshot_path: Optional[str]
    collected_image_count: int
    main_image_count: int
    detail_image_count: int

    class Config:
        from_attributes = True


class CollectedImageOut(BaseModel):
    id: str
    source_image_url: str
    storage_path: str
    image_hash: Optional[str]
    sha256_hash: Optional[str]
    image_role: Optional[str]
    width: Optional[int]
    height: Optional[int]
    display_order: Optional[int]
    collected_at: datetime

    class Config:
        from_attributes = True
