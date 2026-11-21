"""Persist review header and per-case table fields so detail APIs read the database."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from sqlalchemy.orm import Session, joinedload

from app.config import FILES_DIR
from app.models import Product, Report, ReportCaseLink, ReportVersion, TestCase
from app.parsers import (
    REVIEW_CARD_CSS,
    build_fragment_page,
    build_review_detail_view,
    extract_report_case_detail,
    extract_report_header_meta,
    extract_style_text_from_raw,
    index_report_case_details,
    key_lookup_aliases,
)

_LOCKS: dict[int, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()

_PREFIX_BY_SLUG = {
    "price-openapi": "TC-OPA",
    "global-model": "TC-GMA",
    "r58l": "TC-R58",
    "exdata-vin": "TC-EXD",
    "gt06-a5": "TC-A5",
}


def _lock_for(rv_id: int) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(rv_id, threading.Lock())


def _source_stat(rel: str | None) -> tuple[int, int]:
    if not rel:
        return (0, 0)
    path = (FILES_DIR / rel).resolve()
    if not str(path).startswith(str(FILES_DIR.resolve())) or not path.is_file():
        return (0, 0)
    st = path.stat()
    return (int(st.st_size), int(st.st_mtime_ns))


def source_is_stale(rv: ReportVersion) -> bool:
    size, mtime = _source_stat(rv.source_file)
    if not size:
        return False
    return int(rv.source_size or 0) != size or int(rv.source_mtime_ns or 0) != mtime


def _apply_header(rv: ReportVersion, header: dict, css: str, size: int, mtime: int) -> None:
    rv.repo = header.get("repo") or ""
    rv.branch = header.get("branch") or ""
    rv.participants = header.get("participants") or ""
    rv.style_css = css or ""
    rv.header_parsed = 1
    rv.source_size = size
    rv.source_mtime_ns = mtime


def apply_link_detail(link: ReportCaseLink, detail: dict) -> None:
    link.heading = detail.get("heading") or ""
    link.anchor = detail.get("anchor") or ""
    link.section_html = detail.get("html") or ""
    link.fields_json = json.dumps(detail.get("fields") or [], ensure_ascii=False)
    link.detail_text = detail.get("text") or ""
    link.detail_parsed = 1
    if detail.get("result") and not link.result:
        link.result = detail["result"]


def empty_detail() -> dict:
    return {
        "found": False,
        "anchor": "",
        "html": "",
        "fragment_page": "",
        "text": "",
        "fields": [],
        "result": "",
        "heading": "",
    }


def payload_from_link(link: ReportCaseLink, css: str, case_key: str) -> dict:
    if not link or not link.detail_parsed:
        return empty_detail()
    try:
        fields = json.loads(link.fields_json or "[]")
    except json.JSONDecodeError:
        fields = []
    result = link.result or ""
    section_html, fields, heading = build_review_detail_view(
        link.section_html or "",
        fields,
        heading=link.heading or "",
        text=link.detail_text or "",
        result=result,
        fallback_title=case_key or "",
    )
    css_parts = [part for part in ((css or "").strip(), REVIEW_CARD_CSS.strip()) if part]
    return {
        "found": bool(section_html),
        "anchor": link.anchor or "",
        "html": section_html,
        "fragment_page": build_fragment_page(section_html, "\n".join(css_parts), title=heading or case_key),
        "text": link.detail_text or "",
        "fields": fields,
        "result": result,
        "heading": heading,
    }


def _key_prefix(product: Product | None) -> str | None:
    if product is None:
        return None
    return _PREFIX_BY_SLUG.get(product.slug, "TC-GEN")


def persist_report_version_details(
    db: Session,
    rv: ReportVersion,
    product: Product | None = None,
    html: str | None = None,
    force: bool = False,
) -> dict:
    """Parse one report file once and store header + every case's table fields."""
    if rv is None:
        return {"parsed": 0}
    from app.reviews import _read_source

    with _lock_for(rv.id):
        db.refresh(rv)
        if not force and rv.details_parsed and not source_is_stale(rv):
            return {"parsed": 0, "cached": True}
        src = rv.source_file or ""
        if html is None:
            html = _read_source(src)
        size, mtime = _source_stat(src)
        ext = Path(src).suffix.lower()
        links = (
            db.query(ReportCaseLink)
            .options(joinedload(ReportCaseLink.case))
            .filter_by(report_version_id=rv.id)
            .all()
        )
        if not html or ext not in {".html", ".htm"}:
            _apply_header(rv, {"repo": "", "branch": "", "participants": ""}, "", size, mtime)
            for link in links:
                apply_link_detail(link, empty_detail())
            rv.details_parsed = 1
            db.commit()
            return {"parsed": 0, "skipped": True}

        if product is None and rv.report is not None:
            product = rv.report.product
        indexed = index_report_case_details(html, _key_prefix(product))
        _apply_header(rv, indexed["header"], indexed["css"], size, mtime)

        by_key: dict[str, ReportCaseLink] = {}
        for link in links:
            key = link.case.key if link.case else ""
            if not key:
                continue
            for alias in [key, *key_lookup_aliases(key)]:
                if alias:
                    by_key.setdefault(alias, link)
                    by_key.setdefault(alias.upper(), link)
                    by_key.setdefault(alias.lower(), link)

        filled = 0
        used: set[int] = set()
        for item in indexed["cases"]:
            key = item.get("key") or ""
            link = by_key.get(key) or (by_key.get(key.upper()) if key else None)
            if link is None and item.get("anchor"):
                link = by_key.get(item["anchor"]) or by_key.get(str(item["anchor"]).lower())
            if link is None or link.id in used:
                continue
            used.add(link.id)
            apply_link_detail(link, item)
            filled += 1
        for link in links:
            if not link.detail_parsed:
                apply_link_detail(link, empty_detail())
        rv.details_parsed = 1
        db.commit()
        return {"parsed": filled, "links": len(links)}


def persist_one_case_detail(
    db: Session,
    rv: ReportVersion,
    case: TestCase,
    html: str | None = None,
) -> None:
    """Ensure this version's header and this case's table fields are in the database."""
    from app.reviews import _link_for, _read_source

    with _lock_for(rv.id):
        db.refresh(rv)
        stale = source_is_stale(rv)
        link = _link_for(db, rv, case.id)
        if stale:
            rv.header_parsed = 0
            rv.details_parsed = 0
            if link is not None:
                link.detail_parsed = 0
        if rv.header_parsed and (link is None or link.detail_parsed) and not stale:
            return

        src = rv.source_file or ""
        ext = Path(src).suffix.lower()
        if html is None:
            html = _read_source(src) if ext in {".html", ".htm"} else ""
        size, mtime = _source_stat(src)
        if not rv.header_parsed:
            if html:
                header = extract_report_header_meta(html)
                css = extract_style_text_from_raw(html)
            else:
                header = {"repo": "", "branch": "", "participants": ""}
                css = ""
            _apply_header(rv, header, css, size, mtime)
        if link is not None and not link.detail_parsed:
            detail = extract_report_case_detail(html, case.key) if html else empty_detail()
            apply_link_detail(link, detail)
        db.commit()


def backfill_review_details(db: Session, force: bool = False) -> dict:
    rows = (
        db.query(ReportVersion)
        .options(joinedload(ReportVersion.report).joinedload(Report.product))
        .all()
    )
    stats = {"versions": 0, "filled": 0, "cached": 0}
    for rv in rows:
        if not force and rv.details_parsed and not source_is_stale(rv):
            stats["cached"] += 1
            continue
        result = persist_report_version_details(
            db, rv, rv.report.product if rv.report else None, force=force
        )
        stats["versions"] += 1
        stats["filled"] += int(result.get("parsed") or 0)
    return stats


def backfill_review_details_async() -> None:
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        backfill_review_details(db)
    finally:
        db.close()
