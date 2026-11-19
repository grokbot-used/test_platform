"""Parse real case/report HTML for document info, stats, and review header meta."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.parsers import (  # noqa: E402
    build_priority_stats,
    count_untested_cases,
    extract_case_document_info,
    extract_report_case_detail,
    extract_report_header_meta,
)

FILES = ROOT / "data" / "files"
GMA_CASE_V106 = FILES / "global-model" / "cases" / "黑盒测试用例_全球型号接入_v1.0.6.html"
GMA_BACKEND_V101 = FILES / "global-model" / "reports" / "后端静态推演_全球型号接入_v1.0.1.html"
EXDATA_BACKEND_V30 = FILES / "exdata-vin" / "reports" / "exData-VIN-后端推演报告-v3.0.html"
R58L_FRONTEND = FILES / "r58l" / "reports" / "R58L-pro-plus-前端推演报告.html"
PRICE_CASE = FILES / "price-openapi" / "cases" / "黑盒测试用例_价格管控OpenAPI_v1.0.6.html"
R58L_CASE = FILES / "r58l" / "cases" / "R58L-pro-plus-黑盒用例表.html"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def test_gma_v106_untested_and_case_info():
    html = _read(GMA_CASE_V106)
    assert count_untested_cases(html) == 11

    info = extract_case_document_info(html)
    assert info["available"] is True
    assert "全球型号接入" in info["title"]
    labels = [f["label"] for f in info["fields"]]
    assert any(lab.startswith("参与人") for lab in labels)
    assert any("条数" in lab for lab in labels)
    frag = info["fragment_page"]
    assert "参与人" in frag
    assert "模块一览" in frag
    body = frag.split("<body>", 1)[-1] if "<body>" in frag else frag
    assert body.count("<article") < 5
    assert "data-search=" not in body
    assert body.count('class="case"') == 0 or "模块一览" in body


def test_gma_v106_priority_from_html_data_pri():
    from bs4 import BeautifulSoup

    html = _read(GMA_CASE_V106)
    soup = BeautifulSoup(html, "lxml")
    pris = [el.get("data-pri") or "" for el in soup.select("article.case")]
    stats = build_priority_stats(pris, count_untested_cases(html))
    by = {p["priority"]: p for p in stats["priorities"]}
    assert stats["total"] == 479
    assert stats["untested"] == 11
    assert by["P1"]["count"] == 34
    assert by["P2"]["count"] == 187
    assert by["P3"]["count"] == 258
    assert by["P1"]["percent"] == 7.1
    assert by["P2"]["percent"] == 39.0
    assert by["P3"]["percent"] == 53.9


def test_gma_backend_report_header_and_fragment_cleanup():
    html = _read(GMA_BACKEND_V101)
    meta = extract_report_header_meta(html)
    assert meta["repo"] == "http://192.168.100.88:19523/huangjinjian/swdcloud.git"
    assert "test" in meta["branch"]
    assert "634dd36dd3cfa033307e7160c23a226594e623b2" in meta["branch"]
    assert "断水流大师兄" in meta["participants"]

    detail = extract_report_case_detail(html, "TC-GMA-001")
    assert detail["found"] is True
    assert detail["heading"].startswith("#1")
    assert not detail["heading"].startswith("1")
    labels = [f["label"] for f in detail["fields"]]
    assert labels == ["后端链路", "推演结果", "不通过原因", "备注"]
    frag = detail["html"]
    assert "问题级别" not in labels
    assert "问题级别" not in frag
    assert "推演用例编号" not in frag
    assert "用例标题" not in frag
    assert "标题" not in labels
    # heading outside the table stays #N
    assert "<h3>#1" in frag or ">#1" in frag


def test_exdata_backend_header_has_repo_and_participants_only():
    html = _read(EXDATA_BACKEND_V30)
    meta = extract_report_header_meta(html)
    assert meta["repo"]
    assert "swdcloud-test" in meta["repo"]
    assert meta["participants"]
    assert "大师兄" in meta["participants"] or "祺祺" in meta["participants"]
    assert meta["branch"] == ""


def test_r58l_frontend_header_is_empty():
    html = _read(R58L_FRONTEND)
    meta = extract_report_header_meta(html)
    assert meta == {"repo": "", "branch": "", "participants": ""}
    detail = extract_report_case_detail(html, "TC-R58-001")
    assert detail["found"] is True
    assert detail["heading"].lstrip("#").startswith("1") is False or detail["heading"].startswith("#1")
    assert "#1" in detail["heading"]
    assert "问题级别" not in detail["html"]


def test_price_and_r58l_case_docs_keep_preamble_drop_case_list():
    price = extract_case_document_info(_read(PRICE_CASE))
    assert price["available"] is True
    assert "价格管控" in price["title"]
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(price["fragment_page"], "lxml")
    assert soup.select("table.cases") == []
    assert soup.find("h1") is not None

    r58 = extract_case_document_info(_read(R58L_CASE))
    assert r58["available"] is True
    assert "R58L" in r58["title"]
    rs = BeautifulSoup(r58["fragment_page"], "lxml")
    assert len(rs.find_all("tr")) == 0
    assert "TC-R58-001" not in r58["fragment_page"]
