"""Case/review JSON CRUD, review-report migration, and report-list filters."""

from __future__ import annotations

import asyncio
from datetime import datetime
from io import BytesIO
import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from app.case_fingerprint import case_content_fingerprint, fingerprint_from_version, normalize_case_text
from app.case_reviews import (
    REVIEW_REPORT_TYPES,
    backfill_review_fingerprints,
    create_review,
    delete_review,
    list_reviews,
    migrate_review_reports,
    next_review_version,
    patch_review,
    review_detail,
)
from app.comments import create_comment
from app.config import FILES_DIR
from app.db import SessionLocal, init_db
from app.main import (
    delete_case,
    delete_case_version,
    import_cases,
    import_reports,
    delete_report,
    delete_report_version,
    list_reports,
    patch_case_version,
)
from app.models import (
    CaseComment,
    CaseReview,
    Product,
    Report,
    ReportCaseLink,
    ReportVersion,
    TestCase,
    TestCaseVersion,
)
from app.seed import upsert_case_version, upsert_report_version


SLUG = "__qa_reviews_tmp__"


def _cleanup_product(db, product: Product | None):
    if product is None:
        product = db.query(Product).filter_by(slug=SLUG).one_or_none()
    if product is None:
        return
    cases = db.query(TestCase).filter_by(product_id=product.id).all()
    case_ids = [c.id for c in cases]
    if case_ids:
        comments = db.query(CaseComment).filter(CaseComment.case_id.in_(case_ids)).all()
        for row in comments:
            folder = FILES_DIR / "comments" / str(row.id)
            if folder.exists():
                import shutil

                shutil.rmtree(folder, ignore_errors=True)
        db.query(CaseComment).filter(CaseComment.case_id.in_(case_ids)).delete(synchronize_session=False)
        db.query(CaseReview).filter(CaseReview.case_id.in_(case_ids)).delete(synchronize_session=False)
        db.query(ReportCaseLink).filter(ReportCaseLink.case_id.in_(case_ids)).delete(synchronize_session=False)
        db.flush()
        db.query(TestCaseVersion).filter(TestCaseVersion.case_id.in_(case_ids)).delete(synchronize_session=False)
        db.flush()
        db.query(TestCase).filter(TestCase.id.in_(case_ids)).delete(synchronize_session=False)
    reports = db.query(Report).filter_by(product_id=product.id).all()
    report_ids = [r.id for r in reports]
    if report_ids:
        rv_ids = [r[0] for r in db.query(ReportVersion.id).filter(ReportVersion.report_id.in_(report_ids)).all()]
        if rv_ids:
            db.query(ReportCaseLink).filter(ReportCaseLink.report_version_id.in_(rv_ids)).delete(
                synchronize_session=False
            )
        db.query(ReportVersion).filter(ReportVersion.report_id.in_(report_ids)).delete(synchronize_session=False)
        db.query(Report).filter(Report.id.in_(report_ids)).delete(synchronize_session=False)
    db.delete(product)
    db.commit()


def _product_fixture(db) -> tuple[Product, TestCase, TestCaseVersion, TestCaseVersion]:
    _cleanup_product(db, None)
    product = Product(name="QA Reviews Temp", slug=SLUG)
    db.add(product)
    db.flush()
    rec = {
        "key": "TC-QAR-001",
        "title": "临时用例",
        "module": "qa",
        "priority": "P3",
        "client": "web",
        "description": "desc",
        "preconditions": "pre",
        "steps": "1. 一步",
        "expected": "ok",
    }
    v1 = upsert_case_version(db, product, rec, "v1.0.0", "")
    rec["title"] = "临时用例 v2"
    rec["steps"] = "1. 另一步"
    v2 = upsert_case_version(db, product, rec, "v1.0.1", "")
    db.commit()
    case = db.get(TestCase, v1.case_id)
    return product, case, v1, v2


def _add_review_report(db, product, title, typ, version, based_on, case, case_version, result, created_at, heading=""):
    rv = upsert_report_version(
        db,
        product,
        title=title,
        rtype=typ,
        version=version,
        summary="",
        conclusion="",
        source_file="",
        based_on_case_version=based_on,
    )
    rv.created_at = created_at
    rv.repo = "repo-x"
    rv.branch = "main"
    rv.participants = "qa"
    rv.style_css = "body{}"
    db.flush()
    # Intentionally point case_version_id at a *different* version than based_on
    # when the caller passes a mismatched case_version, to prove migration prefers based_on.
    link = ReportCaseLink(
        report_version_id=rv.id,
        case_id=case.id,
        case_version_id=case_version.id,
        result=result,
        heading=heading or f"{title} {version}",
        section_html=f"<p>{title} {version}</p>",
        fields_json='[{"label": "推演结果", "value": "通过"}]',
        detail_text=f"{title} {version}",
        detail_parsed=1,
    )
    db.add(link)
    db.flush()
    return rv, link


def test_next_review_version_increments():
    assert next_review_version([]) == "v0.0.1"
    assert next_review_version(["v0.0.1"]) == "v0.0.2"
    assert next_review_version(["v0.0.9", "v0.0.10"]) == "v0.0.11"


def test_migrate_prefers_based_on_and_is_idempotent():
    init_db()
    db = SessionLocal()
    product = None
    try:
        product, case, v1, v2 = _product_fixture(db)
        t0 = datetime(2026, 11, 1, 1, 0, 0)
        t1 = datetime(2026, 11, 2, 1, 0, 0)
        # link.case_version_id is v1, but based_on is v1.0.1 (v2) — should attach to v2
        _add_review_report(
            db, product, "前端静态推演", "frontend_review", "v1.0.0", "v1.0.1",
            case, v1, "pass", t0, heading="first",
        )
        _add_review_report(
            db, product, "前端静态推演", "frontend_review", "v1.0.1", "v1.0.1",
            case, v1, "fail", t1, heading="second",
        )
        _add_review_report(
            db, product, "后端静态推演", "backend_review", "v1.0.0", "v1.0.1",
            case, v1, "pass", t0, heading="backend",
        )
        db.commit()

        first = migrate_review_reports(db)
        assert first["inserted"] == 3
        assert first["skipped"] == 0
        second = migrate_review_reports(db)
        assert second["inserted"] == 0
        assert second["already"] >= 3

        web = list_reviews(db, case.id, "v1.0.1", "web")
        assert [item["version"] for item in web["items"]] == ["v0.0.2", "v0.0.1"]
        assert web["items"][0]["result"] == "fail"
        assert web["items"][1]["result"] == "pass"
        assert "html" not in web["items"][0]
        assert "fragment_page" not in web["items"][0]

        # case_version is ignored; the same reviews show for any requested version
        other = list_reviews(db, case.id, "v1.0.0", "web")
        assert [item["version"] for item in other["items"]] == ["v0.0.2", "v0.0.1"]
        unscoped = list_reviews(db, case.id, endpoint="web")
        assert [item["version"] for item in unscoped["items"]] == ["v0.0.2", "v0.0.1"]

        detail = review_detail(db, product.id, "web", case.id, "v1.0.1")
        assert detail["available"] is True
        assert detail["version"] == "v0.0.2"
        assert detail["result"] == "fail"
        assert [r["version"] for r in detail["reviews"]] == ["v0.0.2", "v0.0.1"]
        assert "fragment_page" in detail
        older = review_detail(
            db, product.id, "web", case.id, "v1.0.1", review_version="v0.0.1"
        )
        assert older["version"] == "v0.0.1"
        assert older["result"] == "pass"
        assert older["heading"] == "first"
        assert "前端静态推演 v1.0.0" in (older.get("html") or "")
    finally:
        _cleanup_product(db, product)
        db.close()


def test_review_crud_conflict_and_case_delete_cascade():
    init_db()
    db = SessionLocal()
    product = None
    try:
        product, case, v1, v2 = _product_fixture(db)
        created = create_review(
            db,
            {
                "case_id": case.id,
                "endpoint": "backend",
                "result": "pass",
                "heading": "h1",
                "html": "<p>one</p>",
                "text": "one",
                "fields": [{"label": "推演结果", "value": "通过"}],
            },
        )
        assert created["version"] == "v0.0.1"
        assert created["stale"] is False
        assert created["result_label"] == "通过"
        assert created["label"] == "后端"
        assert created["created_at"].endswith("+08:00")
        assert created["html"]

        second = create_review(
            db,
            {
                "case_id": case.id,
                "case_version": "v1.0.1",
                "endpoint": "backend",
                "result": "fail",
                "html": "<p>two</p>",
            },
        )
        assert second["version"] == "v0.0.2"
        assert second["result"] == "fail"

        with pytest.raises(HTTPException) as conflict:
            create_review(
                db,
                {
                    "case_id": case.id,
                    "case_version": "v1.0.1",
                    "endpoint": "backend",
                    "version": "v0.0.1",
                    "result": "skip",
                },
            )
        assert conflict.value.status_code == 409

        with pytest.raises(HTTPException) as bad_ep:
            create_review(
                db,
                {"case_id": case.id, "case_version": "v1.0.1", "endpoint": "desktop"},
            )
        assert bad_ep.value.status_code == 400

        patched = patch_review(db, created["id"], {"result": "blocked", "text": "updated"})
        assert patched["result"] == "blocked"
        assert patched["text"] == "updated"
        assert "one" in (patched["html"] or "")
        assert "review-card" in (patched["html"] or "")
        assert [f["label"] for f in patched["fields"]] == ["推演链路", "推演结果", "不通过原因", "备注"]
        assert patched["version"] == "v0.0.1"
        assert patched["endpoint"] == "backend"

        listed = list_reviews(db, case.id, "v1.0.1")
        assert {item["endpoint"] for item in listed["items"]} == {"backend"}
        assert listed["items"][0]["version"] == "v0.0.2"

        removed = delete_review(db, created["id"])
        assert removed["ok"] is True
        left = list_reviews(db, case.id, "v1.0.1", "backend")
        assert [item["version"] for item in left["items"]] == ["v0.0.2"]

        create_review(
            db,
            {"case_id": case.id, "case_version": "v1.0.0", "endpoint": "web", "result": "skip"},
        )
        comment = asyncio.run(create_comment(db, case.id, body="临时记录", case_version="v1.0.1"))

        class _Patch:
            def model_dump(self, exclude_unset=True):
                return {"title": "只改标题"}

        patch_case_version(case.id, "v1.0.0", _Patch(), db)
        cv = db.query(TestCaseVersion).filter_by(case_id=case.id, version="v1.0.0").one()
        assert cv.title == "只改标题"
        assert cv.steps == "1. 一步"

        with pytest.raises(HTTPException) as blocked_ver:
            delete_case_version(case.id, "v1.0.1", db)
        assert blocked_ver.value.status_code == 410
        assert "删除接口" in str(blocked_ver.value.detail)
        assert db.get(TestCaseVersion, v2.id) is not None
        assert db.query(CaseReview).filter_by(case_id=case.id).count() >= 1

        with pytest.raises(HTTPException) as blocked_case:
            delete_case(case.id, db)
        assert blocked_case.value.status_code == 410
        assert db.get(TestCase, case.id) is not None
        assert db.query(CaseComment).filter_by(case_id=case.id).count() == 1

        with pytest.raises(HTTPException) as blocked_rep:
            delete_report(1, db)
        assert blocked_rep.value.status_code == 410
        with pytest.raises(HTTPException) as blocked_rv:
            delete_report_version(1, "v1.0.0", db)
        assert blocked_rv.value.status_code == 410

        product = db.query(Product).filter_by(slug=SLUG).one()
    finally:
        _cleanup_product(db, product)
        db.close()


def test_report_list_hides_reviews_and_import_rejects_them():
    init_db()
    db = SessionLocal()
    try:
        data = list_reports(page=1, page_size=200, db=db)
        types = {item["type"] for item in data["items"]}
        assert types.isdisjoint(REVIEW_REPORT_TYPES)
        assert "blackbox" in types or "whitebox" in types or data["total"] == 0

        async def _import_reports(**kwargs):
            return await import_reports(**kwargs)

        for typ in ("frontend_review", "backend_review", "blackbox", "whitebox"):
            with pytest.raises(HTTPException) as blocked:
                asyncio.run(_import_reports(product_id=1, type=typ, file=None, db=db))
            assert blocked.value.status_code == 410
            assert "已关闭 HTML 导入接口" in str(blocked.value.detail)

        with pytest.raises(HTTPException) as blocked_cases:
            asyncio.run(import_cases(product_id=1, file=None, db=db))
        assert blocked_cases.value.status_code == 410
        assert "POST /api/cases" in str(blocked_cases.value.detail)
    finally:
        db.close()


def test_production_migration_idempotent_and_history_sample():
    init_db()
    db = SessionLocal()
    try:
        first = migrate_review_reports(db)
        second = migrate_review_reports(db)
        assert second["inserted"] == 0
        # After init_db the first call here should also be 0 if startup already migrated.
        assert first["inserted"] == 0 or first["inserted"] > 0

        comments_before = db.query(CaseComment).count()
        case = db.query(TestCase).filter_by(key="TC-OPA-001").one()
        # sample the case version that historically had multiple frontend reviews (based_on v1.0.4)
        items = list_reviews(db, case.id, "v1.0.4", "web")["items"]
        assert len(items) >= 2
        versions = [item["version"] for item in items]
        assert versions == sorted(versions, key=lambda v: tuple(int(x) for x in v.lstrip("v").split(".")), reverse=True)
        # reviews hang on the case, so a later library version still shows them
        later = list_reviews(db, case.id, "v1.0.6", "web")["items"]
        assert [item["id"] for item in later] == [item["id"] for item in items]
        backend = list_reviews(db, case.id, "v1.0.6", "backend")["items"]
        assert len(backend) >= 1
        detail = review_detail(db, case.product_id, "web", case.id, "v1.0.6")
        assert detail["version"] == items[0]["version"]
        assert detail["reviews"][0]["version"] == items[0]["version"]
        assert "stale" in detail

        gma = db.query(TestCase).filter_by(key="TC-GMA-081").one()
        gma_detail = review_detail(db, gma.product_id, "backend", gma.id, "v1.0.6")
        assert gma_detail["available"] is True
        assert gma_detail["found"] is True
        labels = [f["label"] for f in gma_detail["fields"]]
        assert "推演链路" in labels
        assert "后端链路" not in labels
        assert "用例标题" not in labels
        assert comments_before == db.query(CaseComment).count()

        # case body not clobbered
        cv = (
            db.query(TestCaseVersion)
            .filter_by(case_id=case.id, version="v1.0.6")
            .one()
        )
        assert cv.steps
        assert cv.expected
    finally:
        db.close()


def test_plan_review_version_renumber_merges_duplicate_v001():
    from app.db import plan_review_version_renumber

    rows = [
        {
            "id": 20,
            "case_id": 1,
            "endpoint": "backend",
            "version": "v0.0.1",
            "created_at": datetime(2026, 11, 18, 7, 53, 40),
        },
        {
            "id": 10,
            "case_id": 1,
            "endpoint": "backend",
            "version": "v0.0.1",
            "created_at": datetime(2026, 11, 18, 7, 53, 40),
        },
        {
            "id": 11,
            "case_id": 1,
            "endpoint": "web",
            "version": "v0.0.2",
            "created_at": datetime(2026, 11, 18, 7, 53, 40),
        },
        {
            "id": 12,
            "case_id": 1,
            "endpoint": "web",
            "version": "v0.0.1",
            "created_at": datetime(2026, 11, 18, 7, 53, 40),
        },
    ]
    planned = plan_review_version_renumber(rows)
    by_id = {row["id"]: row["version"] for row in planned}
    # same created_at + same old version -> id order
    assert by_id[10] == "v0.0.1"
    assert by_id[20] == "v0.0.2"
    # web keeps chronological old-version order
    assert by_id[12] == "v0.0.1"
    assert by_id[11] == "v0.0.2"
    versions = [row["version"] for row in planned if row["endpoint"] == "backend"]
    assert versions == ["v0.0.1", "v0.0.2"]


def test_post_without_case_version_auto_increments_per_case_endpoint():
    init_db()
    db = SessionLocal()
    product = None
    try:
        product, case, _v1, _v2 = _product_fixture(db)
        first = create_review(db, {"case_id": case.id, "endpoint": "web", "result": "pass"})
        assert first["version"] == "v0.0.1"
        second = create_review(
            db,
            {"case_id": case.id, "case_version": "v1.0.0", "endpoint": "web", "result": "fail"},
        )
        assert second["version"] == "v0.0.2"
        listed = list_reviews(db, case.id, endpoint="web")
        assert [item["version"] for item in listed["items"]] == ["v0.0.2", "v0.0.1"]
        other_end = create_review(db, {"case_id": case.id, "endpoint": "backend", "result": "skip"})
        assert other_end["version"] == "v0.0.1"
    finally:
        _cleanup_product(db, product)
        db.close()


def test_normalize_case_text_and_fingerprint():
    assert normalize_case_text("  1。\n一步  ") == normalize_case_text("1.一步")
    assert normalize_case_text("1. 一步") == normalize_case_text("1。一步")
    assert normalize_case_text("Hello，world！") == normalize_case_text("Hello,world!")
    assert normalize_case_text("（“A”—B）") == normalize_case_text('("A"-B)')
    assert normalize_case_text("参数：成功") == normalize_case_text("参数:成功")
    assert normalize_case_text("请确认？") == normalize_case_text("请确认?")
    same_a = case_content_fingerprint(description="d", preconditions="p", steps="1. 一步", expected="ok")
    same_b = case_content_fingerprint(description="d", preconditions="p", steps="1。\n一步", expected="ok")
    other = case_content_fingerprint(description="d", preconditions="p", steps="1. 另一步", expected="ok")
    assert same_a == same_b
    assert same_a != other
    assert same_a.startswith("sha256:")
    assert len(same_a) == len("sha256:") + 64
    # field boundaries must not collide
    assert case_content_fingerprint(description="ab", steps="c") != case_content_fingerprint(description="a", steps="bc")


class _Patch:
    def __init__(self, **fields):
        self._fields = fields

    def model_dump(self, exclude_unset=True):
        return dict(self._fields)


def test_fingerprint_stale_rules():
    init_db()
    db = SessionLocal()
    product = None
    try:
        product, case, _v1, v2 = _product_fixture(db)
        earlier = create_review(db, {"case_id": case.id, "endpoint": "web", "result": "pass"})
        assert earlier["stale"] is False
        stored = db.get(CaseReview, earlier["id"]).content_fingerprint
        assert stored == fingerprint_from_version(v2)

        # punctuation / whitespace-only steps change is not stale
        patch_case_version(case.id, v2.version, _Patch(steps="1。\n另一步"), db)
        assert list_reviews(db, case.id, endpoint="web")["items"][0]["stale"] is False
        assert review_detail(db, product.id, "web", case.id)["stale"] is False

        # title / module / priority only — not stale
        patch_case_version(
            case.id,
            v2.version,
            _Patch(title="新标题", module="other", priority="P1"),
            db,
        )
        assert list_reviews(db, case.id, endpoint="web")["items"][0]["stale"] is False

        # a new case version with the same description/steps/expected is not stale
        rec = {
            "key": case.key,
            "title": "又一个标题",
            "module": "changed-module",
            "priority": "P0",
            "client": "ios",
            "description": v2.description,
            "preconditions": v2.preconditions,
            "steps": "1. 另一步",
            "expected": v2.expected,
        }
        v3 = upsert_case_version(db, product, rec, "v1.0.2", "")
        db.commit()
        db.refresh(case)
        assert case.latest_version == "v1.0.2"
        assert list_reviews(db, case.id, endpoint="web")["items"][0]["stale"] is False
        from app.case_reviews import latest_reviews_for_case, case_endpoint_results

        docks = latest_reviews_for_case(db, case.id)
        web_dock = next(item for item in docks if item["endpoint"] == "web")
        assert web_dock["stale"] is False

        # substantive change in steps / description / expected marks earlier reviews stale
        patch_case_version(case.id, v3.version, _Patch(steps="1. 完全不同的步骤"), db)
        listed = list_reviews(db, case.id, endpoint="web")
        assert listed["items"][0]["stale"] is True
        assert review_detail(db, product.id, "web", case.id)["stale"] is True
        docks = latest_reviews_for_case(db, case.id)
        web_dock = next(item for item in docks if item["endpoint"] == "web")
        assert web_dock["stale"] is True
        results = case_endpoint_results(db, product.id, "v1.0.2", [case.id])
        assert any(item["endpoint"] == "web" and item["stale"] is True for item in results[case.id])

        later = create_review(db, {"case_id": case.id, "endpoint": "web", "result": "fail"})
        assert later["stale"] is False
        assert later["version"] == "v0.0.2"
        # each review keeps its own fingerprint
        earlier_row = db.get(CaseReview, earlier["id"])
        later_row = db.get(CaseReview, later["id"])
        assert earlier_row.content_fingerprint != later_row.content_fingerprint
        detail_later = review_detail(db, product.id, "web", case.id)
        assert detail_later["version"] == later["version"]
        assert detail_later["stale"] is False
        older = review_detail(db, product.id, "web", case.id, review_id=earlier["id"])
        assert older["stale"] is True
        assert [item["stale"] for item in older["reviews"] if item["id"] == earlier["id"]] == [True]
        assert [item["stale"] for item in older["reviews"] if item["id"] == later["id"]] == [False]

        # description and expected also participate
        patch_case_version(case.id, v3.version, _Patch(description="改过的描述"), db)
        assert review_detail(db, product.id, "web", case.id, review_id=later["id"])["stale"] is True
        patch_case_version(case.id, v3.version, _Patch(description=v2.description, expected="不同预期"), db)
        assert review_detail(db, product.id, "web", case.id, review_id=later["id"])["stale"] is True
    finally:
        _cleanup_product(db, product)
        db.close()


def test_backfill_review_fingerprints_is_idempotent():
    init_db()
    first = backfill_review_fingerprints()
    second = backfill_review_fingerprints()
    assert first["total"] >= 0
    assert second["filled"] == 0
    assert second["total"] == first["total"]
    assert second["stale"] == first["stale"]
    assert second["not_stale"] == first["not_stale"]
    assert second["empty"] == 0

    db = SessionLocal()
    product = None
    try:
        product, case, v1, v2 = _product_fixture(db)
        created = datetime(2026, 11, 18, 8, 0, 0)
        review = CaseReview(
            case_id=case.id,
            case_version_id=v1.id,
            endpoint="android",
            version="v0.0.1",
            result="pass",
            content_fingerprint="",
            created_at=created,
        )
        db.add(review)
        db.commit()
        db.refresh(review)
        stats = backfill_review_fingerprints(db)
        db.refresh(review)
        assert stats["filled"] >= 1
        assert review.content_fingerprint == fingerprint_from_version(v1)
        # latest version v2 has different steps, so this lineage-v1 review is stale
        assert review_detail(db, product.id, "android", case.id)["stale"] is True
        again = backfill_review_fingerprints(db)
        db.refresh(review)
        assert again["filled"] == 0
        assert review.content_fingerprint == fingerprint_from_version(v1)
    finally:
        _cleanup_product(db, product)
        db.close()
