from __future__ import annotations

import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

import markdown
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session, joinedload

from app.case_reviews import REVIEW_REPORT_TYPES
from app.config import FILES_DIR, FRONTEND_DIST
from app.db import get_db, init_db, touch_case
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
from app.parsers import (
    build_priority_stats,
    case_seq_from_key,
    extract_case_document_info,
    parse_file,
    parse_pending_notes,
    count_untested_cases,
    version_from_html,
)
from app.seed import bump_latest, store_file, upsert_case_version, upsert_report_version, version_key

app = FastAPI(title="测谱 · 测试用例与报告平台", version="0.1.0")

RESULT_LABELS = {
    "pass": "通过",
    "fail": "失败",
    "skip": "跳过",
    "blocked": "阻塞",
    "untested": "未测",
    "": "未记录",
}

REPORT_TYPE_LABELS = {
    "blackbox": "黑盒测试",
    "frontend_review": "前端推演",
    "backend_review": "后端推演",
    "whitebox": "白盒测试",
}


@app.on_event("startup")
def _startup():
    init_db()
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    import threading

    from app.db import SessionLocal
    from app.review_store import backfill_review_details_async
    from app.reviews import backfill_based_on_case_versions

    db = SessionLocal()
    try:
        backfill_based_on_case_versions(db)
        from app.case_reviews import migrate_review_reports

        migrate_review_reports(db)
    finally:
        db.close()
    threading.Thread(target=backfill_review_details_async, name="review-detail-backfill", daemon=True).start()
    from app.case_doc_store import backfill_case_doc_metas_async

    threading.Thread(target=backfill_case_doc_metas_async, name="case-doc-backfill", daemon=True).start()


def version_sort(values: list[str]) -> list[str]:
    return sorted(values, key=version_key)


class CaseIn(BaseModel):
    product_id: int
    key: str
    version: str | None = None
    title: str = ""
    module: str = ""
    priority: str = ""
    client: str = ""
    description: str = ""
    preconditions: str = ""
    steps: str = ""
    expected: str = ""


class CaseUpdate(BaseModel):
    version: str | None = None
    title: str = ""
    module: str = ""
    priority: str = ""
    client: str = ""
    description: str = ""
    preconditions: str = ""
    steps: str = ""
    expected: str = ""


class CaseVersionPatch(BaseModel):
    title: str | None = None
    module: str | None = None
    priority: str | None = None
    client: str | None = None
    description: str | None = None
    preconditions: str | None = None
    steps: str | None = None
    expected: str | None = None


class ReviewIn(BaseModel):
    case_id: int
    case_version: str | None = None
    endpoint: str
    version: str | None = None
    result: str | None = None
    fields: list[Any] | None = None
    html: str | None = None
    text: str | None = None
    heading: str | None = None
    repo: str | None = None
    branch: str | None = None
    participants: str | None = None
    style_css: str | None = None


class ReviewPatch(BaseModel):
    result: str | None = None
    fields: list[Any] | None = None
    html: str | None = None
    text: str | None = None
    heading: str | None = None
    repo: str | None = None
    branch: str | None = None
    participants: str | None = None
    style_css: str | None = None


class LinkIn(BaseModel):
    report_version_id: int
    case_id: int
    case_version_id: int | None = None
    result: str = ""


class ProductIn(BaseModel):
    name: str
    slug: str = Field(min_length=1)


def next_version(current: str | None) -> str:
    if not current:
        return "v1.0.0"
    parts = [int(x) for x in re.findall(r"\d+", current)]
    if not parts:
        return "v1.0.0"
    parts[-1] += 1
    return "v" + ".".join(str(p) for p in parts)


def product_out(p: Product) -> dict:
    return {"id": p.id, "name": p.name, "slug": p.slug}


def resolve_file(rel: str | None) -> Path | None:
    if not rel:
        return None
    path = (FILES_DIR / rel).resolve()
    if not str(path).startswith(str(FILES_DIR.resolve())):
        return None
    if not path.is_file():
        return None
    return path


# --------------- meta / overview ---------------


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/products")
def list_products(db: Session = Depends(get_db)):
    return [product_out(p) for p in db.query(Product).order_by(Product.id).all()]


@app.post("/api/products")
def create_product(body: ProductIn, db: Session = Depends(get_db)):
    if db.query(Product).filter_by(slug=body.slug).one_or_none():
        raise HTTPException(400, "slug 已存在")
    p = Product(name=body.name, slug=body.slug)
    db.add(p)
    db.commit()
    db.refresh(p)
    return product_out(p)


@app.get("/api/meta")
def meta(product_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(TestCaseVersion.module).filter(TestCaseVersion.module != "")
    pq = db.query(TestCaseVersion.priority).filter(TestCaseVersion.priority != "")
    cq = db.query(TestCaseVersion.client).filter(TestCaseVersion.client != "")
    rq = db.query(Report.type).filter(Report.type.notin_(tuple(REVIEW_REPORT_TYPES)))
    vq = (
        db.query(ReportVersion.version)
        .join(Report, ReportVersion.report_id == Report.id)
        .filter(Report.type.notin_(tuple(REVIEW_REPORT_TYPES)))
    )
    if product_id:
        q = q.join(TestCase).filter(TestCase.product_id == product_id)
        pq = pq.join(TestCase).filter(TestCase.product_id == product_id)
        cq = cq.join(TestCase).filter(TestCase.product_id == product_id)
        rq = rq.filter(Report.product_id == product_id)
        vq = vq.filter(Report.product_id == product_id)
    modules = sorted({r[0] for r in q.distinct().all()})
    priorities = sorted({r[0] for r in pq.distinct().all()})
    clients = sorted({r[0] for r in cq.distinct().all()})
    types = sorted({r[0] for r in rq.distinct().all()})
    versions = version_sort(list({r[0] for r in vq.distinct().all() if r[0]}))
    cvq = db.query(TestCaseVersion.version).filter(TestCaseVersion.version != "")
    if product_id:
        cvq = cvq.join(TestCase).filter(TestCase.product_id == product_id)
    case_versions = version_sort(list({r[0] for r in cvq.distinct().all()}))
    return {
        "modules": modules,
        "priorities": priorities,
        "clients": clients,
        "report_types": [{"value": t, "label": REPORT_TYPE_LABELS.get(t, t)} for t in types],
        "report_versions": versions,
        "case_versions": case_versions,
        "type_labels": REPORT_TYPE_LABELS,
        "result_labels": RESULT_LABELS,
    }


@app.get("/api/overview")
def overview(db: Session = Depends(get_db)):
    products = db.query(Product).order_by(Product.id).all()
    by_product = []
    for p in products:
        case_ids = [c.id for c in db.query(TestCase.id).filter_by(product_id=p.id)]
        report_ids = [r.id for r in db.query(Report.id).filter_by(product_id=p.id)]
        link_count = (
            db.query(func.count(ReportCaseLink.id))
            .join(ReportVersion)
            .join(Report)
            .filter(Report.product_id == p.id)
            .scalar()
        )
        by_product.append(
            {
                "id": p.id,
                "name": p.name,
                "slug": p.slug,
                "cases": len(case_ids),
                "case_versions": db.query(func.count(TestCaseVersion.id))
                .join(TestCase)
                .filter(TestCase.product_id == p.id)
                .scalar(),
                "reports": len(report_ids),
                "report_versions": db.query(func.count(ReportVersion.id))
                .join(Report)
                .filter(Report.product_id == p.id)
                .scalar(),
                "links": link_count or 0,
            }
        )

    result_rows = (
        db.query(ReportCaseLink.result, func.count(ReportCaseLink.id))
        .group_by(ReportCaseLink.result)
        .all()
    )
    results = {k or "empty": v for k, v in result_rows}

    recent_cases = (
        db.query(TestCaseVersion)
        .options(joinedload(TestCaseVersion.case).joinedload(TestCase.product))
        .order_by(TestCaseVersion.created_at.desc(), TestCaseVersion.id.desc())
        .limit(8)
        .all()
    )
    recent_reports = (
        db.query(ReportVersion)
        .join(Report, ReportVersion.report_id == Report.id)
        .options(joinedload(ReportVersion.report).joinedload(Report.product))
        .filter(Report.type.notin_(tuple(REVIEW_REPORT_TYPES)))
        .order_by(ReportVersion.created_at.desc(), ReportVersion.id.desc())
        .limit(8)
        .all()
    )
    return {
        "products": db.query(func.count(Product.id)).scalar(),
        "cases": db.query(func.count(TestCase.id)).scalar(),
        "case_versions": db.query(func.count(TestCaseVersion.id)).scalar(),
        "reports": db.query(func.count(Report.id)).scalar(),
        "report_versions": db.query(func.count(ReportVersion.id)).scalar(),
        "links": db.query(func.count(ReportCaseLink.id)).scalar(),
        "by_product": by_product,
        "results": results,
        "recent_cases": [
            {
                "case_id": cv.case.id,
                "key": cv.case.key,
                "title": cv.title,
                "version": cv.version,
                "product": cv.case.product.name,
                "created_at": cv.created_at.isoformat() if cv.created_at else None,
            }
            for cv in recent_cases
        ],
        "recent_reports": [
            {
                "report_id": rv.report.id,
                "title": rv.report.title,
                "type": rv.report.type,
                "type_label": REPORT_TYPE_LABELS.get(rv.report.type, rv.report.type),
                "version": rv.version,
                "product": rv.report.product.name,
                "created_at": rv.created_at.isoformat() if rv.created_at else None,
            }
            for rv in recent_reports
        ],
    }


# --------------- cases ---------------


@app.get("/api/cases")
def list_cases(
    q: str | None = None,
    product_id: int | None = None,
    priority: str | None = None,
    module: str | None = None,
    client: str | None = None,
    version: str | None = None,
    include_body: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(40, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    query = (
        db.query(TestCase, TestCaseVersion)
        .join(
            TestCaseVersion,
            and_(
                TestCaseVersion.case_id == TestCase.id,
                TestCaseVersion.version == (version or TestCase.latest_version),
            ),
        )
        .join(Product, Product.id == TestCase.product_id)
    )
    if product_id:
        query = query.filter(TestCase.product_id == product_id)
    if priority:
        query = query.filter(TestCaseVersion.priority == priority)
    if module:
        query = query.filter(TestCaseVersion.module == module)
    if client:
        query = query.filter(TestCaseVersion.client == client)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(
                TestCase.key.ilike(like),
                TestCaseVersion.title.ilike(like),
                TestCaseVersion.module.ilike(like),
                TestCaseVersion.description.ilike(like),
            )
        )

    total = query.with_entities(func.count(TestCase.id)).scalar() or 0
    rows = (
        query.order_by(Product.id, TestCase.key)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    # link counts for current page
    ids = [case.id for case, _ in rows]
    link_map: dict[int, int] = {}
    if ids:
        for cid, cnt in (
            db.query(ReportCaseLink.case_id, func.count(ReportCaseLink.id))
            .filter(ReportCaseLink.case_id.in_(ids))
            .group_by(ReportCaseLink.case_id)
            .all()
        ):
            link_map[cid] = cnt
    ver_count: dict[int, int] = {}
    if ids:
        for cid, cnt in (
            db.query(TestCaseVersion.case_id, func.count(TestCaseVersion.id))
            .filter(TestCaseVersion.case_id.in_(ids))
            .group_by(TestCaseVersion.case_id)
            .all()
        ):
            ver_count[cid] = cnt

    items = []
    for case, lv in rows:
        item = {
            "id": case.id,
            "key": case.key,
            "latest_version": case.latest_version,
            "version": lv.version,
            "version_id": lv.id,
            "seq": case_seq_from_key(case.key),
            "version_count": ver_count.get(case.id, 1),
            "title": lv.title,
            "module": lv.module,
            "priority": lv.priority,
            "client": lv.client,
            "product": product_out(case.product) if case.product else {"id": case.product_id},
            "link_count": link_map.get(case.id, 0),
        }
        if include_body:
            item.update(
                {
                    "description": lv.description,
                    "preconditions": lv.preconditions,
                    "steps": lv.steps,
                    "expected": lv.expected,
                    "source_file": lv.source_file,
                }
            )
        items.append(item)
    # product may not be loaded — load map
    # Fix: TestCase.product wasn't joinedload. We joined Product already; access via case.product needs relationship. Let's populate properly.
    prod_map = {p.id: p for p in db.query(Product).all()}
    for item in items:
        p = prod_map.get(item["product"]["id"] if isinstance(item["product"], dict) else None)
        # already handled below if relationship works
        pass

    # If relationship didn't load, fix products
    for item, (case, _) in zip(items, rows):
        p = db.get(Product, case.product_id)
        item["product"] = product_out(p) if p else {"id": case.product_id, "name": "", "slug": ""}

    return {"items": items, "total": total, "page": page, "page_size": page_size}


@app.get("/api/cases/{case_id}")
def get_case(case_id: int, version: str | None = None, db: Session = Depends(get_db)):
    case = db.get(TestCase, case_id)
    if not case:
        raise HTTPException(404, "用例不存在")
    versions = (
        db.query(TestCaseVersion)
        .filter_by(case_id=case.id)
        .all()
    )
    versions = sorted(versions, key=lambda v: version_key(v.version))
    current = None
    if version:
        current = next((v for v in versions if v.version == version), None)
        if not current:
            raise HTTPException(404, "该版本不存在")
    else:
        current = next((v for v in versions if v.version == case.latest_version), versions[-1] if versions else None)
    if not current:
        raise HTTPException(404, "用例尚无版本")

    links = (
        db.query(ReportCaseLink)
        .options(
            joinedload(ReportCaseLink.report_version).joinedload(ReportVersion.report),
            joinedload(ReportCaseLink.case_version),
        )
        .filter_by(case_id=case.id)
        .all()
    )
    reports = []
    for link in links:
        rv = link.report_version
        if rv.report.type in REVIEW_REPORT_TYPES:
            continue
        reports.append(
            {
                "link_id": link.id,
                "report_id": rv.report.id,
                "title": rv.report.title,
                "type": rv.report.type,
                "type_label": REPORT_TYPE_LABELS.get(rv.report.type, rv.report.type),
                "report_version": rv.version,
                "report_version_id": rv.id,
                "case_version": link.case_version.version if link.case_version else None,
                "matches_current": (link.case_version_id == current.id) if link.case_version_id else False,
                "result": link.result or "",
                "result_label": RESULT_LABELS.get(link.result or "", link.result or "未记录"),
            }
        )

    from app.case_reviews import latest_reviews_for_case

    reviews = latest_reviews_for_case(db, case.id)

    product = db.get(Product, case.product_id)
    return {
        "id": case.id,
        "key": case.key,
        "latest_version": case.latest_version,
        "updated_at": case.updated_at.isoformat() if case.updated_at else None,
        "product": product_out(product) if product else None,
        "versions": [v.version for v in versions],
        "current": {
            "id": current.id,
            "version": current.version,
            "title": current.title,
            "module": current.module,
            "priority": current.priority,
            "client": current.client,
            "description": current.description,
            "preconditions": current.preconditions,
            "steps": current.steps,
            "expected": current.expected,
            "source_file": current.source_file,
            "created_at": current.created_at.isoformat() if current.created_at else None,
        },
        "reviews": reviews,
        "reports": reports,
    }


@app.post("/api/cases")
def create_case(body: CaseIn, db: Session = Depends(get_db)):
    product = db.get(Product, body.product_id)
    if not product:
        raise HTTPException(404, "产品不存在")
    existing = db.query(TestCase).filter_by(product_id=body.product_id, key=body.key.strip()).one_or_none()
    version = body.version or (next_version(existing.latest_version) if existing else "v1.0.0")
    rec = body.model_dump()
    rec["key"] = body.key.strip()
    cv = upsert_case_version(db, product, rec, version, source_file="")
    db.commit()
    return {"id": cv.case_id, "version": cv.version}


@app.post("/api/cases/{case_id}/versions")
def add_case_version(case_id: int, body: CaseUpdate, db: Session = Depends(get_db)):
    case = db.get(TestCase, case_id)
    if not case:
        raise HTTPException(404, "用例不存在")
    product = db.get(Product, case.product_id)
    version = body.version or next_version(case.latest_version)
    rec = body.model_dump()
    rec["key"] = case.key
    cv = upsert_case_version(db, product, rec, version, source_file="")
    db.commit()
    return {"id": case.id, "version": cv.version}


@app.patch("/api/cases/{case_id}/versions/{version}")
def patch_case_version(case_id: int, version: str, body: CaseVersionPatch, db: Session = Depends(get_db)):
    case = db.get(TestCase, case_id)
    if not case:
        raise HTTPException(404, "用例不存在")
    cv = (
        db.query(TestCaseVersion)
        .filter_by(case_id=case.id, version=version)
        .one_or_none()
    )
    if not cv:
        raise HTTPException(404, "该版本不存在")
    updates = body.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(cv, key, value if value is not None else "")
    if updates:
        touch_case(case)
    db.commit()
    return {"id": case.id, "version": cv.version, "updated_at": case.updated_at.isoformat() if case.updated_at else None}


DELETE_DISABLED_DETAIL = "已关闭用例和报告的删除接口。"

IMPORT_DISABLED_DETAIL = (
    "已关闭 HTML 导入接口。用例请改用 POST /api/cases 与 POST /api/cases/{id}/versions，"
    "推演请改用 POST /api/reviews。"
)


@app.delete("/api/cases/{case_id}/versions/{version}")
def delete_case_version(case_id: int, version: str, db: Session = Depends(get_db)):
    raise HTTPException(410, DELETE_DISABLED_DETAIL)




@app.delete("/api/cases/{case_id}")
def delete_case(case_id: int, db: Session = Depends(get_db)):
    raise HTTPException(410, DELETE_DISABLED_DETAIL)




# --------------- reports ---------------


@app.get("/api/reports")
def list_reports(
    q: str | None = None,
    product_id: int | None = None,
    type: str | None = None,
    version: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(40, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = db.query(Report, ReportVersion).join(
        ReportVersion,
        and_(
            ReportVersion.report_id == Report.id,
            ReportVersion.version == Report.latest_version,
        ),
    ).filter(Report.type.notin_(tuple(REVIEW_REPORT_TYPES)))
    if product_id:
        query = query.filter(Report.product_id == product_id)
    if type:
        query = query.filter(Report.type == type)
    if version:
        # filter reports that have this version (not only latest)
        ids = [
            r[0]
            for r in db.query(ReportVersion.report_id)
            .filter(ReportVersion.version == version)
            .distinct()
            .all()
        ]
        query = query.filter(Report.id.in_(ids or [-1]))
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Report.title.ilike(like),
                ReportVersion.summary.ilike(like),
                ReportVersion.conclusion.ilike(like),
            )
        )
    total = query.with_entities(func.count(Report.id)).scalar() or 0
    rows = (
        query.order_by(Report.product_id, Report.type, Report.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    ids = [r.id for r, _ in rows]
    link_map: dict[int, int] = {}
    ver_count: dict[int, int] = {}
    if ids:
        # links on latest version
        latest_ids = [lv.id for _, lv in rows]
        for rid, cnt in (
            db.query(ReportVersion.report_id, func.count(ReportCaseLink.id))
            .join(ReportCaseLink, ReportCaseLink.report_version_id == ReportVersion.id)
            .filter(ReportVersion.id.in_(latest_ids))
            .group_by(ReportVersion.report_id)
            .all()
        ):
            link_map[rid] = cnt
        for rid, cnt in (
            db.query(ReportVersion.report_id, func.count(ReportVersion.id))
            .filter(ReportVersion.report_id.in_(ids))
            .group_by(ReportVersion.report_id)
            .all()
        ):
            ver_count[rid] = cnt

    items = []
    for report, lv in rows:
        p = db.get(Product, report.product_id)
        items.append(
            {
                "id": report.id,
                "title": report.title,
                "type": report.type,
                "type_label": REPORT_TYPE_LABELS.get(report.type, report.type),
                "latest_version": report.latest_version,
                "version_count": ver_count.get(report.id, 1),
                "summary": (lv.conclusion or lv.summary or "")[:180],
                "product": product_out(p) if p else None,
                "link_count": link_map.get(report.id, 0),
                "created_at": lv.created_at.isoformat() if lv.created_at else None,
            }
        )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@app.get("/api/reports/{report_id}")
def get_report(report_id: int, version: str | None = None, db: Session = Depends(get_db)):
    report = db.get(Report, report_id)
    if not report:
        raise HTTPException(404, "报告不存在")
    versions = sorted(
        db.query(ReportVersion).filter_by(report_id=report.id).all(),
        key=lambda v: version_key(v.version),
    )
    if version:
        current = next((v for v in versions if v.version == version), None)
        if not current:
            raise HTTPException(404, "该版本不存在")
    else:
        current = next((v for v in versions if v.version == report.latest_version), versions[-1] if versions else None)
    if not current:
        raise HTTPException(404, "报告尚无版本")

    links = (
        db.query(ReportCaseLink)
        .options(
            joinedload(ReportCaseLink.case).joinedload(TestCase.product),
            joinedload(ReportCaseLink.case_version),
        )
        .filter_by(report_version_id=current.id)
        .all()
    )
    cases = []
    for link in sorted(links, key=lambda l: l.case.key if l.case else ""):
        title = link.case_version.title if link.case_version else ""
        if not title:
            # fallback latest title
            latest_cv = (
                db.query(TestCaseVersion)
                .filter_by(case_id=link.case_id, version=link.case.latest_version)
                .one_or_none()
            )
            title = latest_cv.title if latest_cv else ""
        cases.append(
            {
                "link_id": link.id,
                "case_id": link.case_id,
                "key": link.case.key,
                "title": title,
                "case_version": link.case_version.version if link.case_version else None,
                "result": link.result or "",
                "result_label": RESULT_LABELS.get(link.result or "", link.result or "未记录"),
            }
        )

    product = db.get(Product, report.product_id)
    src = current.source_file or ""
    ext = Path(src).suffix.lower() if src else ""
    return {
        "id": report.id,
        "title": report.title,
        "type": report.type,
        "type_label": REPORT_TYPE_LABELS.get(report.type, report.type),
        "latest_version": report.latest_version,
        "product": product_out(product) if product else None,
        "versions": [v.version for v in versions],
        "current": {
            "id": current.id,
            "version": current.version,
            "summary": current.summary,
            "conclusion": current.conclusion,
            "source_file": current.source_file,
            "based_on_case_version": current.based_on_case_version,
            "preview_kind": "markdown" if ext in {".md", ".markdown"} else ("html" if ext in {".html", ".htm"} else "file"),
            "created_at": current.created_at.isoformat() if current.created_at else None,
        },
        "cases": cases,
        "result_summary": _result_summary(cases),
    }


def _result_summary(cases: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for c in cases:
        key = c["result"] or "empty"
        counts[key] = counts.get(key, 0) + 1
    return counts


@app.get("/api/report-versions/{version_id}/preview")
def preview_report(version_id: int, db: Session = Depends(get_db)):
    rv = db.get(ReportVersion, version_id)
    if not rv:
        raise HTTPException(404, "报告版本不存在")
    path = resolve_file(rv.source_file)
    if not path:
        raise HTTPException(404, "源文件不存在")
    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown"}:
        html = markdown.markdown(
            path.read_text(encoding="utf-8", errors="replace"),
            extensions=["tables", "fenced_code", "nl2br"],
        )
        page = (
            "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>"
            "<style>body{font-family:ui-sans-serif,system-ui,sans-serif;background:#0b1018;"
            "color:#d7e4ef;padding:32px 40px;line-height:1.65;max-width:980px;margin:0 auto}"
            "a{color:#3ce0ff} table{border-collapse:collapse;width:100%} "
            "th,td{border:1px solid #243044;padding:6px 8px} code{background:#151c28;padding:0 4px}"
            "pre{background:#151c28;padding:12px;overflow:auto}</style></head><body>"
            + html
            + "</body></html>"
        )
        return HTMLResponse(page)
    if suffix in {".html", ".htm"}:
        return FileResponse(path, media_type="text/html; charset=utf-8")
    return FileResponse(path)


@app.get("/api/case-versions/{version_id}/preview")
def preview_case_source(version_id: int, db: Session = Depends(get_db)):
    cv = db.get(TestCaseVersion, version_id)
    if not cv:
        raise HTTPException(404, "用例版本不存在")
    path = resolve_file(cv.source_file)
    if not path:
        raise HTTPException(404, "源文件不存在")
    suffix = path.suffix.lower()
    if suffix in {".html", ".htm"}:
        return FileResponse(path, media_type="text/html; charset=utf-8")
    if suffix in {".md", ".markdown"}:
        html = markdown.markdown(path.read_text(encoding="utf-8", errors="replace"), extensions=["tables", "fenced_code"])
        return HTMLResponse(html)
    return FileResponse(path)


# --------------- links & import ---------------


@app.post("/api/links")
def create_link(body: LinkIn, db: Session = Depends(get_db)):
    rv = db.get(ReportVersion, body.report_version_id)
    case = db.get(TestCase, body.case_id)
    if not rv or not case:
        raise HTTPException(404, "报告版本或用例不存在")
    existing = (
        db.query(ReportCaseLink)
        .filter_by(report_version_id=body.report_version_id, case_id=body.case_id)
        .one_or_none()
    )
    if existing:
        existing.case_version_id = body.case_version_id
        existing.result = body.result or existing.result
        db.commit()
        return {"id": existing.id, "updated": True}
    link = ReportCaseLink(
        report_version_id=body.report_version_id,
        case_id=body.case_id,
        case_version_id=body.case_version_id,
        result=body.result or "",
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return {"id": link.id, "updated": False}


@app.delete("/api/reports/{report_id}/versions/{version}")
def delete_report_version(report_id: int, version: str, db: Session = Depends(get_db)):
    raise HTTPException(410, DELETE_DISABLED_DETAIL)


@app.delete("/api/reports/{report_id}")
def delete_report(report_id: int, db: Session = Depends(get_db)):
    raise HTTPException(410, DELETE_DISABLED_DETAIL)


@app.delete("/api/links/{link_id}")
def delete_link(link_id: int, db: Session = Depends(get_db)):
    link = db.get(ReportCaseLink, link_id)
    if not link:
        raise HTTPException(404, "关联不存在")
    db.delete(link)
    db.commit()
    return {"ok": True}


@app.post("/api/imports/cases")
async def import_cases(
    product_id: int | None = Form(None),
    version: str | None = Form(None),
    key_prefix: str | None = Form(None),
    file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    raise HTTPException(410, IMPORT_DISABLED_DETAIL)


@app.post("/api/imports/reports")
async def import_reports(
    product_id: int | None = Form(None),
    type: str | None = Form(None),
    title: str | None = Form(None),
    version: str | None = Form(None),
    key_prefix: str | None = Form(None),
    file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    raise HTTPException(410, IMPORT_DISABLED_DETAIL)


def _guess_prefix(product: Product) -> str:
    return {
        "price-openapi": "TC-OPA",
        "global-model": "TC-GMA",
        "r58l": "TC-R58",
        "exdata-vin": "TC-EXD",
        "gt06-a5": "TC-A5",
    }.get(product.slug, "TC-GEN")


# --------------- case document & review entries ---------------


@app.get("/api/case-docs")
def get_case_docs(
    product_id: int,
    version: str | None = None,
    q: str | None = None,
    priority: str | None = None,
    review_endpoints: Annotated[list[str] | None, Query()] = None,
    review_results: Annotated[list[str] | None, Query()] = None,
    stale: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "产品不存在")
    from app.reviews import case_endpoint_results, product_case_versions

    versions = product_case_versions(db, product_id)
    empty_info = {"available": False, "title": "", "fields": [], "fragment_page": ""}
    empty_stats = {"total": 0, "priorities": [], "untested": 0}
    empty = {
        "product": product_out(product),
        "version": version,
        "versions": versions,
        "items": [],
        "total": 0,
        "page": 1,
        "page_size": page_size,
        "priorities": [],
        "pending": [],
        "source_file": "",
        "priority_stats": empty_stats,
        "case_info": empty_info,
    }
    if not versions:
        return empty
    current = version if version in versions else versions[-1]
    rows = (
        db.query(TestCase, TestCaseVersion)
        .join(
            TestCaseVersion,
            and_(
                TestCaseVersion.case_id == TestCase.id,
                TestCaseVersion.version == current,
            ),
        )
        .filter(TestCase.product_id == product_id)
        .all()
    )

    def sort_key(row):
        case, _lv = row
        seq = case_seq_from_key(case.key)
        parts = seq.split("-")
        nums = tuple(int(p) if p.isdigit() else 0 for p in parts)
        nums = (nums + (0, 0, 0))[:3]
        return (*nums, case.key)

    rows = sorted(rows, key=sort_key)
    priorities = sorted({lv.priority for _c, lv in rows if lv.priority})
    source_file = next((lv.source_file for _c, lv in rows if lv.source_file), "")

    needle = (q or "").strip().lower()
    filtered = []
    for case, lv in rows:
        if priority and lv.priority != priority:
            continue
        if needle:
            blob = " ".join(
                [
                    case_seq_from_key(case.key),
                    case.key,
                    lv.title or "",
                    lv.description or "",
                    lv.module or "",
                    lv.client or "",
                ]
            ).lower()
            if needle not in blob:
                continue
        filtered.append((case, lv))

    from app.case_reviews import (
        filter_cases_by_review,
        filter_cases_by_stale_review,
        normalize_review_endpoints,
        normalize_review_results,
    )

    review_eps = normalize_review_endpoints(review_endpoints)
    review_res = normalize_review_results(review_results)
    if review_eps or review_res:
        kept_ids = filter_cases_by_review(
            db, [c.id for c, _ in filtered], endpoints=review_eps, results=review_res
        )
        filtered = [(c, lv) for c, lv in filtered if c.id in kept_ids]
    if stale:
        stale_ids = filter_cases_by_stale_review(db, [c.id for c, _ in filtered])
        filtered = [(c, lv) for c, lv in filtered if c.id in stale_ids]

    total = len(filtered)
    page_count = max(1, (total + page_size - 1) // page_size) if total else 1
    if page > page_count:
        page = page_count
    start = (page - 1) * page_size
    page_rows = filtered[start : start + page_size]
    ids = [c.id for c, _ in page_rows]
    states = case_endpoint_results(db, product_id, current, ids)
    from app.comments import comment_counts, comment_environments

    counts = comment_counts(db, ids)
    env_map = comment_environments(db, ids)

    items = []
    for case, lv in page_rows:
        items.append(
            {
                "id": case.id,
                "key": case.key,
                "seq": case_seq_from_key(case.key),
                "version": lv.version,
                "latest_version": case.latest_version,
                "version_id": lv.id,
                "title": lv.title or lv.description,
                "module": lv.module,
                "priority": lv.priority,
                "client": lv.client,
                "description": lv.description or lv.title,
                "preconditions": lv.preconditions,
                "steps": lv.steps,
                "expected": lv.expected,
                "endpoints": states.get(case.id, []),
                "comment_count": counts.get(case.id, 0),
                "env_comments": env_map.get(case.id, {}),
            }
        )
    from app.case_doc_store import get_case_doc_meta

    doc_meta = get_case_doc_meta(db, product_id, current, source_file)
    pending = doc_meta["pending"]
    case_info = doc_meta["case_info"]
    untested = doc_meta["untested"]
    priority_stats = build_priority_stats([lv.priority for _c, lv in rows], untested)
    return {
        "product": product_out(product),
        "version": current,
        "versions": versions,
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "priorities": priorities,
        "pending": pending,
        "source_file": source_file,
        "priority_stats": priority_stats,
        "case_info": case_info,
    }


@app.get("/api/review-entries")
def get_review_entries(
    product_id: int,
    case_version: str | None = None,
    db: Session = Depends(get_db),
):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "产品不存在")
    from app.reviews import review_entries

    data = review_entries(db, product_id, case_version)
    data["product"] = product_out(product)
    return data


@app.get("/api/review-detail")
def get_review_detail(
    product_id: int,
    endpoint: str,
    case_id: int,
    case_version: str | None = None,
    review_id: int | None = None,
    review_version: str | None = None,
    db: Session = Depends(get_db),
):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "产品不存在")
    from app.reviews import ENDPOINT_LABELS, review_detail

    if endpoint not in ENDPOINT_LABELS:
        raise HTTPException(400, "未知端")
    data = review_detail(
        db,
        product_id,
        endpoint,
        case_id,
        case_version,
        review_id=review_id,
        review_version=review_version,
    )
    if data.get("error") == "用例不存在":
        raise HTTPException(404, "用例不存在")
    if data.get("error") == "推演记录不存在":
        raise HTTPException(404, "推演记录不存在")
    data["product"] = product_out(product)
    return data


@app.get("/api/reviews")
def get_reviews(
    case_id: int = Query(...),
    case_version: str | None = None,
    endpoint: str | None = None,
    db: Session = Depends(get_db),
):
    from app.case_reviews import list_reviews

    return list_reviews(db, case_id, case_version, endpoint)


@app.get("/api/reviews/{review_id}")
def get_review(review_id: int, db: Session = Depends(get_db)):
    from app.case_reviews import get_review as _get

    return _get(db, review_id)


@app.post("/api/reviews")
def post_review(body: ReviewIn, db: Session = Depends(get_db)):
    from app.case_reviews import create_review

    return create_review(db, body.model_dump())


@app.patch("/api/reviews/{review_id}")
def patch_review_api(review_id: int, body: ReviewPatch, db: Session = Depends(get_db)):
    from app.case_reviews import patch_review

    return patch_review(db, review_id, body.model_dump(exclude_unset=True))


@app.delete("/api/reviews/{review_id}")
def delete_review_api(review_id: int, db: Session = Depends(get_db)):
    from app.case_reviews import delete_review

    return delete_review(db, review_id)




@app.get("/api/cases/{case_id}/comments")
def get_case_comments(case_id: int, db: Session = Depends(get_db)):
    from app.comments import list_comments

    return list_comments(db, case_id)


@app.post("/api/cases/{case_id}/comments")
async def post_case_comment(
    case_id: int,
    body: str = Form(""),
    case_version: str | None = Form(None),
    environment: str | None = Form(None),
    images: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
):
    from app.comments import create_comment

    return await create_comment(
        db,
        case_id,
        body=body or "",
        case_version=case_version or "",
        environment=environment or "",
        images=images,
    )


@app.delete("/api/cases/{case_id}/comments/{comment_id}")
def delete_case_comment(case_id: int, comment_id: int, db: Session = Depends(get_db)):
    from app.comments import delete_comment

    return delete_comment(db, case_id, comment_id)


# --------------- static / spa ---------------

if FILES_DIR.exists():
    app.mount("/files", StaticFiles(directory=str(FILES_DIR)), name="files")


@app.get("/{full_path:path}")
def spa_or_static(full_path: str):
    if full_path.startswith("api/") or full_path.startswith("files/"):
        raise HTTPException(404, "not found")
    dist = FRONTEND_DIST
    if dist.is_dir():
        candidate = (dist / full_path).resolve()
        if str(candidate).startswith(str(dist.resolve())) and candidate.is_file():
            return FileResponse(candidate)
        index = dist / "index.html"
        if index.is_file():
            return FileResponse(index)
    return HTMLResponse(
        "<h1>测谱前端尚未构建</h1><p>请在 frontend 目录执行 npm install && npm run build</p>",
        status_code=200,
    )
