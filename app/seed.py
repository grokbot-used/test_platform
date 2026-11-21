"""Copy official sources and seed the SQLite database. Safe to re-run (rebuilds official data)."""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

from sqlalchemy.orm import Session

# Allow `python -m app.seed` from repo root
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import DATA_DIR, DB_PATH, FILES_DIR, SOURCES_DIR  # noqa: E402
from app.db import SessionLocal, engine, init_db, touch_case  # noqa: E402
from app.models import (  # noqa: E402
    Base,
    Product,
    Report,
    ReportCaseLink,
    ReportVersion,
    TestCase,
    TestCaseVersion,
)
from app.parsers import infer_based_on_case_version, parse_file, version_from_html  # noqa: E402

WORKSPACE = Path("/workspace")

CATALOG = [
    {
        "slug": "price-openapi",
        "name": "价格管控 OpenAPI",
        "key_prefix": "TC-OPA",
        "src": WORKSPACE / "price-openapi",
        "cases": [
            "价格管控OpenAPI兼容-黑盒用例_v1.0.0.html",
            "黑盒测试用例_价格管控OpenAPI_v1.0.1.html",
            "黑盒测试用例_价格管控OpenAPI_v1.0.2.html",
            "黑盒测试用例_价格管控OpenAPI_v1.0.3.html",
            "黑盒测试用例_价格管控OpenAPI_v1.0.4.html",
            "黑盒测试用例_价格管控OpenAPI_v1.0.5.html",
            "黑盒测试用例_价格管控OpenAPI_v1.0.6.html",
        ],
        "reports": [
            ("黑盒测试报告_价格管控OpenAPI_P1_20261104.html", "黑盒测试报告 · P1", "blackbox"),
            ("黑盒测试报告_价格管控OpenAPI_P2_v1.0.0.html", "黑盒测试报告 · P2", "blackbox"),
            ("黑盒测试报告_价格管控OpenAPI_P2_v1.0.1.html", "黑盒测试报告 · P2", "blackbox"),
            ("黑盒测试报告_价格管控OpenAPI_P2_v1.0.2.html", "黑盒测试报告 · P2", "blackbox"),
            ("黑盒测试报告_价格管控OpenAPI_P2_v1.0.3.html", "黑盒测试报告 · P2", "blackbox"),
            ("黑盒测试报告_价格管控OpenAPI_P2_v1.0.4.html", "黑盒测试报告 · P2", "blackbox"),
            ("黑盒测试报告_价格管控OpenAPI_P1P2_最终_v1.0.0.html", "黑盒测试报告 · P1+P2 最终整合", "blackbox"),
            ("前端静态推演_价格管控OpenAPI_v1.0.0.html", "前端静态推演", "frontend_review"),
            ("前端静态推演_价格管控OpenAPI_v1.0.1.html", "前端静态推演", "frontend_review"),
            ("前端静态推演_价格管控OpenAPI_v1.0.2.html", "前端静态推演", "frontend_review"),
            ("后端静态推演_价格管控OpenAPI_v1.0.0.html", "后端静态推演", "backend_review"),
            ("后端静态推演_价格管控OpenAPI_v1.0.1.html", "后端静态推演", "backend_review"),
        ],
    },
    {
        "slug": "global-model",
        "name": "全球型号接入",
        "key_prefix": "TC-GMA",
        "src": WORKSPACE / "global-model",
        "cases": [
            "黑盒测试用例_全球型号接入_v1.0.0.html",
            "黑盒测试用例_全球型号接入_v1.0.1.html",
            "黑盒测试用例_全球型号接入_v1.0.2.html",
            "黑盒测试用例_全球型号接入_v1.0.3.html",
            "黑盒测试用例_全球型号接入_v1.0.4.html",
            "黑盒测试用例_全球型号接入_v1.0.6.html",
        ],
        "reports": [
            ("前端静态推演_全球型号接入_v1.0.0.html", "前端静态推演", "frontend_review"),
            ("前端静态推演_全球型号接入_v1.0.1.html", "前端静态推演", "frontend_review"),
            ("前端静态推演_全球型号接入_v1.0.2.html", "前端静态推演", "frontend_review"),
            ("前端静态推演_全球型号接入_v1.0.3.html", "前端静态推演", "frontend_review"),
            ("后端静态推演_全球型号接入_v1.0.0.html", "后端静态推演", "backend_review"),
            ("后端静态推演_全球型号接入_v1.0.1.html", "后端静态推演", "backend_review"),
            ("APP静态推演_全球型号接入_v1.0.0.html", "APP 静态推演", "frontend_review"),
            ("APP静态推演_全球型号接入_v1.0.1.html", "APP 静态推演", "frontend_review"),
            ("APP静态推演_全球型号接入_v1.0.2.html", "APP 静态推演", "frontend_review"),
            ("APP静态推演_全球型号接入_v1.0.3.html", "APP 静态推演", "frontend_review"),
            ("APP静态推演_全球型号接入_v1.0.4.html", "APP 静态推演", "frontend_review"),
        ],
    },
    {
        "slug": "r58l",
        "name": "R58L Pro Plus",
        "key_prefix": "TC-R58",
        "src": WORKSPACE / "r58l",
        "cases": [
            "R58L-pro-plus-黑盒用例表.html",
        ],
        "reports": [
            ("R58L-pro-plus-前端推演报告.html", "前端静态推演", "frontend_review"),
            ("R58L-pro-plus-后端推演报告.html", "后端静态推演", "backend_review"),
            ("R58L-pro-plus-白盒测试报告.md", "白盒测试报告", "whitebox"),
        ],
    },
    {
        "slug": "exdata-vin",
        "name": "exData-VIN",
        "key_prefix": "TC-EXD",
        "src": WORKSPACE / "rocketmq-exdata",
        "cases": [
            "exData脏数据过滤与TDengine消费兜底-黑盒用例.html",
        ],
        "reports": [
            ("exData-VIN-前端推演报告.html", "前端静态推演", "frontend_review"),
            ("exData-VIN-后端推演报告.html", "后端静态推演", "backend_review"),
            ("exData-VIN-后端推演报告-v2.5.3.html", "后端静态推演", "backend_review"),
            ("exData-VIN-后端推演报告-v3.0.html", "后端静态推演", "backend_review"),
            ("exData-VIN-黑盒测试报告.html", "黑盒测试报告", "blackbox"),
            ("exData-VIN-黑盒测试报告-v3.0.1.html", "黑盒测试报告", "blackbox"),
        ],
    },
    {
        "slug": "gt06-a5",
        "name": "GT06 A5 告警包定位解析",
        "key_prefix": "TC-A5",
        "src": WORKSPACE / "gt06-a5",
        "cases": [
            "黑盒测试用例_A5告警包定位解析_v1.0.0.html",
        ],
        "reports": [],
    },
]


def version_key(ver: str) -> tuple[int, ...]:
    parts = [int(x) for x in re.findall(r"\d+", ver or "")]
    return tuple(parts + [0] * (4 - len(parts)))


def bump_latest(current: str | None, incoming: str) -> str:
    if not current:
        return incoming
    return incoming if version_key(incoming) >= version_key(current) else current


def copy_official_sources() -> list[str]:
    """Copy catalog files into data/sources so the runtime is self-contained."""
    skipped: list[str] = []
    if SOURCES_DIR.exists():
        # Only clear product folders we manage
        for item in CATALOG:
            dest = SOURCES_DIR / item["slug"]
            if dest.exists():
                shutil.rmtree(dest)
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    for item in CATALOG:
        dest = SOURCES_DIR / item["slug"]
        dest.mkdir(parents=True, exist_ok=True)
        src_dir: Path = item["src"]
        names = list(item["cases"]) + [r[0] for r in item["reports"]]
        for name in names:
            src = src_dir / name
            if not src.is_file():
                skipped.append(f"missing: {src}")
                continue
            shutil.copy2(src, dest / name)
    return skipped


def store_file(src: Path, slug: str, kind: str) -> str:
    rel_dir = Path(slug) / kind
    dest_dir = FILES_DIR / rel_dir
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    if dest.resolve() != src.resolve():
        shutil.copy2(src, dest)
    return str(rel_dir / src.name).replace("\\", "/")


def get_or_create_product(db: Session, name: str, slug: str) -> Product:
    row = db.query(Product).filter_by(slug=slug).one_or_none()
    if row:
        row.name = name
        return row
    row = Product(name=name, slug=slug)
    db.add(row)
    db.flush()
    return row


def upsert_case_version(
    db: Session,
    product: Product,
    rec: dict,
    version: str,
    source_file: str,
) -> TestCaseVersion:
    case = (
        db.query(TestCase)
        .filter_by(product_id=product.id, key=rec["key"])
        .one_or_none()
    )
    if not case:
        case = TestCase(product_id=product.id, key=rec["key"], latest_version=version)
        db.add(case)
        db.flush()
    cv = (
        db.query(TestCaseVersion)
        .filter_by(case_id=case.id, version=version)
        .one_or_none()
    )
    fields = dict(
        title=rec.get("title") or "",
        module=rec.get("module") or "",
        priority=rec.get("priority") or "",
        client=rec.get("client") or "",
        description=rec.get("description") or "",
        preconditions=rec.get("preconditions") or "",
        steps=rec.get("steps") or "",
        expected=rec.get("expected") or "",
        source_file=source_file,
    )
    if cv:
        for k, v in fields.items():
            setattr(cv, k, v)
    else:
        cv = TestCaseVersion(case_id=case.id, version=version, **fields)
        db.add(cv)
        db.flush()
    case.latest_version = bump_latest(case.latest_version, version)
    touch_case(case)
    return cv


def upsert_report_version(
    db: Session,
    product: Product,
    title: str,
    rtype: str,
    version: str,
    summary: str,
    conclusion: str,
    source_file: str,
    based_on_case_version: str | None = None,
) -> ReportVersion:
    report = (
        db.query(Report)
        .filter_by(product_id=product.id, title=title, type=rtype)
        .one_or_none()
    )
    if not report:
        report = Report(
            product_id=product.id, title=title, type=rtype, latest_version=version
        )
        db.add(report)
        db.flush()
    rv = (
        db.query(ReportVersion)
        .filter_by(report_id=report.id, version=version)
        .one_or_none()
    )
    if rv:
        rv.summary = summary
        rv.conclusion = conclusion
        rv.source_file = source_file
        if based_on_case_version:
            rv.based_on_case_version = based_on_case_version
        # rebuild links for this version
        db.query(ReportCaseLink).filter_by(report_version_id=rv.id).delete()
    else:
        rv = ReportVersion(
            report_id=report.id,
            version=version,
            summary=summary,
            conclusion=conclusion,
            source_file=source_file,
            based_on_case_version=based_on_case_version,
        )
        db.add(rv)
        db.flush()
    report.latest_version = bump_latest(report.latest_version, version)
    return rv


def link_cases(
    db: Session,
    product: Product,
    rv: ReportVersion,
    links: list[dict],
) -> int:
    count = 0
    seen: set[int] = set()
    for item in links:
        key = item.get("key")
        if not key:
            continue
        case = (
            db.query(TestCase)
            .filter_by(product_id=product.id, key=key)
            .one_or_none()
        )
        if not case or case.id in seen:
            continue
        seen.add(case.id)
        target_ver = rv.based_on_case_version or rv.version
        cv = (
            db.query(TestCaseVersion)
            .filter_by(case_id=case.id, version=target_ver)
            .one_or_none()
        )
        if cv is None and rv.based_on_case_version and rv.version != rv.based_on_case_version:
            cv = (
                db.query(TestCaseVersion)
                .filter_by(case_id=case.id, version=rv.version)
                .one_or_none()
            )
        db.add(
            ReportCaseLink(
                report_version_id=rv.id,
                case_id=case.id,
                case_version_id=cv.id if cv else None,
                result=item.get("result") or "",
            )
        )
        count += 1
    return count


def reset_db():
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    Base.metadata.drop_all(bind=engine)
    if DB_PATH.exists():
        # drop_all already cleared tables; keep file
        pass
    init_db()


def seed(reset: bool = True) -> dict:
    missing_copy = copy_official_sources()
    if reset:
        reset_db()
    else:
        init_db()

    failed: list[str] = []
    db = SessionLocal()
    stats = {
        "products": 0,
        "cases": 0,
        "case_versions": 0,
        "reports": 0,
        "report_versions": 0,
        "links": 0,
        "failed": failed,
        "missing": missing_copy,
    }
    try:
        for item in CATALOG:
            product = get_or_create_product(db, item["name"], item["slug"])
            prefix = item["key_prefix"]
            src_root = SOURCES_DIR / item["slug"]

            for name in item["cases"]:
                path = src_root / name
                if not path.is_file():
                    failed.append(f"case missing after copy: {item['slug']}/{name}")
                    continue
                parsed = parse_file(path, key_prefix=prefix, kind="case")
                if not parsed.get("cases"):
                    failed.append(f"case parse empty: {name}")
                    continue
                stored = store_file(path, item["slug"], "cases")
                version = parsed["version"]
                for rec in parsed["cases"]:
                    upsert_case_version(db, product, rec, version, stored)
            db.flush()

            for name, title, rtype in item["reports"]:
                path = src_root / name
                if not path.is_file():
                    failed.append(f"report missing after copy: {item['slug']}/{name}")
                    continue
                parsed = parse_file(path, key_prefix=prefix, kind="report")
                stored = store_file(path, item["slug"], "reports")
                raw = path.read_text(encoding="utf-8", errors="replace")
                version = parsed.get("version") or version_from_html(raw, name)
                available = {
                    r[0]
                    for r in db.query(TestCaseVersion.version)
                    .join(TestCase)
                    .filter(TestCase.product_id == product.id)
                    .distinct()
                    .all()
                }
                from app.reviews import snap_to_available

                baseline = snap_to_available(infer_based_on_case_version(raw, name), available)
                if not baseline and len(available) == 1:
                    baseline = next(iter(available))
                elif not baseline and version in available:
                    baseline = version
                rv = upsert_report_version(
                    db,
                    product,
                    title=title,
                    rtype=rtype,
                    version=version,
                    summary=parsed.get("summary") or "",
                    conclusion=parsed.get("conclusion") or "",
                    source_file=stored,
                    based_on_case_version=baseline,
                )
                link_cases(db, product, rv, parsed.get("links") or [])
            db.commit()

        stats["products"] = db.query(Product).count()
        stats["cases"] = db.query(TestCase).count()
        stats["case_versions"] = db.query(TestCaseVersion).count()
        stats["reports"] = db.query(Report).count()
        stats["report_versions"] = db.query(ReportVersion).count()
        stats["links"] = db.query(ReportCaseLink).count()

        from sqlalchemy import func as sa_func

        multi_row = (
            db.query(TestCase.key, sa_func.count(TestCaseVersion.id))
            .join(TestCaseVersion)
            .group_by(TestCase.id)
            .having(sa_func.count(TestCaseVersion.id) > 1)
            .first()
        )
        linked = (
            db.query(ReportCaseLink)
            .join(ReportVersion)
            .join(Report)
            .join(TestCase, ReportCaseLink.case_id == TestCase.id)
            .first()
        )
        stats["spot_multi_case"] = (
            f"{multi_row[0]} x{multi_row[1]}" if multi_row else "NONE"
        )
        if linked:
            stats["spot_link"] = (
                f"{linked.case.key} ↔ report_version={linked.report_version_id} result={linked.result}"
            )
        else:
            stats["spot_link"] = "NONE"

        from app.review_store import backfill_review_details
        from app.case_doc_store import backfill_case_doc_metas

        stats["review_details"] = backfill_review_details(db)
        stats["case_docs"] = backfill_case_doc_metas(db)
    finally:
        db.close()
    return stats


def main():
    parser = argparse.ArgumentParser(description="Seed test platform database")
    parser.add_argument("--no-reset", action="store_true", help="Do not drop existing tables")
    args = parser.parse_args()
    stats = seed(reset=not args.no_reset)
    print("=== seed complete ===")
    print(f"products:        {stats['products']}")
    print(f"cases:           {stats['cases']}")
    print(f"case versions:   {stats['case_versions']}")
    print(f"reports:         {stats['reports']}")
    print(f"report versions: {stats['report_versions']}")
    print(f"links:           {stats['links']}")
    print(f"spot-check multi-version case: {stats['spot_multi_case']}")
    print(f"spot-check link: {stats['spot_link']}")
    if stats["missing"]:
        print("missing source files:")
        for line in stats["missing"]:
            print("  -", line)
    if stats["failed"]:
        print("parse/import issues:")
        for line in stats["failed"]:
            print("  -", line)
    if not (
        stats["products"]
        and stats["cases"]
        and stats["case_versions"]
        and stats["reports"]
        and stats["links"]
    ):
        print("ERROR: one or more core counts are 0", file=sys.stderr)
        sys.exit(1)
    if stats["spot_multi_case"] == "NONE" or stats["spot_link"] == "NONE":
        print("ERROR: spot-check failed", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
