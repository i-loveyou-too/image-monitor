import hashlib
import io
import os
import shutil
import tempfile
from datetime import datetime

import imagehash
import requests
from PIL import Image
from sqlalchemy.orm import Session

import models
from adapters.generic import HEADERS
from adapters.registry import get_adapter_for_url
from crawl_detection import detect_blocked_page
from seller_meta import apply_scraped_meta, import_source_metadata_if_needed
from storage_naming import (
    resolve_job_storage_dir,
    resolve_seller_storage_dir,
    write_metadata_json,
)

STORAGE_DIR = os.path.join(os.path.dirname(__file__), "storage")
_SCREENSHOT_FILENAME = "page_full.png"


def run_crawl(db: Session, seller: models.Seller) -> models.CrawlJob:
    if import_source_metadata_if_needed(seller):
        db.commit()
        db.refresh(seller)

    job = models.CrawlJob(
        seller_id=seller.id,
        status="running",
        started_at=datetime.utcnow(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    os.makedirs(STORAGE_DIR, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix="_crawl_tmp_", dir=STORAGE_DIR)
    job_dir = None

    try:
        adapter = get_adapter_for_url(seller.product_url)
        # Adapter visits the URL once and both extracts page meta and takes the
        # screenshot in that same browser session; the screenshot lands in tmp_dir
        # since we don't know the final storage folder name until after scraped_*
        # is updated below.
        artifacts = adapter.crawl(seller.product_url, artifact_dir=tmp_dir)

        job.final_page_url = artifacts.final_page_url

        blocked_reason = detect_blocked_page(
            artifacts.final_page_url,
            artifacts.page_title,
            artifacts.page_content,
        )

        if not blocked_reason and apply_scraped_meta(seller, artifacts):
            db.commit()
            db.refresh(seller)

        # Folder name is resolved AFTER scraped_* so a successful extraction is
        # reflected immediately; on a blocked/failed run scraped_* is untouched and
        # resolve_seller_storage_dir naturally falls back to source_*/URL-derived
        # values instead.
        seller_dir = resolve_seller_storage_dir(STORAGE_DIR, seller)
        job_dir = resolve_job_storage_dir(seller_dir, job.started_at or datetime.utcnow())
        images_dir = os.path.join(job_dir, "images")
        os.makedirs(images_dir, exist_ok=True)
        job.screenshot_path = _relocate_screenshot(artifacts.screenshot_path, job_dir)

        if blocked_reason:
            job.status = "blocked"
            job.status_reason = blocked_reason
            job.finished_at = datetime.utcnow()
            write_metadata_json(job_dir, seller=seller, job=job)
            db.commit()
            db.refresh(job)
            return job

        saved_count = 0
        role_counters: dict[str, int] = {}
        detail_entries: list[tuple[int, str]] = []
        for idx, image in enumerate(artifacts.images):
            if _looks_like_non_product_image(image.url):
                continue
            try:
                resp = requests.get(image.url, headers=HEADERS, timeout=30)
                resp.raise_for_status()
                content = resp.content

                img = Image.open(io.BytesIO(content))
                width, height = img.size
                if width <= 1 or height <= 1:
                    continue

                phash = str(imagehash.phash(img))
                sha256_hash = hashlib.sha256(content).hexdigest()

                role = image.role or "unknown"
                ext = _guess_ext(image.url, img.format)
                role_counters[role] = role_counters.get(role, 0) + 1
                filename = f"{role}_{role_counters[role]:03d}{ext}"
                filepath = os.path.join(images_dir, filename)
                with open(filepath, "wb") as f:
                    f.write(content)

                display_order = idx + 1
                record = models.CollectedImage(
                    crawl_job_id=job.id,
                    seller_id=seller.id,
                    source_image_url=image.url,
                    storage_path=filepath,
                    image_hash=phash,
                    sha256_hash=sha256_hash,
                    image_role=role,
                    width=width,
                    height=height,
                    display_order=display_order,
                )
                db.add(record)
                saved_count += 1
                if role == "detail":
                    detail_entries.append((display_order, filepath))
            except Exception:
                continue

        job.finished_at = datetime.utcnow()
        if saved_count > 0:
            job.status = "success"
            job.status_reason = f"saved_valid_images:{saved_count}"
        else:
            job.status = "no_images"
            job.status_reason = "no_valid_product_images_detected"

        if len(detail_entries) >= 2:
            detail_entries.sort(key=lambda entry: entry[0])
            _build_detail_merged_image(
                [path for _, path in detail_entries],
                os.path.join(job_dir, "detail_merged.png"),
            )

        write_metadata_json(job_dir, seller=seller, job=job)
        db.commit()

    except Exception as e:
        job.status = "failed"
        job.error_message = str(e)
        job.status_reason = "crawl_exception"
        job.finished_at = datetime.utcnow()
        if job_dir is None:
            # Failed before a folder was resolved (e.g. adapter.crawl() itself
            # raised): fall back to whatever seller fields are currently set
            # (source_*/existing/URL, since scraped_* was never reached).
            try:
                seller_dir = resolve_seller_storage_dir(STORAGE_DIR, seller)
                job_dir = resolve_job_storage_dir(seller_dir, job.started_at or datetime.utcnow())
            except Exception:
                job_dir = None
        if job_dir and not job.screenshot_path:
            # Salvage a screenshot that made it to tmp_dir before the failure.
            leftover = os.path.join(tmp_dir, _SCREENSHOT_FILENAME)
            job.screenshot_path = _relocate_screenshot(leftover, job_dir)
        if job_dir and (job.screenshot_path or job.final_page_url):
            write_metadata_json(job_dir, seller=seller, job=job)
        db.commit()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    db.refresh(job)
    return job


def _relocate_screenshot(tmp_path: str | None, job_dir: str) -> str | None:
    if not tmp_path or not os.path.isfile(tmp_path):
        return None
    final_path = os.path.join(job_dir, _SCREENSHOT_FILENAME)
    try:
        shutil.move(tmp_path, final_path)
        return final_path
    except OSError:
        return None


def _guess_ext(url: str, pil_format: str | None) -> str:
    for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"]:
        if url.lower().split("?")[0].endswith(ext):
            return ext
    if pil_format:
        return "." + pil_format.lower()
    return ".jpg"


def _build_detail_merged_image(image_paths: list[str], output_path: str) -> str | None:
    """Vertically stack detail images in display order. Animated GIF/WebP sources
    contribute only their first frame; the original files on disk are untouched."""
    frames = []
    try:
        for path in image_paths:
            with Image.open(path) as im:
                im.seek(0)
                frames.append(im.convert("RGBA"))
        if len(frames) < 2:
            return None
        max_width = max(f.width for f in frames)
        total_height = sum(f.height for f in frames)
        canvas = Image.new("RGBA", (max_width, total_height), (255, 255, 255, 255))
        y = 0
        for frame in frames:
            canvas.paste(frame, (0, y), frame)
            y += frame.height
        canvas.convert("RGB").save(output_path, "PNG")
        return output_path
    except Exception:
        return None


def _looks_like_non_product_image(url: str) -> bool:
    lowered = url.lower()
    blocked_tokens = [
        "logo",
        "icon",
        "qr",
        "captcha",
        "spacer",
        "blank",
        "1x1",
    ]
    return any(token in lowered for token in blocked_tokens)
