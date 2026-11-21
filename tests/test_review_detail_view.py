"""Canonical v0.0.2 review-detail card: 4 fields, no extra labels."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.parsers import REVIEW_DETAIL_FIELD_NAMES, build_review_detail_view
from app.case_reviews import create_review, review_detail
from app.db import SessionLocal, init_db
from tests.test_case_reviews import SLUG, _cleanup_product, _product_fixture


TABLE_HTML = """
<section class="case" data-result="不通过">
  <h3>1 新用户自主注册后返回登录页并首次登录进入添加设备</h3>
  <table>
    <tr><th>用例标题</th><td>新用户自主注册后返回登录页并首次登录进入添加设备</td></tr>
    <tr><th>推演用例编号</th><td>1</td></tr>
    <tr><th>后端链路</th><td>入口是 <code>SelfRegisterController</code>。<br/>第二步校验 token。</td></tr>
    <tr><th>推演结果</th><td class="fail">失败</td></tr>
    <tr><th>不通过原因</th><td>验证码格式不匹配</td></tr>
    <tr><th>备注</th><td>建议重新推演</td></tr>
    <tr><th>问题级别</th><td>P2</td></tr>
  </table>
</section>
"""

PLAIN_HTML = """
<p><strong>用例标题</strong>：新用户自主注册后返回登录页并首次登录进入添加设备</p>
<p><strong>推演结果</strong>：通过</p>
<p><strong>后端链路</strong>：</p>
<p>1. 入口证明，对应 <code>SelfRegisterController</code>。</p>
<p>2. 网关 AuthGlobalFilter 校验白名单。</p>
"""

PLAIN_TEXT = """
用例标题: 验证码发送接口5xx时恢复发送按钮并允许重试
推演结果: 通过
后端链路:
1. 点击「获取验证码」对应 sendEmailCode。
不通过/跳过原因:
备注/证据: 邮件模板未核验
"""


def _labels(fields):
    return [item["label"] for item in fields]


def test_old_table_html_is_renamed_and_trimmed():
    html, fields, heading = build_review_detail_view(
        TABLE_HTML,
        heading="",
        result="fail",
        result_label="失败",
    )
    assert heading.startswith("#1")
    assert _labels(fields) == list(REVIEW_DETAIL_FIELD_NAMES)
    by = {item["label"]: item for item in fields}
    assert "SelfRegisterController" in by["推演链路"]["value_text"]
    assert "<code>" in by["推演链路"]["value_html"]
    assert by["推演结果"]["value_text"] == "失败"
    assert by["不通过原因"]["value_text"] == "验证码格式不匹配"
    assert by["备注"]["value_text"] == "建议重新推演"
    assert "用例标题" not in html
    assert "后端链路" not in html
    assert "问题级别" not in html
    assert "推演用例编号" not in html
    assert "推演链路" in html
    assert "review-card" in html
    assert "<td><td>" not in html
    assert 'data-result="不通过"' in html


def test_plain_markdown_html_becomes_v002_card():
    html, fields, heading = build_review_detail_view(
        PLAIN_HTML,
        heading="",
        result="pass",
        result_label="通过",
    )
    assert "新用户自主注册" in heading
    assert _labels(fields) == list(REVIEW_DETAIL_FIELD_NAMES)
    by = {item["label"]: item for item in fields}
    assert "SelfRegisterController" in by["推演链路"]["value_text"]
    assert by["推演结果"]["value_text"] == "通过"
    assert by["不通过原因"]["value_text"] == "—"
    assert by["备注"]["value_text"] == "—"
    assert "用例标题" not in html
    assert "后端链路" not in html
    assert ">推演链路<" in html or ">推演链路</" in html
    assert 'data-result="通过"' in html


def test_text_aliases_and_result_fallback():
    html, fields, heading = build_review_detail_view(
        "",
        text=PLAIN_TEXT,
        result="pass",
        result_label="通过",
        fallback_title="备用标题",
    )
    assert "验证码发送接口" in heading
    by = {item["label"]: item for item in fields}
    assert "sendEmailCode" in by["推演链路"]["value_text"]
    assert by["推演结果"]["value_text"] == "通过"
    assert by["不通过原因"]["value_text"] == "—"
    assert by["备注"]["value_text"] == "邮件模板未核验"
    assert _labels(fields) == list(REVIEW_DETAIL_FIELD_NAMES)


def test_empty_fields_use_dash_and_result_from_record():
    html, fields, heading = build_review_detail_view(
        "",
        fields=[],
        heading="标题甲",
        result="skip",
        result_label="跳过",
    )
    assert heading == "标题甲"
    by = {item["label"]: item for item in fields}
    assert by["推演链路"]["value_text"] == "—"
    assert by["推演结果"]["value_text"] == "跳过"
    assert by["不通过原因"]["value_text"] == "—"
    assert by["备注"]["value_text"] == "—"
    assert 'data-result="跳过"' in html


def test_gma_backend_and_posted_plain_share_display_shape():
    init_db()
    db = SessionLocal()
    try:
        gma = None
        from app.models import TestCase

        gma = db.query(TestCase).filter_by(key="TC-GMA-001").one_or_none()
        if gma is not None:
            detail = review_detail(db, gma.product_id, "backend", gma.id, "v1.0.6")
            assert detail["found"] is True
            labels = _labels(detail["fields"])
            assert labels == list(REVIEW_DETAIL_FIELD_NAMES)
            assert "用例标题" not in (detail["html"] or "")
            assert "后端链路" not in (detail["html"] or "")
            assert "推演链路" in (detail["html"] or "")
            assert detail["heading"].startswith("#1")
            assert detail["created_at"]
            # API stores UTC naive, serializes as UTC+8 offset
            assert "+08:00" in detail["created_at"]

        product, case, _v1, v2 = _product_fixture(db)
        created = create_review(
            db,
            {
                "case_id": case.id,
                "endpoint": "backend",
                "result": "pass",
                "heading": "",
                "html": PLAIN_HTML,
                "text": "",
                "repo": "swdcloud",
                "branch": "test",
                "participants": "断水流大师兄（后端推演）",
            },
        )
        assert _labels(created["fields"]) == list(REVIEW_DETAIL_FIELD_NAMES)
        assert "用例标题" not in created["html"]
        assert "后端链路" not in created["html"]
        assert "推演链路" in created["html"]
        assert "SelfRegisterController" in created["html"]
        detail = review_detail(db, product.id, "backend", case.id)
        assert _labels(detail["fields"]) == list(REVIEW_DETAIL_FIELD_NAMES)
        assert detail["repo"] == "swdcloud"
        assert detail["created_at"].endswith("+08:00")
        parsed = datetime.fromisoformat(detail["created_at"])
        assert parsed.tzinfo is not None
        assert parsed.utcoffset().total_seconds() == 8 * 3600
    finally:
        db = SessionLocal()
        try:
            _cleanup_product(db, None)
        finally:
            db.close()
