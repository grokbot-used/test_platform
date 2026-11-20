"""Case comments with optional pasted/uploaded images."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
import shutil

from fastapi import HTTPException, UploadFile
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import FILES_DIR
from app.models import CaseComment, TestCase

ALLOWED_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
}
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGES = 9
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
CST = timezone(timedelta(hours=8))

ENVIRONMENTS = (
    ("test", "测试线"),
    ("cn_pre", "国内预发布"),
    ("overseas_pre", "海外预发布"),
    ("cn_prod", "国内正式线"),
    ("overseas_prod", "海外正式线"),
)
ENV_KEYS = {key for key, _label in ENVIRONMENTS}
ENV_LABELS = {key: label for key, label in ENVIRONMENTS}


def _fmt_dt(dt: datetime | None) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def _normalize_environment(value: str | None) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if text not in ENV_KEYS:
        raise HTTPException(400, "未知的环境")
    return text


def _images(row: CaseComment) -> list[dict]:
    try:
        items = json.loads(row.images_json or "[]")
    except json.JSONDecodeError:
        items = []
    out = []
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        rel = str(item.get("file") or "").lstrip("/")
        if not rel:
            continue
        out.append(
            {
                "name": item.get("name") or Path(rel).name,
                "content_type": item.get("content_type") or "",
                "url": "/files/" + rel,
            }
        )
    return out


def comment_out(row: CaseComment) -> dict:
    env = (row.environment or "").strip()
    return {
        "id": row.id,
        "case_id": row.case_id,
        "product_id": row.product_id,
        "case_version": row.case_version or "",
        "body": row.body or "",
        "environment": env,
        "environment_label": ENV_LABELS.get(env, ""),
        "created_at": _fmt_dt(row.created_at),
        "images": _images(row),
    }


def list_comments(db: Session, case_id: int) -> dict:
    case = db.get(TestCase, case_id)
    if not case:
        raise HTTPException(404, "用例不存在")
    rows = (
        db.query(CaseComment)
        .filter_by(case_id=case_id)
        .order_by(CaseComment.created_at.asc(), CaseComment.id.asc())
        .all()
    )
    return {"case_id": case_id, "items": [comment_out(row) for row in rows]}


def comment_counts(db: Session, case_ids: list[int]) -> dict[int, int]:
    if not case_ids:
        return {}
    rows = (
        db.query(CaseComment.case_id, func.count(CaseComment.id))
        .filter(CaseComment.case_id.in_(case_ids))
        .group_by(CaseComment.case_id)
        .all()
    )
    return {int(cid): int(n) for cid, n in rows}


def comment_environments(db: Session, case_ids: list[int]) -> dict[int, dict[str, int]]:
    if not case_ids:
        return {}
    rows = (
        db.query(CaseComment.case_id, CaseComment.environment, CaseComment.id)
        .filter(CaseComment.case_id.in_(case_ids))
        .filter(CaseComment.environment != "")
        .all()
    )
    out: dict[int, dict[str, int]] = {}
    for case_id, environment, comment_id in rows:
        env = (environment or "").strip()
        if not env:
            continue
        out.setdefault(int(case_id), {})[env] = int(comment_id)
    return out


def _safe_filename(name: str, content_type: str) -> str:
    raw = Path(name or "image").name
    stem = _SAFE_NAME.sub("_", Path(raw).stem).strip("._") or "image"
    ext = Path(raw).suffix.lower()
    if ext not in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}:
        ext = ALLOWED_TYPES.get(content_type, ".png")
    if ext == ".jpeg":
        ext = ".jpg"
    return f"{stem[:80]}{ext}"


async def create_comment(
    db: Session,
    case_id: int,
    body: str = "",
    case_version: str = "",
    environment: str = "",
    images: list[UploadFile] | None = None,
) -> dict:
    case = db.get(TestCase, case_id)
    if not case:
        raise HTTPException(404, "用例不存在")
    text = (body or "").strip()
    env = _normalize_environment(environment)
    files = [f for f in (images or []) if f is not None and (f.filename or f.content_type)]
    if not text and not files:
        raise HTTPException(400, "请输入测试执行记录或粘贴图片")
    if len(files) > MAX_IMAGES:
        raise HTTPException(400, f"一次最多上传 {MAX_IMAGES} 张图片")

    if env:
        exists = (
            db.query(CaseComment.id)
            .filter_by(case_id=case.id, environment=env)
            .first()
        )
        if exists:
            raise HTTPException(409, "该环境已有测试执行记录，删除后可重新评论")

    payloads: list[tuple[bytes, str, str]] = []
    for upload in files:
        content_type = (upload.content_type or "").split(";")[0].strip().lower()
        if content_type not in ALLOWED_TYPES:
            raise HTTPException(400, "只支持 JPEG / PNG / GIF / WebP / BMP 图片")
        data = await upload.read()
        if not data:
            continue
        if len(data) > MAX_IMAGE_BYTES:
            raise HTTPException(400, "单张图片不能超过 8MB")
        payloads.append((data, _safe_filename(upload.filename or "", content_type), content_type))

    if not text and not payloads:
        raise HTTPException(400, "请输入测试执行记录或粘贴图片")

    row = CaseComment(
        case_id=case.id,
        product_id=case.product_id,
        case_version=case_version or "",
        body=text,
        images_json="[]",
        environment=env,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "该环境已有测试执行记录，删除后可重新评论") from None

    stored: list[dict] = []
    folder = FILES_DIR / "comments" / str(row.id)
    folder.mkdir(parents=True, exist_ok=True)
    for data, filename, content_type in payloads:
        unique = f"{uuid.uuid4().hex[:10]}_{filename}"
        dest = folder / unique
        dest.write_bytes(data)
        rel = str(dest.relative_to(FILES_DIR)).replace("\\", "/")
        stored.append({"file": rel, "name": filename, "content_type": content_type})
    row.images_json = json.dumps(stored, ensure_ascii=False)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if folder.exists():
            shutil.rmtree(folder, ignore_errors=True)
        raise HTTPException(409, "该环境已有测试执行记录，删除后可重新评论") from None
    db.refresh(row)
    return comment_out(row)


def delete_comment(db: Session, case_id: int, comment_id: int) -> dict:
    case = db.get(TestCase, case_id)
    if not case:
        raise HTTPException(404, "用例不存在")
    row = db.get(CaseComment, comment_id)
    if not row or row.case_id != case_id:
        raise HTTPException(404, "测试执行记录不存在")
    folder = FILES_DIR / "comments" / str(row.id)
    db.delete(row)
    db.commit()
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)
    return {"ok": True, "id": comment_id, "case_id": case_id}
