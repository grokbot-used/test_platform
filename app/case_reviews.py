"""Case + endpoint review records, JSON CRUD, and report-link migration."""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.case_fingerprint import fingerprint_from_version
from app.comments import _fmt_dt
from app.models import (
    CaseComment,
    CaseReview,
    Report,
    ReportCaseLink,
    ReportVersion,
    TestCase,
    TestCaseVersion,
)
from app.parsers import REVIEW_CARD_CSS, build_fragment_page, build_review_detail_view
from app.reviews import ENDPOINT_LABELS, ENDPOINTS, RESULT_LABELS, classify_report_endpoints, version_key

log = logging.getLogger(__name__)

REVIEW_REPORT_TYPES = frozenset({"frontend_review", "backend_review"})
VALID_ENDPOINTS = frozenset(ENDPOINT_LABELS)
FAIL_FILTER_ENDPOINTS = ("backend", "web", "android", "ios")
REVIEW_FILTER_ENDPOINTS = FAIL_FILTER_ENDPOINTS
REVIEW_FILTER_RESULTS = ("pass", "fail", "skip")
VALID_RESULTS = frozenset({"pass", "fail", "skip", "blocked", "untested", ""})
EMPTY_MESSAGE = "当前用例暂无{label}推演结果"


def next_review_version(existing: list[str] | set[str] | None) -> str:
    versions = [v for v in (existing or []) if v]
    if not versions:
        return "v0.0.1"
    latest = max(versions, key=version_key)
    parts = [int(x) for x in re.findall(r"\d+", latest)] or [0, 0, 0]
    while len(parts) < 3:
        parts.append(0)
    parts[-1] += 1
    return "v" + ".".join(str(p) for p in parts)


def normalize_result(value: str | None, *, required: bool = False) -> str:
    if value is None:
        if required:
            raise HTTPException(400, "缺少推演结果")
        return ""
    text = str(value).strip()
    if text not in VALID_RESULTS:
        raise HTTPException(400, "未知的推演结果")
    return text


def normalize_endpoint(value: str | None) -> str:
    text = (value or "").strip()
    if text not in VALID_ENDPOINTS:
        raise HTTPException(400, "未知端")
    return text



def _normalize_filter_values(values, allowed: tuple[str, ...], unknown_msg: str) -> list[str]:
    if not values or not isinstance(values, (list, tuple, str, set)):
        return []
    if isinstance(values, str):
        values = [values]
    raw: list[str] = []
    for item in values:
        for part in str(item).split(","):
            part = part.strip()
            if part:
                raw.append(part)
    out: list[str] = []
    seen: set[str] = set()
    for value in raw:
        if value not in allowed:
            raise HTTPException(400, unknown_msg)
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def normalize_review_endpoints(values) -> list[str]:
    return _normalize_filter_values(values, REVIEW_FILTER_ENDPOINTS, "未知端")


def normalize_review_results(values) -> list[str]:
    return _normalize_filter_values(values, REVIEW_FILTER_RESULTS, "未知的推演结果")


def normalize_fail_endpoints(values) -> list[str]:
    return normalize_review_endpoints(values)


def filter_cases_by_review(
    db: Session,
    case_ids: list[int],
    endpoints: list[str] | None = None,
    results: list[str] | None = None,
) -> set[int]:
    """Cases whose latest review matches any selected endpoint and any selected result.

    Empty endpoints means all four ends; empty results means any recorded result.
    Within each list the match is OR; the two lists are AND.
    """
    endpoints = list(endpoints or [])
    results = list(results or [])
    if not case_ids or (not endpoints and not results):
        return set()
    best = latest_review_map(db, case_ids)
    ends = endpoints or list(REVIEW_FILTER_ENDPOINTS)
    allowed = set(results) if results else None
    matched: set[int] = set()
    for case_id in case_ids:
        for endpoint in ends:
            row = best.get((case_id, endpoint))
            if row is None:
                continue
            if allowed is None or (row.result or "") in allowed:
                matched.add(case_id)
                break
    return matched


def filter_cases_by_endpoint_fail(db: Session, case_ids: list[int], endpoints: list[str]) -> set[int]:
    return filter_cases_by_review(db, case_ids, endpoints=endpoints, results=["fail"])


def filter_cases_by_stale_review(db: Session, case_ids: list[int]) -> set[int]:
    """Cases whose latest review on any endpoint shows the stale (失真) warning."""
    if not case_ids:
        return set()
    best = latest_review_map(db, case_ids)
    current = current_fingerprints_by_case(db, case_ids)
    matched: set[int] = set()
    for case_id in case_ids:
        current_fp = current.get(case_id, "")
        for endpoint in FAIL_FILTER_ENDPOINTS:
            row = best.get((case_id, endpoint))
            if row is not None and is_review_stale(row, current_fp, case=row.case):
                matched.add(case_id)
                break
    return matched


def _fields_json(fields) -> str:
    if fields is None:
        return "[]"
    if not isinstance(fields, list):
        raise HTTPException(400, "fields 须为数组")
    return json.dumps(fields, ensure_ascii=False)


def _load_fields(raw: str | None) -> list:
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _resolve_case_version(db: Session, case_id: int, version: str) -> tuple[TestCase, TestCaseVersion]:
    case = db.get(TestCase, case_id)
    if not case:
        raise HTTPException(404, "用例不存在")
    cv = (
        db.query(TestCaseVersion)
        .filter_by(case_id=case.id, version=version)
        .one_or_none()
    )
    if not cv:
        raise HTTPException(404, "该用例版本不存在")
    return case, cv


def _payload_body(row: CaseReview, case_key: str, fallback_title: str = "") -> dict:
    fields = _load_fields(row.fields_json)
    result = row.result or ""
    result_label = RESULT_LABELS.get(result, result or "未记录") if result else ""
    section_html, fields, heading = build_review_detail_view(
        row.section_html or "",
        fields,
        heading=row.heading or "",
        text=row.detail_text or "",
        result=result,
        result_label=result_label,
        fallback_title=fallback_title or "",
    )
    css_parts = [part for part in ((row.style_css or "").strip(), REVIEW_CARD_CSS.strip()) if part]
    return {
        "heading": heading,
        "fields": fields,
        "html": section_html,
        "fragment_page": build_fragment_page(section_html, "\n".join(css_parts), title=heading or case_key),
        "text": row.detail_text or "",
        "repo": row.repo or "",
        "branch": row.branch or "",
        "participants": row.participants or "",
        "style_css": row.style_css or "",
    }


def _naive(dt):
    if dt is None:
        return None
    if getattr(dt, "tzinfo", None) is not None:
        return dt.replace(tzinfo=None)
    return dt


def _as_dt(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return _naive(value)
    if isinstance(value, str):
        raw = value.strip().replace("Z", "")
        if not raw:
            return None
        try:
            return _naive(datetime.fromisoformat(raw))
        except ValueError:
            return None
    return None


def latest_versions_by_case(db: Session, case_ids: list[int]) -> dict[int, TestCaseVersion]:
    if not case_ids:
        return {}
    cases = db.query(TestCase).filter(TestCase.id.in_(case_ids)).all()
    versions = (
        db.query(TestCaseVersion)
        .filter(TestCaseVersion.case_id.in_(case_ids))
        .all()
    )
    by_case: dict[int, list[TestCaseVersion]] = {}
    for row in versions:
        by_case.setdefault(row.case_id, []).append(row)
    latest: dict[int, TestCaseVersion] = {}
    case_map = {case.id: case for case in cases}
    for cid, rows in by_case.items():
        case = case_map.get(cid)
        if case and case.latest_version:
            match = next((row for row in rows if row.version == case.latest_version), None)
            if match is not None:
                latest[cid] = match
                continue
        latest[cid] = max(rows, key=lambda row: (version_key(row.version), row.id))
    return latest


def current_fingerprints_by_case(db: Session, case_ids: list[int]) -> dict[int, str]:
    return {
        cid: fingerprint_from_version(cv)
        for cid, cv in latest_versions_by_case(db, case_ids).items()
    }


def _fingerprint_for_case(case: TestCase | None) -> str:
    if case is None:
        return ""
    versions = list(getattr(case, "versions", None) or [])
    if not versions:
        return ""
    if case.latest_version:
        match = next((row for row in versions if row.version == case.latest_version), None)
        if match is not None:
            return fingerprint_from_version(match)
    return fingerprint_from_version(max(versions, key=lambda row: (version_key(row.version), row.id)))


def is_review_stale(
    review: CaseReview | None,
    current_fingerprint: str | None = None,
    *,
    case=None,
    latest_cv: TestCaseVersion | None = None,
) -> bool:
    """True when the review has a stored fingerprint that differs from the latest case content."""
    if review is None:
        return False
    stored = (getattr(review, "content_fingerprint", None) or "").strip()
    if not stored:
        return False
    current = (current_fingerprint or "").strip()
    if not current and latest_cv is not None:
        current = fingerprint_from_version(latest_cv)
    if not current:
        current = _fingerprint_for_case(case if case is not None else getattr(review, "case", None))
    if not current:
        return False
    return stored != current


def _case_updated_at(case) -> str:
    if case is None:
        return ""
    return _fmt_dt(getattr(case, "updated_at", None))


def review_out(row: CaseReview, *, include_body: bool = True, current_fingerprint: str | None = None) -> dict:
    case = row.case
    cv = row.case_version
    case_key = case.key if case else ""
    case_version = cv.version if cv else ""
    result = row.result or ""
    item = {
        "id": row.id,
        "case_id": row.case_id,
        "case_key": case_key,
        "case_version": case_version,
        "latest_version": case.latest_version if case else "",
        "case_title": cv.title if cv else "",
        "case_client": cv.client if cv else "",
        "endpoint": row.endpoint,
        "label": ENDPOINT_LABELS.get(row.endpoint, row.endpoint),
        "version": row.version,
        "result": result,
        "result_label": RESULT_LABELS.get(result, result or "未记录"),
        "created_at": _fmt_dt(row.created_at),
        "case_updated_at": _case_updated_at(case),
        "stale": is_review_stale(row, current_fingerprint, case=case),
    }
    if include_body:
        item.update(_payload_body(row, case_key, fallback_title=cv.title if cv else ""))
    return item


def review_history_item(row: CaseReview, current_fingerprint: str | None = None) -> dict:
    result = row.result or ""
    return {
        "id": row.id,
        "version": row.version,
        "result": result,
        "result_label": RESULT_LABELS.get(result, result or "未记录"),
        "created_at": _fmt_dt(row.created_at),
        "case_updated_at": _case_updated_at(row.case),
        "latest_version": row.case.latest_version if row.case else "",
        "stale": is_review_stale(row, current_fingerprint, case=row.case),
    }


def _ordered_reviews(rows: list[CaseReview], *, descending: bool = True) -> list[CaseReview]:
    return sorted(
        rows,
        key=lambda row: (version_key(row.version), row.id),
        reverse=descending,
    )


def list_reviews(
    db: Session,
    case_id: int | None,
    case_version: str | None = None,
    endpoint: str | None = None,
) -> dict:
    if not case_id:
        raise HTTPException(400, "case_id 必填")
    case = db.get(TestCase, int(case_id))
    if not case:
        raise HTTPException(404, "用例不存在")
    query = db.query(CaseReview).options(
        joinedload(CaseReview.case),
        joinedload(CaseReview.case_version),
    ).filter_by(case_id=case.id)
    if endpoint:
        query = query.filter_by(endpoint=normalize_endpoint(endpoint))
    rows = _ordered_reviews(query.all(), descending=True)
    current_fp = current_fingerprints_by_case(db, [case.id]).get(case.id, "")
    return {
        "case_id": case.id,
        "case_key": case.key,
        "case_version": (case_version or "").strip(),
        "case_updated_at": _case_updated_at(case),
        "endpoint": endpoint or "",
        "items": [review_out(row, include_body=False, current_fingerprint=current_fp) for row in rows],
    }


def get_review(db: Session, review_id: int) -> dict:
    row = (
        db.query(CaseReview)
        .options(joinedload(CaseReview.case), joinedload(CaseReview.case_version))
        .filter_by(id=review_id)
        .one_or_none()
    )
    if not row:
        raise HTTPException(404, "推演记录不存在")
    current_fp = current_fingerprints_by_case(db, [row.case_id]).get(row.case_id, "")
    return review_out(row, include_body=True, current_fingerprint=current_fp)


def _existing_versions(db: Session, case_id: int, endpoint: str) -> list[str]:
    rows = (
        db.query(CaseReview.version)
        .filter_by(case_id=case_id, endpoint=endpoint)
        .all()
    )
    return [r[0] for r in rows if r[0]]


def create_review(db: Session, body: dict) -> dict:
    case_id = body.get("case_id")
    if not case_id:
        raise HTTPException(400, "case_id 必填")
    endpoint = normalize_endpoint(body.get("endpoint"))
    case = db.get(TestCase, int(case_id))
    if not case:
        raise HTTPException(404, "用例不存在")
    version = (body.get("version") or "").strip()
    if not version:
        version = next_review_version(_existing_versions(db, case.id, endpoint))
    else:
        clash = (
            db.query(CaseReview.id)
            .filter_by(case_id=case.id, endpoint=endpoint, version=version)
            .first()
        )
        if clash:
            raise HTTPException(409, "该推演版本已存在，请改用 PATCH /api/reviews/{id}")
    row = CaseReview(
        case_id=case.id,
        case_version_id=None,
        endpoint=endpoint,
        version=version,
        result=normalize_result(body.get("result")),
        heading=body.get("heading") or "",
        fields_json=_fields_json(body.get("fields")),
        section_html=body.get("html") or "",
        detail_text=body.get("text") or "",
        repo=body.get("repo") or "",
        branch=body.get("branch") or "",
        participants=body.get("participants") or "",
        style_css=body.get("style_css") or "",
        content_fingerprint=fingerprint_from_version(
            latest_versions_by_case(db, [case.id]).get(case.id)
        ),
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "该推演版本已存在，请改用 PATCH /api/reviews/{id}") from None
    db.refresh(row)
    row = (
        db.query(CaseReview)
        .options(joinedload(CaseReview.case), joinedload(CaseReview.case_version))
        .filter_by(id=row.id)
        .one()
    )
    return review_out(row, include_body=True)


def patch_review(db: Session, review_id: int, body: dict) -> dict:
    row = db.get(CaseReview, review_id)
    if not row:
        raise HTTPException(404, "推演记录不存在")
    if "result" in body:
        row.result = normalize_result(body.get("result"))
    if "heading" in body:
        row.heading = body.get("heading") or ""
    if "fields" in body:
        row.fields_json = _fields_json(body.get("fields"))
    if "html" in body:
        row.section_html = body.get("html") or ""
    if "text" in body:
        row.detail_text = body.get("text") or ""
    if "repo" in body:
        row.repo = body.get("repo") or ""
    if "branch" in body:
        row.branch = body.get("branch") or ""
    if "participants" in body:
        row.participants = body.get("participants") or ""
    if "style_css" in body:
        row.style_css = body.get("style_css") or ""
    db.commit()
    row = (
        db.query(CaseReview)
        .options(joinedload(CaseReview.case), joinedload(CaseReview.case_version))
        .filter_by(id=row.id)
        .one()
    )
    return review_out(row, include_body=True)


def delete_review(db: Session, review_id: int) -> dict:
    row = db.get(CaseReview, review_id)
    if not row:
        raise HTTPException(404, "推演记录不存在")
    case_id = row.case_id
    db.delete(row)
    db.commit()
    return {"ok": True, "id": review_id, "case_id": case_id}


def reviews_for_case(
    db: Session,
    case_id: int,
    endpoint: str | None = None,
) -> list[CaseReview]:
    query = (
        db.query(CaseReview)
        .options(joinedload(CaseReview.case), joinedload(CaseReview.case_version))
        .filter_by(case_id=case_id)
    )
    if endpoint:
        query = query.filter_by(endpoint=endpoint)
    return _ordered_reviews(query.all(), descending=True)


def latest_review_map(
    db: Session,
    case_ids: list[int],
) -> dict[tuple[int, str], CaseReview]:
    if not case_ids:
        return {}
    rows = (
        db.query(CaseReview)
        .options(joinedload(CaseReview.case), joinedload(CaseReview.case_version))
        .filter(CaseReview.case_id.in_(case_ids))
        .all()
    )
    best: dict[tuple[int, str], CaseReview] = {}
    for row in rows:
        key = (row.case_id, row.endpoint)
        cur = best.get(key)
        if cur is None or version_key(row.version) > version_key(cur.version) or (
            version_key(row.version) == version_key(cur.version) and row.id > cur.id
        ):
            best[key] = row
    return best


def latest_reviews_for_case(db: Session, case_id: int) -> list[dict]:
    case = db.get(TestCase, case_id)
    if not case:
        return [_empty_endpoint(spec["id"]) for spec in ENDPOINTS]
    best = latest_review_map(db, [case_id])
    current_fp = current_fingerprints_by_case(db, [case_id]).get(case_id, "")
    out = []
    for spec in ENDPOINTS:
        row = best.get((case_id, spec["id"]))
        out.append(_endpoint_from_review(spec["id"], row, current_fingerprint=current_fp))
    return out


def latest_reviews_for_case_version(db: Session, case_id: int, case_version: str | None = None) -> list[dict]:
    # case_version is ignored; kept so older callers still import this name.
    return latest_reviews_for_case(db, case_id)


def _empty_endpoint(endpoint: str) -> dict:
    return {
        "endpoint": endpoint,
        "label": ENDPOINT_LABELS.get(endpoint, endpoint),
        "available": False,
        "review_id": None,
        "version": None,
        "result": "",
        "result_label": "暂无",
        "found": False,
        "stale": False,
        "created_at": "",
        "case_updated_at": "",
        "latest_version": "",
    }


def _endpoint_from_review(endpoint: str, row: CaseReview | None, current_fingerprint: str | None = None) -> dict:
    if row is None:
        return _empty_endpoint(endpoint)
    result = row.result or ""
    case = row.case
    return {
        "endpoint": endpoint,
        "label": ENDPOINT_LABELS.get(endpoint, endpoint),
        "available": True,
        "review_id": row.id,
        "version": row.version,
        "result": result,
        "result_label": RESULT_LABELS.get(result, result or "未记录"),
        "found": True,
        "stale": is_review_stale(row, current_fingerprint, case=case),
        "created_at": _fmt_dt(row.created_at),
        "case_updated_at": _case_updated_at(case),
        "latest_version": case.latest_version if case else "",
    }


def case_endpoint_results(
    db: Session,
    product_id: int,
    case_version: str | None,
    case_ids: list[int],
) -> dict[int, list[dict]]:
    if not case_ids:
        return {}
    best = latest_review_map(db, case_ids)
    fps = current_fingerprints_by_case(db, case_ids)
    out: dict[int, list[dict]] = {}
    for cid in case_ids:
        fp = fps.get(cid, "")
        out[cid] = [
            _endpoint_from_review(spec["id"], best.get((cid, spec["id"])), current_fingerprint=fp)
            for spec in ENDPOINTS
        ]
    return out


def review_entries(db: Session, product_id: int, case_version: str | None = None) -> dict:
    case_ids = [
        r[0]
        for r in db.query(TestCase.id).filter(TestCase.product_id == product_id).all()
    ]
    best = latest_review_map(db, case_ids)
    by_ep: dict[str, CaseReview] = {}
    for (_cid, endpoint), row in best.items():
        cur = by_ep.get(endpoint)
        if cur is None or version_key(row.version) > version_key(cur.version) or (
            version_key(row.version) == version_key(cur.version) and row.id > cur.id
        ):
            by_ep[endpoint] = row
    fps = current_fingerprints_by_case(db, case_ids)
    return {
        "product_id": product_id,
        "case_version": case_version or "",
        "endpoints": {
            spec["id"]: _endpoint_from_review(
                spec["id"],
                by_ep.get(spec["id"]),
                current_fingerprint=fps.get(by_ep[spec["id"]].case_id, "") if spec["id"] in by_ep else "",
            )
            for spec in ENDPOINTS
        },
    }


def review_detail(
    db: Session,
    product_id: int,
    endpoint: str,
    case_id: int,
    case_version: str | None = None,
    review_id: int | None = None,
    review_version: str | None = None,
) -> dict:
    if endpoint not in ENDPOINT_LABELS:
        return {"available": False, "error": "未知端"}
    case = db.get(TestCase, case_id)
    if not case or case.product_id != product_id:
        return {"available": False, "error": "用例不存在"}
    wanted = (case_version or "").strip()
    cv = None
    if wanted:
        cv = (
            db.query(TestCaseVersion)
            .filter_by(case_id=case.id, version=wanted)
            .one_or_none()
        )
    if cv is None:
        cv = (
            db.query(TestCaseVersion)
            .filter_by(case_id=case.id, version=case.latest_version)
            .one_or_none()
        )
    history = reviews_for_case(db, case.id, endpoint)
    chosen: CaseReview | None = None
    if review_id:
        chosen = next((row for row in history if row.id == review_id), None)
        if chosen is None:
            return {"available": False, "error": "推演记录不存在"}
    elif review_version:
        want = review_version.strip()
        chosen = next((row for row in history if row.version == want), None)
        if chosen is None:
            return {"available": False, "error": "推演记录不存在"}
    elif history:
        chosen = history[0]

    current_fp = current_fingerprints_by_case(db, [case.id]).get(case.id, "")
    base = {
        **_endpoint_from_review(endpoint, chosen, current_fingerprint=current_fp),
        "id": chosen.id if chosen else None,
        "case_id": case.id,
        "case_key": case.key,
        "case_title": cv.title if cv else "",
        "case_client": cv.client if cv else "",
        "case_version": cv.version if cv else (case_version or ""),
        "latest_version": case.latest_version or "",
        "case_updated_at": _case_updated_at(case),
        "stale": is_review_stale(chosen, current_fp, case=case),
        "heading": "",
        "fields": [],
        "html": "",
        "fragment_page": "",
        "text": "",
        "found": bool(chosen),
        "message": "",
        "repo": "",
        "branch": "",
        "participants": "",
        "created_at": "",
        "reviews": [review_history_item(row, current_fp) for row in history],
    }
    if chosen is None:
        base["available"] = False
        base["result_label"] = "暂无"
        base["message"] = EMPTY_MESSAGE.format(label=ENDPOINT_LABELS[endpoint])
        return base

    body = _payload_body(chosen, case.key, fallback_title=(cv.title if cv else ""))
    base.update(body)
    base["found"] = bool(body.get("html") or body.get("text") or body.get("fields"))
    base["created_at"] = _fmt_dt(chosen.created_at)
    if not base["found"]:
        base["message"] = "该条推演没有详情内容"
    return base


def _resolve_migration_case_version(
    db: Session,
    link: ReportCaseLink,
    rv: ReportVersion,
    cv_cache: dict[tuple[int, str], TestCaseVersion | None],
) -> TestCaseVersion | None:
    """Prefer the report's based_on case version when it resolves.

    Many legacy links stored case_version_id equal to the *report* version
    (e.g. v1.0.0) rather than the case baseline the current UI uses
    (based_on_case_version, e.g. v1.0.6). Using the link id blindly would
    hide reviews from the case versions users actually open.
    """
    target = (rv.based_on_case_version or "").strip()
    if target:
        key = (link.case_id, target)
        if key not in cv_cache:
            cv_cache[key] = (
                db.query(TestCaseVersion)
                .filter_by(case_id=link.case_id, version=target)
                .one_or_none()
            )
        if cv_cache[key] is not None:
            return cv_cache[key]
    if link.case_version_id:
        if link.case_version is not None:
            return link.case_version
        return db.get(TestCaseVersion, link.case_version_id)
    return None


def migrate_review_reports(db: Session) -> dict:
    """Copy frontend/backend review links into case_reviews. Idempotent."""
    existing = {
        (row.source_link_id, row.endpoint)
        for row in db.query(CaseReview.source_link_id, CaseReview.endpoint)
        .filter(CaseReview.source_link_id.isnot(None))
        .all()
    }
    rows = (
        db.query(ReportCaseLink)
        .options(
            joinedload(ReportCaseLink.report_version).joinedload(ReportVersion.report),
            joinedload(ReportCaseLink.case_version),
            joinedload(ReportCaseLink.case),
        )
        .join(ReportVersion, ReportCaseLink.report_version_id == ReportVersion.id)
        .join(Report, ReportVersion.report_id == Report.id)
        .filter(Report.type.in_(tuple(REVIEW_REPORT_TYPES)))
        .all()
    )

    pending: list[tuple[int, int, str, ReportCaseLink, ReportVersion]] = []
    skipped = 0
    skipped_no_endpoint = 0
    skipped_no_case_version = 0
    already = 0
    cv_cache: dict[tuple[int, str], TestCaseVersion | None] = {}

    for link in rows:
        rv = link.report_version
        report = rv.report if rv else None
        if rv is None or report is None:
            skipped += 1
            log.info("skip review link %s: missing report version", link.id)
            continue
        ends = classify_report_endpoints(report.title, report.type, rv.source_file or "")
        if not ends:
            skipped += 1
            skipped_no_endpoint += 1
            log.info("skip review link %s: no endpoint for %s", link.id, report.title)
            continue
        cv = _resolve_migration_case_version(db, link, rv, cv_cache)
        if cv is None:
            skipped += 1
            skipped_no_case_version += 1
            log.info(
                "skip review link %s: cannot resolve case version (case_id=%s based_on=%s)",
                link.id,
                link.case_id,
                rv.based_on_case_version,
            )
            continue
        for endpoint in ends:
            if (link.id, endpoint) in existing:
                already += 1
                continue
            pending.append((link.case_id, cv.id, endpoint, link, rv))

    groups: dict[tuple[int, str], list[tuple[int, ReportCaseLink, ReportVersion]]] = defaultdict(list)
    for case_id, cv_id, endpoint, link, rv in pending:
        groups[(case_id, endpoint)].append((cv_id, link, rv))

    existing_versions: dict[tuple[int, str], list[str]] = defaultdict(list)
    if groups:
        group_case_ids = {case_id for case_id, _ in groups}
        for row in (
            db.query(CaseReview.case_id, CaseReview.endpoint, CaseReview.version)
            .filter(CaseReview.case_id.in_(group_case_ids))
            .all()
        ):
            existing_versions[(row.case_id, row.endpoint)].append(row.version)

    inserted = 0
    for (case_id, endpoint), items in groups.items():
        items.sort(
            key=lambda it: (
                it[2].created_at or datetime.min,
                version_key(it[2].version or ""),
                it[1].id,
            )
        )
        versions = list(existing_versions[(case_id, endpoint)])
        for cv_id, link, rv in items:
            version = next_review_version(versions)
            versions.append(version)
            created = rv.created_at or datetime.now(timezone.utc).replace(tzinfo=None)
            row = CaseReview(
                case_id=link.case_id,
                case_version_id=cv_id,
                endpoint=endpoint,
                version=version,
                result=link.result or "",
                heading=link.heading or "",
                fields_json=link.fields_json or "[]",
                section_html=link.section_html or "",
                detail_text=link.detail_text or "",
                repo=rv.repo or "",
                branch=rv.branch or "",
                participants=rv.participants or "",
                style_css=rv.style_css or "",
                source_report_version_id=rv.id,
                source_link_id=link.id,
                content_fingerprint=fingerprint_from_version(db.get(TestCaseVersion, cv_id)),
                created_at=created,
            )
            db.add(row)
            inserted += 1
            existing.add((link.id, endpoint))
        existing_versions[(case_id, endpoint)] = versions

    if inserted:
        db.commit()
    else:
        db.flush()

    stats = {
        "inserted": inserted,
        "skipped": skipped,
        "skipped_no_endpoint": skipped_no_endpoint,
        "skipped_no_case_version": skipped_no_case_version,
        "already": already,
        "source_links": len(rows),
        "pending_groups": len(groups),
    }
    log.info("migrate_review_reports %s", stats)
    return stats


def _pick_backfill_version(
    review: CaseReview,
    versions_by_id: dict[int, TestCaseVersion],
    versions_by_case: dict[int, list[TestCaseVersion]],
) -> TestCaseVersion | None:
    """Choose the case version that represented the case when the review was written."""
    if review.case_version_id and review.case_version_id in versions_by_id:
        return versions_by_id[review.case_version_id]
    versions = list(versions_by_case.get(review.case_id) or [])
    created = _as_dt(review.created_at)
    if created is not None:
        eligible = [row for row in versions if _as_dt(row.created_at) is not None and _as_dt(row.created_at) <= created]
        if eligible:
            return max(eligible, key=lambda row: (_as_dt(row.created_at), version_key(row.version), row.id))
    if versions:
        return min(
            versions,
            key=lambda row: (_as_dt(row.created_at) or datetime.max, version_key(row.version), row.id),
        )
    return None


def backfill_review_fingerprints(db: Session | None = None) -> dict:
    """Fill empty content_fingerprint values. Idempotent; never rewrites a stored hash."""
    from app.db import SessionLocal, _backup_sqlite, ensure_review_fingerprint_column

    ensure_review_fingerprint_column()
    owns = db is None
    session = db or SessionLocal()
    try:
        missing = (
            session.query(CaseReview)
            .filter(
                (CaseReview.content_fingerprint.is_(None))
                | (CaseReview.content_fingerprint == "")
            )
            .all()
        )
        if not missing:
            filled = 0
            already = session.query(CaseReview).filter(CaseReview.content_fingerprint != "").count()
            skipped = 0
        else:
            if owns:
                _backup_sqlite("review-fingerprints")
            case_ids = {row.case_id for row in missing}
            versions = (
                session.query(TestCaseVersion)
                .filter(TestCaseVersion.case_id.in_(case_ids))
                .all()
            )
            versions_by_id = {row.id: row for row in versions}
            versions_by_case: dict[int, list[TestCaseVersion]] = {}
            for row in versions:
                versions_by_case.setdefault(row.case_id, []).append(row)
            filled = 0
            skipped = 0
            for review in missing:
                source = _pick_backfill_version(review, versions_by_id, versions_by_case)
                if source is None:
                    skipped += 1
                    continue
                review.content_fingerprint = fingerprint_from_version(source)
                filled += 1
            session.commit()
            already = session.query(CaseReview).count() - filled - skipped

        # Stale counts vs the latest case content, for migration reporting.
        all_rows = session.query(CaseReview).all()
        fps = current_fingerprints_by_case(session, list({row.case_id for row in all_rows}))
        stale = 0
        fresh = 0
        empty = 0
        for review in all_rows:
            stored = (review.content_fingerprint or "").strip()
            if not stored:
                empty += 1
                continue
            if stored != fps.get(review.case_id, ""):
                stale += 1
            else:
                fresh += 1
        stats = {
            "filled": filled,
            "already": already,
            "skipped_no_version": skipped,
            "total": len(all_rows),
            "stale": stale,
            "not_stale": fresh,
            "empty": empty,
        }
        return stats
    finally:
        if owns:
            session.close()
