import asyncio
from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from app.comments import comment_counts, create_comment, list_comments
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
    finally:
        if created_ids:
            db.query(CaseComment).filter(CaseComment.id.in_(created_ids)).delete(synchronize_session=False)
            db.commit()
        db.close()
