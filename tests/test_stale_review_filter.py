"""Filter case-docs by visible stale (推演失真) reviews."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.case_reviews import create_review
from app.db import SessionLocal, init_db
from app.main import get_case_docs, patch_case_version
from app.models import CaseDocMeta, TestCase as CaseRow
from app.seed import upsert_case_version
from tests.test_case_reviews import SLUG, _Patch, _cleanup_product, _product_fixture


def _purge_doc_meta(db, product_id: int | None = None):
    q = db.query(CaseDocMeta)
    if product_id is not None:
        q = q.filter_by(product_id=product_id)
    else:
        from app.models import Product

        ids = [r[0] for r in db.query(Product.id).filter_by(slug=SLUG).all()]
        if not ids:
            return
        q = q.filter(CaseDocMeta.product_id.in_(ids))
    q.delete(synchronize_session=False)
    db.commit()


def _add_case(db, product, key: str):
    rec = {
        "key": key,
        "title": key,
        "module": "qa",
        "priority": "P3",
        "client": "web",
        "description": "desc",
        "preconditions": "pre",
        "steps": "1. 另一步",
        "expected": "ok",
    }
    cv = upsert_case_version(db, product, rec, "v1.0.1", "")
    db.commit()
    return db.get(CaseRow, cv.case_id)


def _keys(body):
    return [item["key"] for item in body["items"]]


def test_case_docs_stale_filter_matches_visible_dock_warning():
    init_db()
    db = SessionLocal()
    product = None
    try:
        _purge_doc_meta(db)
        product, case_a, _v1, v2 = _product_fixture(db)
        case_b = _add_case(db, product, "TC-QAR-002")
        case_c = _add_case(db, product, "TC-QAR-003")
        case_d = _add_case(db, product, "TC-QAR-004")
        case_e = _add_case(db, product, "TC-QAR-005")

        create_review(db, {"case_id": case_a.id, "endpoint": "backend", "result": "fail"})
        create_review(db, {"case_id": case_b.id, "endpoint": "web", "result": "fail"})
        create_review(db, {"case_id": case_c.id, "endpoint": "backend", "result": "pass"})
        create_review(db, {"case_id": case_d.id, "endpoint": "web", "result": "pass"})
        create_review(db, {"case_id": case_e.id, "endpoint": "android", "result": "fail"})

        patch_case_version(case_a.id, v2.version, _Patch(steps="1. 完全不同的步骤"), db)
        patch_case_version(case_c.id, "v1.0.1", _Patch(steps="1. 完全不同的步骤"), db)
        create_review(db, {"case_id": case_c.id, "endpoint": "backend", "result": "pass"})
        patch_case_version(case_d.id, "v1.0.1", _Patch(steps="1. 完全不同的步骤"), db)
        patch_case_version(case_e.id, "v1.0.1", _Patch(steps="1。\n另一步"), db)

        all_docs = get_case_docs(product_id=product.id, version="v1.0.1", page=1, page_size=20, db=db)
        assert _keys(all_docs) == [
            "TC-QAR-001",
            "TC-QAR-002",
            "TC-QAR-003",
            "TC-QAR-004",
            "TC-QAR-005",
        ]
        assert all_docs["total"] == 5

        stale = get_case_docs(
            product_id=product.id,
            version="v1.0.1",
            stale=True,
            page=1,
            page_size=20,
            db=db,
        )
        # A dock is stale; C was re-reviewed so latest is fresh; E punctuation-only is not stale.
        assert _keys(stale) == ["TC-QAR-001", "TC-QAR-004"]
        assert stale["total"] == 2

        both = get_case_docs(
            product_id=product.id,
            version="v1.0.1",
            review_endpoints=["backend"],
            review_results=["fail"],
            stale=True,
            page=1,
            page_size=20,
            db=db,
        )
        assert _keys(both) == ["TC-QAR-001"]
        assert both["total"] == 1
    finally:
        try:
            db.rollback()
        except Exception:
            pass
        try:
            if product is not None:
                _purge_doc_meta(db, product.id)
            else:
                _purge_doc_meta(db)
            _cleanup_product(db, product)
        finally:
            db.close()
