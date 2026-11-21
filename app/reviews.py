"""Map review reports onto the four endpoints and resolve per-case details."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from sqlalchemy.orm import Session, joinedload

from app.config import FILES_DIR
from app.models import Product, Report, ReportCaseLink, ReportVersion, TestCase, TestCaseVersion
from app.parsers import (
    detect_app_platforms,
    extract_report_case_detail,
    extract_report_header_meta,
    infer_based_on_case_version,
    is_app_review,
)

import re

RESULT_LABELS = {
    "pass": "通过",
    "fail": "失败",
    "skip": "跳过",
    "blocked": "阻塞",
    "untested": "未测",
    "": "未记录",
}


def version_key(ver: str) -> tuple[int, ...]:
    parts = [int(x) for x in re.findall(r"\d+", ver or "")]
    return tuple(parts + [0] * (4 - len(parts)))


def snap_to_available(ver: str | None, available: list[str] | set[str] | None) -> str | None:
    """Keep a parsed version only if it exists (or is a prefix of one that exists)."""
    if not ver:
        return None
    avail = [v for v in (available or []) if v]
    if not avail:
        return ver
    if ver in avail:
        return ver
    prefixed = [v for v in avail if v.startswith(ver + ".")]
    if prefixed:
        return sorted(prefixed, key=version_key)[-1]
    return None


ENDPOINTS = [
    {"id": "backend", "label": "后端"},
    {"id": "web", "label": "web"},
    {"id": "android", "label": "安卓"},
    {"id": "ios", "label": "ios"},
]

ENDPOINT_LABELS = {e["id"]: e["label"] for e in ENDPOINTS}


def product_case_versions(db: Session, product_id: int) -> list[str]:
    rows = (
        db.query(TestCaseVersion.version)
        .join(TestCase)
        .filter(TestCase.product_id == product_id)
        .distinct()
        .all()
    )
    return sorted({r[0] for r in rows if r[0]}, key=version_key)


def _read_source(rel: str | None, limit: int | None = None) -> str:
    if not rel:
        return ""
    path = (FILES_DIR / rel).resolve()
    if not str(path).startswith(str(FILES_DIR.resolve())) or not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    if limit is not None:
        return text[:limit]
    return text


def resolve_based_on_case_version(
    db: Session,
    rv: ReportVersion,
    product: Product | None = None,
) -> str | None:
    text = _read_source(rv.source_file)
    if not text:
        text = " ".join(filter(None, [rv.summary or "", rv.conclusion or ""]))
    filename = Path(rv.source_file or "").name
    if product is None and rv.report:
        product = rv.report.product
    if product is None:
        report = rv.report or db.get(Report, rv.report_id)
        product = report.product if report else None
    available = product_case_versions(db, product.id) if product is not None else []

    ver = snap_to_available(infer_based_on_case_version(text, filename), available)
    if ver:
        return ver

    versions: list[str] = []
    links = rv.links
    if links is None:
        links = db.query(ReportCaseLink).filter_by(report_version_id=rv.id).all()
    for link in links:
        cv = link.case_version
        if cv is None and link.case_version_id:
            cv = db.get(TestCaseVersion, link.case_version_id)
        if cv and cv.version:
            versions.append(cv.version)
    if versions:
        picked = Counter(versions).most_common(1)[0][0]
        return snap_to_available(picked, available) or picked

    if len(available) == 1:
        return available[0]
    if rv.version in available:
        return rv.version
    return None


def backfill_based_on_case_versions(db: Session, force: bool = False) -> dict:
    rows = (
        db.query(ReportVersion)
        .options(
            joinedload(ReportVersion.report).joinedload(Report.product),
            joinedload(ReportVersion.links).joinedload(ReportCaseLink.case_version),
        )
        .all()
    )
    filled = 0
    links_fixed = 0
    for rv in rows:
        if force or not rv.based_on_case_version:
            ver = resolve_based_on_case_version(db, rv, rv.report.product if rv.report else None)
            if ver:
                rv.based_on_case_version = ver
                filled += 1
        target = rv.based_on_case_version
        if not target:
            continue
        for link in rv.links:
            if link.case_version_id:
                continue
            cv = (
                db.query(TestCaseVersion)
                .filter_by(case_id=link.case_id, version=target)
                .one_or_none()
            )
            if cv:
                link.case_version_id = cv.id
                links_fixed += 1
    db.commit()
    return {"filled": filled, "links_fixed": links_fixed, "total": len(rows)}


def classify_report_endpoints(
    title: str,
    typ: str,
    source_file: str = "",
    source_text: str | None = None,
) -> list[str]:
    if typ == "backend_review":
        return ["backend"]
    if typ in {"blackbox", "whitebox"}:
        return []
    if typ == "frontend_review":
        if is_app_review(title, source_file, typ):
            text = source_text if source_text is not None else _read_source(source_file, limit=24000)
            return detect_app_platforms(text, title=title, filename=source_file)
        return ["web"]
    return []


def _entry_payload(endpoint: str, rv: ReportVersion | None) -> dict:
    label = ENDPOINT_LABELS.get(endpoint, endpoint)
    if rv is None or rv.report is None:
        return {
            "endpoint": endpoint,
            "label": label,
            "available": False,
            "report_id": None,
            "report_title": None,
            "report_version": None,
            "report_version_id": None,
            "based_on_case_version": None,
        }
    return {
        "endpoint": endpoint,
        "label": label,
        "available": True,
        "report_id": rv.report.id,
        "report_title": rv.report.title,
        "report_version": rv.version,
        "report_version_id": rv.id,
        "based_on_case_version": rv.based_on_case_version,
    }


def review_entries(db: Session, product_id: int, case_version: str | None = None) -> dict:
    from app.case_reviews import review_entries as _impl

    return _impl(db, product_id, case_version)


def _link_for(db: Session, rv: ReportVersion, case_id: int) -> ReportCaseLink | None:
    return (
        db.query(ReportCaseLink)
        .filter_by(report_version_id=rv.id, case_id=case_id)
        .one_or_none()
    )


def review_detail(
    db: Session,
    product_id: int,
    endpoint: str,
    case_id: int,
    case_version: str | None = None,
    review_id: int | None = None,
    review_version: str | None = None,
) -> dict:
    from app.case_reviews import review_detail as _impl

    return _impl(
        db,
        product_id,
        endpoint,
        case_id,
        case_version,
        review_id=review_id,
        review_version=review_version,
    )


def case_endpoint_results(
    db: Session,
    product_id: int,
    case_version: str | None,
    case_ids: list[int],
) -> dict[int, list[dict]]:
    """Per-case four-end entry payloads from the latest case_reviews row."""
    from app.case_reviews import case_endpoint_results as _impl

    return _impl(db, product_id, case_version, case_ids)

