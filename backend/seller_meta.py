from datetime import datetime

from storage_naming import lookup_excel_metadata_by_url
from text_utils import clean_text, parse_price


def import_source_metadata_if_needed(seller) -> bool:
    """Populate source_* fields from the Excel row matched by product_url, exactly
    once. Excel Platform/Category/SellerName/ProductName/Price are known to be
    unreliable, so they're kept only as this original reference snapshot and are
    never used as final values or overwritten on later imports."""
    already_imported = any(
        [
            seller.source_platform_name,
            seller.source_category,
            seller.source_seller_name,
            seller.source_product_name,
            seller.source_price is not None,
        ]
    )
    if already_imported:
        return False
    row = lookup_excel_metadata_by_url(seller.product_url)
    if not row:
        return False
    seller.source_platform_name = clean_text(row.get("Platform"))
    seller.source_category = clean_text(row.get("Category"))
    seller.source_seller_name = clean_text(row.get("SellerName"))
    seller.source_product_name = clean_text(row.get("ProductName"))
    seller.source_price = parse_price(row.get("Price"))
    return True


def apply_scraped_meta(seller, artifacts) -> bool:
    """Update scraped_* fields from a CrawlArtifacts' page-extracted meta. Only
    fields the adapter actually found are overwritten, so a partial extraction on
    one run can't blank out good values collected by an earlier run."""
    updated = False
    if artifacts.platform:
        seller.scraped_platform = artifacts.platform
        updated = True
    if artifacts.category:
        seller.scraped_category = artifacts.category
        updated = True
    if artifacts.seller_name:
        seller.scraped_seller_name = artifacts.seller_name
        updated = True
    if artifacts.seller_name_source:
        seller.seller_name_source = artifacts.seller_name_source
        updated = True
    if artifacts.product_name:
        seller.scraped_product_name = artifacts.product_name
        updated = True
    if artifacts.price is not None:
        seller.scraped_price = artifacts.price
        updated = True
    if updated:
        seller.scraped_at = datetime.utcnow()
    return updated
