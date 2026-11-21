import asyncio
from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from datetime import datetime, timezone

from app.comments import (
    _fmt_dt,
    comment_counts,
    comment_environments,
    create_comment,
    delete_comment,
    list_comments,
)
from app.config import FILES_DIR
from app.db import SessionLocal, init_db
from app.main import get_case_docs
from app.models import CaseComment, TestCase

# 1x1 PNG
PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc``\x00\x00"
    b"\x00\x02\x00\x01\xe2!\xbc3\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_case_comments_text_image_and_order():
    init_db()
    db = SessionLocal()
    created_ids = []
    try:
        case = db.query(TestCase).order_by(TestCase.id.asc()).first()
        assert case is not None

        with pytest.raises(HTTPException) as empty:
            asyncio.run(create_comment(db, case.id, body="   "))
        assert empty.value.status_code == 400

        first = asyncio.run(create_comment(db, case.id, body="第一条评论", case_version="v-test"))
        created_ids.append(first["id"])
        upload = UploadFile(
            filename="dot.png",
            file=BytesIO(PNG),
            headers=Headers({"content-type": "image/png"}),
        )
        second = asyncio.run(create_comment(db, case.id, body="", images=[upload], case_version="v-test"))
        created_ids.append(second["id"])

        data = list_comments(db, case.id)
        ids = [item["id"] for item in data["items"]]
        assert ids == sorted(ids)
        assert data["items"][-2]["body"] == "第一条评论"
        assert data["items"][-1]["images"]
        assert data["items"][-1]["images"][0]["url"].startswith("/files/comments/")

        counts = comment_counts(db, [case.id])
        assert counts.get(case.id, 0) >= 2

        docs = get_case_docs(product_id=case.product_id, page=1, page_size=20, db=db)
        found = next((item for item in docs["items"] if item["id"] == case.id), None)
        if found is not None:
            assert found["comment_count"] >= 2

        image_dir = FILES_DIR / "comments" / str(second["id"])
        assert image_dir.exists()
        removed = delete_comment(db, case.id, second["id"])
        assert removed["ok"] is True
        assert not image_dir.exists()
        leftover = list_comments(db, case.id)
        assert second["id"] not in [item["id"] for item in leftover["items"]]
        with pytest.raises(HTTPException) as missing:
            delete_comment(db, case.id, second["id"])
        assert missing.value.status_code == 404
        created_ids.remove(second["id"])
    finally:
        if created_ids:
            from shutil import rmtree
            for cid in created_ids:
                folder = FILES_DIR / "comments" / str(cid)
                if folder.exists():
                    rmtree(folder, ignore_errors=True)
            db.query(CaseComment).filter(CaseComment.id.in_(created_ids)).delete(synchronize_session=False)
            db.commit()
        db.close()


def test_comment_time_is_utc_plus_eight():
    naive_utc = datetime(2026, 11, 20, 7, 0, 0)
    assert _fmt_dt(naive_utc) == "2026-11-20T15:00:00+08:00"
    aware_utc = datetime(2026, 11, 20, 7, 0, 0, tzinfo=timezone.utc)
    assert _fmt_dt(aware_utc) == "2026-11-20T15:00:00+08:00"


def test_environment_comment_unique_until_deleted():
    init_db()
    db = SessionLocal()
    created_ids = []
    try:
        case = db.query(TestCase).order_by(TestCase.id.asc()).first()
        assert case is not None

        first = asyncio.run(
            create_comment(db, case.id, body="测试线记录", environment="test", case_version="v-test")
        )
        created_ids.append(first["id"])
        assert first["environment"] == "test"
        assert first["environment_label"] == "测试线"
        assert first["created_at"].endswith("+08:00")

        with pytest.raises(HTTPException) as locked:
            asyncio.run(create_comment(db, case.id, body="再写一条", environment="test"))
        assert locked.value.status_code == 409

        general = asyncio.run(create_comment(db, case.id, body="普通记录"))
        created_ids.append(general["id"])
        assert general["environment"] == ""

        with pytest.raises(HTTPException) as bad:
            asyncio.run(create_comment(db, case.id, body="未知环境", environment="staging"))
        assert bad.value.status_code == 400

        env_map = comment_environments(db, [case.id])
        assert env_map[case.id]["test"] == first["id"]

        delete_comment(db, case.id, first["id"])
        created_ids.remove(first["id"])
        again = asyncio.run(create_comment(db, case.id, body="测试线再记录", environment="test"))
        created_ids.append(again["id"])
        assert again["environment"] == "test"
    finally:
        if created_ids:
            from shutil import rmtree
            for cid in created_ids:
                folder = FILES_DIR / "comments" / str(cid)
                if folder.exists():
                    rmtree(folder, ignore_errors=True)
            db.query(CaseComment).filter(CaseComment.id.in_(created_ids)).delete(synchronize_session=False)
            db.commit()
        db.close()
