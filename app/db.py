from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import DATABASE_URL, DB_PATH


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


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    migrate_schema()


def migrate_schema():
    """Add columns that create_all will not attach to an existing SQLite file."""
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
