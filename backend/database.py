from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# MVP: SQLite로 시작. 추후 PostgreSQL로 이관 시 DATABASE_URL만 교체하면 됨.
DATABASE_URL = "sqlite:///./image_monitor.db"

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_database():
    from models import CrawlJob, CollectedImage, Seller  # noqa: F401

    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        _ensure_column(conn, "crawl_jobs", "final_page_url", "TEXT")
        _ensure_column(conn, "crawl_jobs", "screenshot_path", "TEXT")
        _ensure_column(conn, "crawl_jobs", "status_reason", "TEXT")
        _ensure_column(conn, "collected_images", "sha256_hash", "VARCHAR")
        _ensure_column(conn, "collected_images", "image_role", "VARCHAR")
        _ensure_column(conn, "collected_images", "display_order", "INTEGER")
        _ensure_column(conn, "sellers", "source_platform_name", "VARCHAR")
        _ensure_column(conn, "sellers", "source_category", "VARCHAR")
        _ensure_column(conn, "sellers", "source_seller_name", "VARCHAR")
        _ensure_column(conn, "sellers", "source_product_name", "VARCHAR")
        _ensure_column(conn, "sellers", "source_price", "INTEGER")
        _ensure_column(conn, "sellers", "scraped_platform", "VARCHAR")
        _ensure_column(conn, "sellers", "scraped_category", "VARCHAR")
        _ensure_column(conn, "sellers", "scraped_seller_name", "VARCHAR")
        _ensure_column(conn, "sellers", "seller_name_source", "VARCHAR")
        _ensure_column(conn, "sellers", "scraped_product_name", "VARCHAR")
        _ensure_column(conn, "sellers", "scraped_price", "INTEGER")
        _ensure_column(conn, "sellers", "scraped_at", "DATETIME")


def _ensure_column(conn, table_name: str, column_name: str, column_type: str):
    rows = conn.exec_driver_sql(f"PRAGMA table_info({table_name})").fetchall()
    existing = {row[1] for row in rows}
    if column_name in existing:
        return
    conn.exec_driver_sql(
        f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
    )


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
