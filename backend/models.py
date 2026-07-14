import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import relationship

from database import Base


def gen_uuid():
    return str(uuid.uuid4())


class Seller(Base):
    __tablename__ = "sellers"

    id = Column(String, primary_key=True, default=gen_uuid)
    platform = Column(String, nullable=False)  # naver_smartstore / coupang / 11st / etc
    seller_name = Column(String, nullable=True)
    product_url = Column(Text, nullable=False)
    status = Column(String, default="pending")  # pending / active / archived
    memo = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Excel row matched by product_url, imported once and preserved as-is.
    source_platform_name = Column(String, nullable=True)
    source_category = Column(String, nullable=True)
    source_seller_name = Column(String, nullable=True)
    source_product_name = Column(String, nullable=True)
    source_price = Column(Integer, nullable=True)

    # Extracted from the live product page DOM on each successful crawl.
    scraped_platform = Column(String, nullable=True)
    scraped_category = Column(String, nullable=True)
    scraped_seller_name = Column(String, nullable=True)
    seller_name_source = Column(String, nullable=True)
    scraped_product_name = Column(String, nullable=True)
    scraped_price = Column(Integer, nullable=True)
    scraped_at = Column(DateTime, nullable=True)

    crawl_jobs = relationship(
        "CrawlJob", back_populates="seller", cascade="all, delete-orphan"
    )
    images = relationship(
        "CollectedImage", back_populates="seller", cascade="all, delete-orphan"
    )


class CrawlJob(Base):
    __tablename__ = "crawl_jobs"

    id = Column(String, primary_key=True, default=gen_uuid)
    seller_id = Column(String, ForeignKey("sellers.id"), nullable=False)
    status = Column(String, default="pending")
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    final_page_url = Column(Text, nullable=True)
    screenshot_path = Column(Text, nullable=True)
    status_reason = Column(Text, nullable=True)

    seller = relationship("Seller", back_populates="crawl_jobs")
    images = relationship(
        "CollectedImage", back_populates="crawl_job", cascade="all, delete-orphan"
    )


class CollectedImage(Base):
    __tablename__ = "collected_images"

    id = Column(String, primary_key=True, default=gen_uuid)
    crawl_job_id = Column(String, ForeignKey("crawl_jobs.id"), nullable=False)
    seller_id = Column(String, ForeignKey("sellers.id"), nullable=False)
    source_image_url = Column(Text, nullable=False)
    storage_path = Column(Text, nullable=False)
    image_hash = Column(String, nullable=True)
    sha256_hash = Column(String, nullable=True)
    image_role = Column(String, nullable=True, default="unknown")
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    display_order = Column(Integer, nullable=True)
    collected_at = Column(DateTime, default=datetime.utcnow)

    seller = relationship("Seller", back_populates="images")
    crawl_job = relationship("CrawlJob", back_populates="images")
