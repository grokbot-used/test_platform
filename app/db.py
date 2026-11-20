import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import DATABASE_URL, DB_PATH

log = logging.getLogger(__name__)
LAST_RETARGET_STATS: dict = {}
LAST_FINGERPRINT_STATS: dict = {}


class Base(DeclarativeBase):
    pass


engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)


@event.listens_for(engine, "connect")
def _fk_on(dbapi_conn, _rec):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def now_utc_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def touch_case(case) -> None:
    case.updated_at = now_utc_naive()


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    migrate_schema()
    from app.parsers import repair_case_section_text, repair_misparsed_card_steps
    from app.case_reviews import migrate_review_reports

    session = SessionLocal()
    try:
        repair_misparsed_card_steps(session)
        repair_case_section_text(session)
        migrate_review_reports(session)
    finally:
        session.close()


def _backup_sqlite(reason: str) -> Path:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = Path(f"/tmp/platform.db.bak-{reason}-{ts}")
    src = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(dest)
        try:
            with dst:
                src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return dest


def _version_tuple(ver: str | None) -> tuple[int, ...]:
    parts = [int(x) for x in re.findall(r"\d+", ver or "")]
    return tuple(parts + [0] * (4 - len(parts)))


def plan_review_version_renumber(rows: list[dict]) -> list[dict]:
    """Renumber review versions per (case_id, endpoint).

    Sort by created_at asc, then the old version, then id, and assign
    v0.0.1, v0.0.2, … so merged histories stay chronological and unique.
    """
    from collections import defaultdict

    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        groups[(row["case_id"], row["endpoint"])].append(row)

    def sort_key(row: dict):
        created = row.get("created_at") or ""
        if isinstance(created, datetime):
            created_key = created.isoformat(sep=" ")
        else:
            created_key = str(created)
        return (created_key, _version_tuple(row.get("version")), row.get("id") or 0)

    out: list[dict] = []
    for key in groups:
        items = sorted(groups[key], key=sort_key)
        for index, row in enumerate(items, start=1):
            item = dict(row)
            item["version"] = f"v0.0.{index}"
            out.append(item)
    return out


def _row_sql(con) -> str:
    row = con.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='case_reviews'"
    ).fetchone()
    return row[0] if row and row[0] else ""


def _norm_sql(sql: str) -> str:
    return re.sub(r"\s+", "", sql or "").lower()


def case_reviews_needs_retarget(con) -> bool:
    sql = _row_sql(con)
    if not sql:
        return False
    compact = _norm_sql(sql)
    has_new = "unique(case_id,endpoint,version)" in compact
    has_old = "unique(case_version_id,endpoint,version)" in compact
    notnull = {}
    for row in con.execute("PRAGMA table_info(case_reviews)"):
        notnull[row[1]] = row[3]
    cv_not_null = notnull.get("case_version_id") == 1
    if has_old or cv_not_null:
        return True
    return not has_new


def retarget_case_reviews(db_path: Path | str | None = None) -> dict:
    """Rebuild case_reviews onto (case_id, endpoint, version) uniqueness.

    Keeps existing rows, leaves case_version_id as an optional lineage FK,
    and renumbers versions per (case_id, endpoint).
    """
    path = Path(db_path or DB_PATH)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    try:
        if not case_reviews_needs_retarget(con):
            return {"rebuilt": False, "rows": 0, "renumbered": 0, "groups": 0}

        rows = [dict(r) for r in con.execute("SELECT * FROM case_reviews")]
        planned = plan_review_version_renumber(rows)
        planned_by_id = {row["id"]: row for row in planned}
        renumbered = sum(1 for old in rows if planned_by_id[old["id"]]["version"] != old["version"])
        groups = len({(r["case_id"], r["endpoint"]) for r in rows})

        con.execute("PRAGMA foreign_keys=OFF")
        try:
            con.execute("BEGIN")
            con.execute("DROP TABLE IF EXISTS case_reviews_new")
            con.execute(
                """
                CREATE TABLE case_reviews_new (
                    id INTEGER NOT NULL,
                    case_id INTEGER NOT NULL,
                    case_version_id INTEGER,
                    endpoint VARCHAR(24) NOT NULL,
                    version VARCHAR(32) NOT NULL,
                    result VARCHAR(24) NOT NULL,
                    heading TEXT NOT NULL,
                    fields_json TEXT NOT NULL,
                    section_html TEXT NOT NULL,
                    detail_text TEXT NOT NULL,
                    repo VARCHAR(1000) NOT NULL,
                    branch TEXT NOT NULL,
                    participants TEXT NOT NULL,
                    style_css TEXT NOT NULL,
                    source_report_version_id INTEGER,
                    source_link_id INTEGER,
                    content_fingerprint VARCHAR(96) DEFAULT '' NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    PRIMARY KEY (id),
                    CONSTRAINT uq_case_review_version UNIQUE (case_id, endpoint, version),
                    FOREIGN KEY(case_id) REFERENCES test_cases (id),
                    FOREIGN KEY(case_version_id) REFERENCES test_case_versions (id)
                )
                """
            )
            insert_sql = """
                INSERT INTO case_reviews_new (
                    id, case_id, case_version_id, endpoint, version, result, heading,
                    fields_json, section_html, detail_text, repo, branch, participants,
                    style_css, source_report_version_id, source_link_id, content_fingerprint, created_at
                ) VALUES (
                    :id, :case_id, :case_version_id, :endpoint, :version, :result, :heading,
                    :fields_json, :section_html, :detail_text, :repo, :branch, :participants,
                    :style_css, :source_report_version_id, :source_link_id, :content_fingerprint, :created_at
                )
            """
            payloads = []
            for row in planned:
                payloads.append(
                    {
                        "id": row["id"],
                        "case_id": row["case_id"],
                        "case_version_id": row.get("case_version_id"),
                        "endpoint": row["endpoint"],
                        "version": row["version"],
                        "result": row.get("result") or "",
                        "heading": row.get("heading") or "",
                        "fields_json": row.get("fields_json") or "[]",
                        "section_html": row.get("section_html") or "",
                        "detail_text": row.get("detail_text") or "",
                        "repo": row.get("repo") or "",
                        "branch": row.get("branch") or "",
                        "participants": row.get("participants") or "",
                        "style_css": row.get("style_css") or "",
                        "source_report_version_id": row.get("source_report_version_id"),
                        "source_link_id": row.get("source_link_id"),
                        "content_fingerprint": row.get("content_fingerprint") or "",
                        "created_at": row.get("created_at"),
                    }
                )
            con.executemany(insert_sql, payloads)
            con.execute("DROP TABLE case_reviews")
            con.execute("ALTER TABLE case_reviews_new RENAME TO case_reviews")
            for name, col in (
                ("ix_case_reviews_case_id", "case_id"),
                ("ix_case_reviews_case_version_id", "case_version_id"),
                ("ix_case_reviews_endpoint", "endpoint"),
                ("ix_case_reviews_source_report_version_id", "source_report_version_id"),
                ("ix_case_reviews_source_link_id", "source_link_id"),
                ("ix_case_reviews_created_at", "created_at"),
            ):
                con.execute(f"CREATE INDEX IF NOT EXISTS {name} ON case_reviews ({col})")
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        finally:
            con.execute("PRAGMA foreign_keys=ON")
        return {
            "rebuilt": True,
            "rows": len(rows),
            "renumbered": renumbered,
            "groups": groups,
        }
    finally:
        con.close()


def _backfill_case_updated_at(conn) -> int:
    cols = [row[1] for row in conn.execute(text("PRAGMA table_info(test_cases)"))]
    added = 0
    if cols and "updated_at" not in cols:
        conn.execute(text("ALTER TABLE test_cases ADD COLUMN updated_at DATETIME"))
        added = 1
    before = conn.execute(text("SELECT COUNT(*) FROM test_cases WHERE updated_at IS NULL")).scalar()
    conn.execute(
        text(
            """
            UPDATE test_cases
            SET updated_at = (
                SELECT MAX(test_case_versions.created_at)
                FROM test_case_versions
                WHERE test_case_versions.case_id = test_cases.id
            )
            WHERE updated_at IS NULL
            """
        )
    )
    conn.execute(
        text(
            """
            UPDATE test_cases
            SET updated_at = CURRENT_TIMESTAMP
            WHERE updated_at IS NULL
            """
        )
    )
    filled = before or 0
    return filled if cols else 0


def ensure_review_fingerprint_column() -> bool:
    """Add case_reviews.content_fingerprint when create_all will not."""
    with engine.begin() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(case_reviews)"))]
        if cols and "content_fingerprint" not in cols:
            conn.execute(
                text(
                    "ALTER TABLE case_reviews "
                    "ADD COLUMN content_fingerprint VARCHAR(96) DEFAULT '' NOT NULL"
                )
            )
            return True
    return False


def migrate_schema():
    """Add columns / rebuild tables that create_all will not change on an existing SQLite file."""
    with engine.begin() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(report_versions)"))]
        if cols and "based_on_case_version" not in cols:
            conn.execute(
                text("ALTER TABLE report_versions ADD COLUMN based_on_case_version VARCHAR(32)")
            )
        version_adds = {
            "repo": "VARCHAR(1000) DEFAULT ''",
            "branch": "TEXT DEFAULT ''",
            "participants": "TEXT DEFAULT ''",
            "style_css": "TEXT DEFAULT ''",
            "header_parsed": "INTEGER DEFAULT 0",
            "details_parsed": "INTEGER DEFAULT 0",
            "source_size": "INTEGER DEFAULT 0",
            "source_mtime_ns": "INTEGER DEFAULT 0",
        }
        if cols:
            for name, decl in version_adds.items():
                if name not in cols:
                    conn.execute(text(f"ALTER TABLE report_versions ADD COLUMN {name} {decl}"))
        link_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(report_case_links)"))]
        link_adds = {
            "heading": "TEXT DEFAULT ''",
            "anchor": "VARCHAR(200) DEFAULT ''",
            "section_html": "TEXT DEFAULT ''",
            "fields_json": "TEXT DEFAULT '[]'",
            "detail_text": "TEXT DEFAULT ''",
            "detail_parsed": "INTEGER DEFAULT 0",
        }
        if link_cols:
            for name, decl in link_adds.items():
                if name not in link_cols:
                    conn.execute(text(f"ALTER TABLE report_case_links ADD COLUMN {name} {decl}"))
        comment_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(case_comments)"))]
        if comment_cols and "environment" not in comment_cols:
            conn.execute(text("ALTER TABLE case_comments ADD COLUMN environment VARCHAR(32) DEFAULT ''"))
        if comment_cols or "environment" in [row[1] for row in conn.execute(text("PRAGMA table_info(case_comments)"))]:
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ux_case_comments_environment "
                    "ON case_comments(case_id, environment) "
                    "WHERE environment IS NOT NULL AND environment != ''"
                )
            )
        _backfill_case_updated_at(conn)

    con = sqlite3.connect(DB_PATH)
    try:
        needs = case_reviews_needs_retarget(con)
    finally:
        con.close()
    if not needs:
        LAST_RETARGET_STATS.clear()
        LAST_RETARGET_STATS.update({"rebuilt": False, "rows": 0, "renumbered": 0, "groups": 0})
    else:
        backup = _backup_sqlite("case-reviews-retarget")
        stats = retarget_case_reviews(DB_PATH)
        stats["backup"] = str(backup)
        LAST_RETARGET_STATS.clear()
        LAST_RETARGET_STATS.update(stats)
        log.info("retarget_case_reviews %s", stats)

    ensure_review_fingerprint_column()
    from app.case_reviews import backfill_review_fingerprints

    fp_stats = backfill_review_fingerprints()
    LAST_FINGERPRINT_STATS.clear()
    LAST_FINGERPRINT_STATS.update(fp_stats)
    log.info("backfill_review_fingerprints %s", fp_stats)
