"""Persisted review-detail rows are served from the database, not re-parsed."""

from __future__ import annotations

import time
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import SessionLocal, init_db
from app.models import ReportCaseLink, ReportVersion, TestCase
from app.review_store import persist_one_case_detail, persist_report_version_details
from app.reviews import review_detail


def test_review_detail_reads_stored_fields_for_gma_backend():
    init_db()
    db = SessionLocal()
    try:
        case = db.query(TestCase).filter_by(key="TC-GMA-081").one()
        # report version 18 is 后端静态推演 v1.0.1 based on v1.0.6
        rv = db.get(ReportVersion, 18)
        assert rv is not None
        persist_report_version_details(db, rv, rv.report.product if rv.report else None)
        db.refresh(rv)
        assert rv.header_parsed == 1
        assert rv.details_parsed == 1
        assert rv.repo
        link = (
            db.query(ReportCaseLink)
            .filter_by(report_version_id=rv.id, case_id=case.id)
            .one()
        )
        assert link.detail_parsed == 1
        assert "推演用例编号" in (link.fields_json or "")
        assert "后端链路" in (link.section_html or "")
        assert "问题级别" not in (link.section_html or "")

        t0 = time.perf_counter()
        data = review_detail(db, case.product_id, "backend", case.id, "v1.0.6")
        elapsed = time.perf_counter() - t0
        assert data["found"] is True
        labels = [f["label"] for f in data["fields"]]
        assert labels == ["推演用例编号", "用例标题", "后端链路", "推演结果", "不通过原因", "备注"]
        assert data["heading"].startswith("#81")
        assert data["repo"]
        assert "问题级别" not in data["html"]
        assert elapsed < 0.5
    finally:
        db.close()
