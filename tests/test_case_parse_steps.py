from pathlib import Path

from app.config import FILES_DIR
from app.db import SessionLocal, init_db
from app.models import TestCase, TestCaseVersion
from app.parsers import parse_case_html, repair_misparsed_card_steps

CARD_HTML = """
<html><body>
<article class="case" id="case-001" data-pri="P1">
  <header class="case-hd">
    <span class="num">1</span>
    <span class="case-title">取本包</span>
  </header>
  <div class="case-grid">
    <section>
      <h4>前置步骤</h4>
      <div class="steps">公共前置已满足。</div>
    </section>
    <section>
      <h4>操作步骤</h4>
      <ol class="steps">
        <li>登录设备。</li>
        <li>发送告警包。</li>
      </ol>
    </section>
    <section>
      <h4>预期结果</h4>
      <ol class="steps"><li>列表可见本条告警。</li></ol>
    </section>
  </div>
</article>
</body></html>
"""

TABLE_HTML = """
<html><body>
<table>
  <tr><th>编号</th><th>标题</th><th>前置条件</th><th>步骤</th><th>预期结果</th></tr>
  <tr><td>1</td><td>表格用例</td><td>已登录</td><td>点击保存</td><td>保存成功</td></tr>
</table>
</body></html>
"""


def test_card_steps_use_exact_operation_heading():
    parsed = parse_case_html(CARD_HTML, "demo.html", key_prefix="TC-A5")
    rec = parsed["cases"][0]
    assert rec["preconditions"] == "公共前置已满足。"
    assert "登录设备" in rec["steps"]
    assert "发送告警包" in rec["steps"]
    assert rec["steps"] != rec["preconditions"]
    assert "列表可见本条告警" in rec["expected"]


def test_table_steps_column_still_maps():
    parsed = parse_case_html(TABLE_HTML, "table.html", key_prefix="TC-TB")
    rec = parsed["cases"][0]
    assert rec["preconditions"] == "已登录"
    assert rec["steps"] == "点击保存"
    assert rec["expected"] == "保存成功"


def test_gt06_source_and_repair_only_rewrites_steps():
    path = FILES_DIR / "gt06-a5/cases/黑盒测试用例_A5告警包定位解析_v1.0.0.html"
    parsed = parse_case_html(path.read_text(encoding="utf-8"), path.name, key_prefix="TC-A5")
    rec = next(item for item in parsed["cases"] if item["key"] == "TC-A5-001")
    assert rec["preconditions"].startswith("公共前置已满足")
    assert "IMEI" in rec["steps"] or "0xA5" in rec["steps"]
    assert rec["steps"] != rec["preconditions"]

    init_db()
    db = SessionLocal()
    try:
        row = (
            db.query(TestCaseVersion)
            .join(TestCase, TestCase.id == TestCaseVersion.case_id)
            .filter(TestCase.key == "TC-A5-001", TestCaseVersion.version == "v1.0.0")
            .one()
        )
        original_pre = row.preconditions
        original_expected = row.expected
        # Simulate the old bug, then repair should only restore steps.
        row.steps = row.preconditions
        db.commit()
        changed = repair_misparsed_card_steps(db)
        db.refresh(row)
        assert changed >= 1
        assert row.preconditions == original_pre
        assert row.expected == original_expected
        assert row.steps != row.preconditions
        assert "0xA5" in row.steps or "IMEI" in row.steps
    finally:
        db.close()
