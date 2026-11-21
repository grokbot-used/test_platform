"""Case-document extras are stored and served without re-parsing HTML on each page."""

from __future__ import annotations

import time
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.case_doc_store import get_case_doc_meta, persist_case_doc_meta
from app.db import SessionLocal, init_db
from app.main import get_case_docs
from app.models import CaseDocMeta


def test_case_doc_meta_persists_gma_v106_and_speeds_up_pages():
    init_db()
    db = SessionLocal()
    try:
        source = "global-model/cases/黑盒测试用例_全球型号接入_v1.0.6.html"
        first = persist_case_doc_meta(db, 2, "v1.0.6", source, force=True)
        assert first["untested"] == 11
        assert first["case_info"]["available"] is True
        assert first["case_info"]["fields"]
        assert first["case_info"]["fragment_page"]
        row = db.query(CaseDocMeta).filter_by(product_id=2, version="v1.0.6").one()
        assert row.parsed == 1
        assert row.untested == 11

        t0 = time.perf_counter()
        again = get_case_doc_meta(db, 2, "v1.0.6", source)
        elapsed = time.perf_counter() - t0
        assert again["untested"] == 11
        assert elapsed < 0.05

        get_case_docs(product_id=2, version="v1.0.6", q=None, priority=None, page=1, page_size=20, db=db)
        t0 = time.perf_counter()
        body = get_case_docs(product_id=2, version="v1.0.6", q=None, priority=None, page=2, page_size=20, db=db)
        elapsed = time.perf_counter() - t0
        assert body["page"] == 2
        assert len(body["items"]) == 20
        assert body["priority_stats"]["untested"] == 11
        assert body["case_info"]["available"] is True
        assert elapsed < 0.25
    finally:
        db.close()
