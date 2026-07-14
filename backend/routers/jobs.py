from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case, func
from sqlalchemy.orm import Session

import models
import schemas
from database import get_db

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _job_query(db: Session):
    return (
        db.query(
            models.CrawlJob.id.label("id"),
            models.CrawlJob.seller_id.label("seller_id"),
            models.CrawlJob.status.label("status"),
            models.CrawlJob.status_reason.label("status_reason"),
            models.CrawlJob.started_at.label("started_at"),
            models.CrawlJob.finished_at.label("finished_at"),
            models.CrawlJob.final_page_url.label("final_page_url"),
            models.CrawlJob.screenshot_path.label("screenshot_path"),
            func.count(models.CollectedImage.id).label("collected_image_count"),
            func.sum(
                case((models.CollectedImage.image_role == "main", 1), else_=0)
            ).label("main_image_count"),
            func.sum(
                case((models.CollectedImage.image_role == "detail", 1), else_=0)
            ).label("detail_image_count"),
        )
        .outerjoin(
            models.CollectedImage,
            models.CollectedImage.crawl_job_id == models.CrawlJob.id,
        )
        .group_by(models.CrawlJob.id)
    )


def _serialize_job(row) -> schemas.CrawlJobSummary:
    return schemas.CrawlJobSummary(
        id=row.id,
        seller_id=row.seller_id,
        status=row.status,
        status_reason=row.status_reason,
        started_at=row.started_at,
        finished_at=row.finished_at,
        final_page_url=row.final_page_url,
        screenshot_path=row.screenshot_path,
        collected_image_count=int(row.collected_image_count or 0),
        main_image_count=int(row.main_image_count or 0),
        detail_image_count=int(row.detail_image_count or 0),
    )


@router.get("", response_model=list[schemas.CrawlJobSummary])
def list_jobs(db: Session = Depends(get_db)):
    rows = _job_query(db).order_by(models.CrawlJob.started_at.desc()).all()
    return [_serialize_job(row) for row in rows]


@router.get("/{job_id}", response_model=schemas.CrawlJobSummary)
def get_job(job_id: str, db: Session = Depends(get_db)):
    row = _job_query(db).filter(models.CrawlJob.id == job_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    return _serialize_job(row)
