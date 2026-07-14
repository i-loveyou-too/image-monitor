from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models
import schemas
from database import get_db
from crawler import run_crawl
from seller_meta import import_source_metadata_if_needed
from storage_naming import (
    delete_seller_storage,
    delete_storage_paths,
    resolve_display,
    resolve_display_price,
)
import os

router = APIRouter(prefix="/sellers", tags=["sellers"])


def _seller_to_out(seller: models.Seller) -> schemas.SellerOut:
    out = schemas.SellerOut.model_validate(seller)
    out.display_platform = resolve_display(seller, "platform")
    out.display_category = resolve_display(seller, "category")
    out.display_seller_name = resolve_display(seller, "seller_name")
    out.display_product_name = resolve_display(seller, "product_name")
    out.display_price = resolve_display_price(seller)
    return out


@router.post("", response_model=schemas.SellerOut)
def create_seller(payload: schemas.SellerCreate, db: Session = Depends(get_db)):
    seller = models.Seller(**payload.model_dump())
    db.add(seller)
    db.commit()
    db.refresh(seller)
    if import_source_metadata_if_needed(seller):
        db.commit()
        db.refresh(seller)
    return _seller_to_out(seller)


@router.get("", response_model=list[schemas.SellerOut])
def list_sellers(db: Session = Depends(get_db)):
    sellers = db.query(models.Seller).order_by(models.Seller.created_at.desc()).all()
    return [_seller_to_out(seller) for seller in sellers]


@router.get("/{seller_id}", response_model=schemas.SellerOut)
def get_seller(seller_id: str, db: Session = Depends(get_db)):
    seller = db.query(models.Seller).filter(models.Seller.id == seller_id).first()
    if not seller:
        raise HTTPException(status_code=404, detail="Seller not found")
    return _seller_to_out(seller)


@router.delete("/{seller_id}")
def delete_seller(seller_id: str, db: Session = Depends(get_db)):
    seller = db.query(models.Seller).filter(models.Seller.id == seller_id).first()
    if not seller:
        raise HTTPException(status_code=404, detail="Seller not found")
    image_paths = [
        row[0]
        for row in db.query(models.CollectedImage.storage_path)
        .filter(models.CollectedImage.seller_id == seller_id)
        .all()
    ]
    screenshot_paths = [
        row[0]
        for row in db.query(models.CrawlJob.screenshot_path)
        .filter(models.CrawlJob.seller_id == seller_id)
        .all()
        if row[0]
    ]
    db.delete(seller)
    db.commit()
    delete_storage_paths(image_paths + screenshot_paths)
    storage_root = os.path.join(os.path.dirname(__file__), "..", "storage")
    delete_seller_storage(os.path.abspath(storage_root), seller_id)
    return {"ok": True}


@router.post("/{seller_id}/crawl", response_model=schemas.CrawlJobOut)
def trigger_crawl(seller_id: str, db: Session = Depends(get_db)):
    seller = db.query(models.Seller).filter(models.Seller.id == seller_id).first()
    if not seller:
        raise HTTPException(status_code=404, detail="Seller not found")
    job = run_crawl(db, seller)
    return job


@router.get("/{seller_id}/images", response_model=list[schemas.CollectedImageOut])
def list_images(seller_id: str, db: Session = Depends(get_db)):
    return (
        db.query(models.CollectedImage)
        .filter(models.CollectedImage.seller_id == seller_id)
        .order_by(models.CollectedImage.collected_at.desc())
        .all()
    )


@router.get("/{seller_id}/jobs", response_model=list[schemas.CrawlJobSummary])
def list_seller_jobs(seller_id: str, db: Session = Depends(get_db)):
    seller = db.query(models.Seller).filter(models.Seller.id == seller_id).first()
    if not seller:
        raise HTTPException(status_code=404, detail="Seller not found")
    jobs = (
        db.query(models.CrawlJob)
        .filter(models.CrawlJob.seller_id == seller_id)
        .order_by(models.CrawlJob.started_at.desc())
        .all()
    )
    results = []
    for job in jobs:
        images = (
            db.query(models.CollectedImage.image_role)
            .filter(models.CollectedImage.crawl_job_id == job.id)
            .all()
        )
        roles = [row[0] or "unknown" for row in images]
        results.append(
            schemas.CrawlJobSummary(
                id=job.id,
                seller_id=job.seller_id,
                status=job.status,
                status_reason=job.status_reason,
                started_at=job.started_at,
                finished_at=job.finished_at,
                final_page_url=job.final_page_url,
                screenshot_path=job.screenshot_path,
                collected_image_count=len(roles),
                main_image_count=sum(1 for role in roles if role == "main"),
                detail_image_count=sum(1 for role in roles if role == "detail"),
            )
        )
    return results
