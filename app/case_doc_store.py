"""Persist case-document extras (用例信息 / 待确认 / 不测) so pagination does not re-parse HTML."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import FILES_DIR
from app.models import CaseDocMeta, TestCase, TestCaseVersion
from app.parsers import count_untested_cases, extract_case_document_info, parse_pending_notes

_LOCKS: dict[tuple[int, str], threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(product_id: int, version: str) -> threading.Lock:
    key = (int(product_id), str(version or ""))
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _LOCKS[key] = lock
        return lock


def _resolve(rel: str | None) -> Path | None:
    if not rel:
        return None
    path = (FILES_DIR / rel).resolve()
    if not str(path).startswith(str(FILES_DIR.resolve())):
        return None
    if not path.is_file():
        return None
    return path


def _stat(path: Path | None) -> tuple[int, int]:
    if path is None:
        return 0, 0
    st = path.stat()
    return int(st.st_size), int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1_000_000_000)))


def _is_stale(row: CaseDocMeta, size: int, mtime_ns: int, source_file: str) -> bool:
    if not row.parsed:
        return True
    if (row.source_file or "") != (source_file or ""):
        return True
    return int(row.source_size or 0) != int(size or 0) or int(row.source_mtime_ns or 0) != int(mtime_ns or 0)


def _payload(row: CaseDocMeta | None) -> dict:
    if row is None:
        return {
            "pending": [],
            "untested": 0,
            "case_info": {"available": False, "title": "", "fields": [], "fragment_page": ""},
        }
    try:
        pending = json.loads(row.pending_json or "[]")
    except json.JSONDecodeError:
        pending = []
    if not isinstance(pending, list):
        pending = []
    try:
        fields = json.loads(row.info_fields_json or "[]")
    except json.JSONDecodeError:
        fields = []
    if not isinstance(fields, list):
        fields = []
    return {
        "pending": [str(x) for x in pending],
        "untested": int(row.untested or 0),
        "case_info": {
            "available": bool(row.info_available),
            "title": row.info_title or "",
            "fields": fields,
            "fragment_page": row.info_fragment_page or "",
        },
    }


def _empty_payload() -> dict:
    return _payload(None)


def persist_case_doc_meta(
    db: Session,
    product_id: int,
    version: str,
    source_file: str,
    html: str | None = None,
    force: bool = False,
) -> dict:
    """Parse the case HTML once and store pending / case_info / untested."""
    version = version or ""
    source_file = source_file or ""
    if not product_id or not version:
        return _empty_payload()

    with _lock_for(product_id, version):
        row = (
            db.query(CaseDocMeta)
            .filter_by(product_id=product_id, version=version)
            .one_or_none()
        )
        path = _resolve(source_file)
        size, mtime_ns = _stat(path)
        if row and not force and not _is_stale(row, size, mtime_ns, source_file):
            return _payload(row)

        if row is None:
            row = CaseDocMeta(product_id=product_id, version=version)
            db.add(row)

        ext = Path(source_file).suffix.lower() if source_file else ""
        if not path or ext not in {".html", ".htm"}:
            row.source_file = source_file
            row.source_size = size
            row.source_mtime_ns = mtime_ns
            row.pending_json = "[]"
            row.untested = 0
            row.info_available = 0
            row.info_title = ""
            row.info_fields_json = "[]"
            row.info_fragment_page = ""
            row.parsed = 1
            db.commit()
            return _payload(row)

        if html is None:
            html = path.read_text(encoding="utf-8", errors="replace")
        pending = parse_pending_notes(html)
        info = extract_case_document_info(html)
        untested = count_untested_cases(html)
        row.source_file = source_file
        row.source_size = size
        row.source_mtime_ns = mtime_ns
        row.pending_json = json.dumps(pending, ensure_ascii=False)
        row.untested = int(untested or 0)
        row.info_available = 1 if info.get("available") else 0
        row.info_title = info.get("title") or ""
        row.info_fields_json = json.dumps(info.get("fields") or [], ensure_ascii=False)
        row.info_fragment_page = info.get("fragment_page") or ""
        row.parsed = 1
        db.commit()
        return _payload(row)


def get_case_doc_meta(db: Session, product_id: int, version: str, source_file: str) -> dict:
    return persist_case_doc_meta(db, product_id, version, source_file)


def backfill_case_doc_metas(db: Session) -> dict:
    """Ensure every product + case version with a source file is persisted."""
    rows = (
        db.query(TestCase.product_id, TestCaseVersion.version, TestCaseVersion.source_file)
        .join(TestCase, TestCaseVersion.case_id == TestCase.id)
        .filter(TestCaseVersion.source_file != "")
        .distinct()
        .all()
    )
    filled = 0
    cached = 0
    for product_id, version, source_file in rows:
        before = (
            db.query(CaseDocMeta)
            .filter_by(product_id=product_id, version=version)
            .one_or_none()
        )
        path = _resolve(source_file)
        size, mtime_ns = _stat(path)
        if before and before.parsed and not _is_stale(before, size, mtime_ns, source_file or ""):
            cached += 1
            continue
        persist_case_doc_meta(db, product_id, version, source_file or "")
        filled += 1
    return {"versions": len(rows), "filled": filled, "cached": cached}


def backfill_case_doc_metas_async() -> None:
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        backfill_case_doc_metas(db)
    finally:
        db.close()
