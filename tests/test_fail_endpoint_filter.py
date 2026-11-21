"""Filter case-docs by review endpoint and result (OR within each, AND across)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.case_reviews import create_review
from app.db import SessionLocal, init_db
from app.main import get_case_docs
from app.models import CaseDocMeta, TestCase as CaseRow
from app.seed import upsert_case_version
from tests.test_case_reviews import SLUG, _cleanup_product, _product_fixture


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
        "steps": "1. 一步",
        "expected": "ok",
    }
    cv = upsert_case_version(db, product, rec, "v1.0.0", "")
    db.commit()
    return db.get(CaseRow, cv.case_id)


def _keys(body):
    return [item["key"] for item in body["items"]]


def test_case_docs_review_filters_endpoint_and_result():
    init_db()
    db = SessionLocal()
    product = None
    try:
        _purge_doc_meta(db)
        product, case_a, _v1, _v2 = _product_fixture(db)
        case_b = _add_case(db, product, "TC-QAR-002")
        case_c = _add_case(db, product, "TC-QAR-003")
        rec = {
            "key": case_a.key,
            "title": "临时用例",
            "module": "qa",
            "priority": "P3",
            "client": "web",
            "description": "desc",
            "preconditions": "pre",
            "steps": "1. 一步",
            "expected": "ok",
        }
        upsert_case_version(db, product, rec, "v1.0.0", "")
        db.commit()

        create_review(db, {"case_id": case_a.id, "endpoint": "backend", "result": "pass"})
        create_review(db, {"case_id": case_a.id, "endpoint": "backend", "result": "fail"})
        create_review(db, {"case_id": case_b.id, "endpoint": "web", "result": "fail"})
        create_review(db, {"case_id": case_c.id, "endpoint": "backend", "result": "fail"})
        create_review(db, {"case_id": case_c.id, "endpoint": "backend", "result": "pass"})
        create_review(db, {"case_id": case_c.id, "endpoint": "android", "result": "skip"})

        none = get_case_docs(product_id=product.id, version="v1.0.0", page=1, page_size=20, db=db)
        assert set(_keys(none)) == {"TC-QAR-001", "TC-QAR-002", "TC-QAR-003"}
        assert none["total"] == 3

        backend_fail = get_case_docs(
            product_id=product.id,
            version="v1.0.0",
            review_endpoints=["backend"],
            review_results=["fail"],
            page=1,
            page_size=20,
            db=db,
        )
        assert _keys(backend_fail) == ["TC-QAR-001"]
        assert backend_fail["total"] == 1

        both_fail = get_case_docs(
            product_id=product.id,
            version="v1.0.0",
            review_endpoints=["backend", "web"],
            review_results=["fail"],
            page=1,
            page_size=20,
            db=db,
        )
        assert _keys(both_fail) == ["TC-QAR-001", "TC-QAR-002"]
        assert both_fail["total"] == 2

        csv_style = get_case_docs(
            product_id=product.id,
            version="v1.0.0",
            review_endpoints=["backend,web"],
            review_results=["fail"],
            page=1,
            page_size=20,
            db=db,
        )
        assert _keys(csv_style) == ["TC-QAR-001", "TC-QAR-002"]

        any_fail = get_case_docs(
            product_id=product.id,
            version="v1.0.0",
            review_results=["fail"],
            page=1,
            page_size=20,
            db=db,
        )
        assert _keys(any_fail) == ["TC-QAR-001", "TC-QAR-002"]

        backend_any = get_case_docs(
            product_id=product.id,
            version="v1.0.0",
            review_endpoints=["backend"],
            page=1,
            page_size=20,
            db=db,
        )
        # A latest backend fail, C latest backend pass; B has no backend review.
        assert _keys(backend_any) == ["TC-QAR-001", "TC-QAR-003"]

        pass_or_skip = get_case_docs(
            product_id=product.id,
            version="v1.0.0",
            review_results=["pass", "skip"],
            page=1,
            page_size=20,
            db=db,
        )
        # C latest backend pass and android skip; A latest is fail; B is fail.
        assert _keys(pass_or_skip) == ["TC-QAR-003"]

        with pytest.raises(HTTPException) as bad_ep:
            get_case_docs(
                product_id=product.id,
                version="v1.0.0",
                review_endpoints=["desktop"],
                page=1,
                page_size=20,
                db=db,
            )
        assert bad_ep.value.status_code == 400

        with pytest.raises(HTTPException) as bad_res:
            get_case_docs(
                product_id=product.id,
                version="v1.0.0",
                review_results=["blocked"],
                page=1,
                page_size=20,
                db=db,
            )
        assert bad_res.value.status_code == 400
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
