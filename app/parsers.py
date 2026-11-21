"""Parse case and report HTML/Markdown into structured records."""

from __future__ import annotations

import html as html_lib
import re
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag

VERSION_RE = re.compile(r"v?\d+(?:\.\d+){1,3}", re.I)
FILENAME_VERSION_RE = re.compile(r"(?:^|[_\-])v(\d+(?:\.\d+){1,3})", re.I)
TC_KEY_RE = re.compile(r"\b(TC-[A-Z0-9]+-\d{1,4})\b", re.I)
NUM_KEY_RE = re.compile(r"^(\d{1,4})$")

RESULT_CLASS = {
    "pass": "pass",
    "ok": "pass",
    "tag-pass": "pass",
    "tag-ok": "pass",
    "fail": "fail",
    "tag-fail": "fail",
    "skip": "skip",
    "tag-skip": "skip",
    "paused": "skip",
    "blocked": "blocked",
    "tag-blocked": "blocked",
    "untested": "untested",
    "pending": "untested",
}

RESULT_TEXT = {
    "通过": "pass",
    "失败": "fail",
    "不通过": "fail",
    "跳过": "skip",
    "暂停": "skip",
    "阻塞": "blocked",
    "未测": "untested",
    "不测": "untested",
}

HEADER_MAP = {
    "序号": "key",
    "编号": "key",
    "id": "key",
    "优先级": "priority",
    "优先级（用例）": "priority",
    "业务端": "client",
    "端": "client",
    "模块": "module",
    "用例描述": "title",
    "标题": "title",
    "描述": "title",
    "前置步骤": "preconditions",
    "前置条件": "preconditions",
    "操作步骤": "steps",
    "步骤": "steps",
    "预期结果": "expected",
    "类型": "case_type",
    "测试数据": "test_data",
}


def normalize_version(raw: str | None, default: str = "v1.0.0") -> str:
    if not raw:
        return default
    text = raw.strip()
    m = VERSION_RE.search(text)
    if not m:
        return default
    ver = m.group(0)
    if not ver.lower().startswith("v"):
        ver = "v" + ver
    return "v" + ver[1:]


def version_from_filename(name: str, default: str = "v1.0.0") -> str:
    m = FILENAME_VERSION_RE.search(name)
    if m:
        return normalize_version("v" + m.group(1))
    return default


def version_from_html(html: str, filename: str = "", default: str = "v1.0.0") -> str:
    m = re.search(r"版本[:：]\s*(v?\d+(?:\.\d+){1,3})", html[:40000], flags=re.I)
    if m:
        return normalize_version(m.group(1))
    title_m = re.search(r"<title>([^<]+)</title>", html[:4000], flags=re.I)
    if title_m:
        tm = VERSION_RE.search(title_m.group(1))
        if tm:
            return normalize_version(tm.group(0))
    # markdown / plain-text first heading
    hm = re.search(r"^#\s+(.+)$", html[:2000], re.M)
    if hm:
        tm = VERSION_RE.search(hm.group(1))
        if tm:
            return normalize_version(tm.group(0))
    return version_from_filename(filename, default=default)


def text_of(el: Tag | None) -> str:
    if el is None:
        return ""
    clone = BeautifulSoup(str(el), "lxml")
    root = clone.body if clone.body else clone
    for br in root.find_all("br"):
        br.replace_with("\n")
    for li in root.find_all("li"):
        li.insert(0, NavigableString("\n- "))
    text = root.get_text("\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _plain(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def _format_tc(key: str) -> str:
    key = key.upper()
    parts = key.split("-")
    if len(parts) >= 3:
        num = parts[-1].zfill(3) if len(parts[-1]) <= 3 else parts[-1]
        return f"{parts[0]}-{parts[1]}-{num}"
    return key


def _norm_key(raw: str, prefix: str | None = None) -> str | None:
    raw = _plain(raw)
    if not raw or raw in {"—", "-", "/", "无"}:
        return None
    m = TC_KEY_RE.search(raw)
    if m:
        return _format_tc(m.group(1))
    m = re.fullmatch(r"(?:case[-_])?(\d{1,4})(?:[-_](\d{1,3}))?", raw, re.I)
    if m and prefix:
        base = f"{prefix}-{int(m.group(1)):03d}"
        return f"{base}-{m.group(2)}" if m.group(2) else base
    if prefix and NUM_KEY_RE.match(raw):
        return f"{prefix}-{int(raw):03d}"
    return None


def _map_headers(cells: list[str]) -> dict[int, str] | None:
    mapping: dict[int, str] = {}
    for i, raw in enumerate(cells):
        key = HEADER_MAP.get(raw.strip())
        if key:
            mapping[i] = key
    if "key" in mapping.values() and ("title" in mapping.values() or "expected" in mapping.values()):
        return mapping
    return None


def parse_case_html(html: str, filename: str = "", key_prefix: str | None = None) -> dict:
    soup = BeautifulSoup(html, "lxml")
    version = version_from_html(html, filename)
    title = text_of(soup.title) or Path(filename).stem
    cases: list[dict] = []

    articles = soup.select("article.case")
    if articles:
        for art in articles:
            rec = _parse_case_card(art, key_prefix)
            if rec:
                cases.append(rec)
    else:
        seen: set[str] = set()
        for table in soup.find_all("table"):
            classes = " ".join(table.get("class") or [])
            if any(x in classes for x in ("skip-table", "rule-table", "mod-table")):
                continue
            rows = table.find_all("tr")
            if not rows:
                continue
            mapping = None
            for tr in rows:
                cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
                if mapping is None:
                    maybe = _map_headers(cells)
                    if maybe:
                        mapping = maybe
                    continue
                rec = _row_to_case(tr, mapping, key_prefix)
                if rec and rec["key"] not in seen:
                    seen.add(rec["key"])
                    cases.append(rec)

    return {"version": version, "title": title, "cases": cases}


def _meta_value(art: Tag, label: str) -> str:
    for div in art.select(".case-meta > div"):
        k = div.select_one(".k")
        v = div.select_one(".v")
        if k and v and label in k.get_text(strip=True):
            return text_of(v)
    return ""


def _heading_matches(
    heading: str,
    labels: tuple[str, ...],
    *,
    exact: bool = False,
    exclude: tuple[str, ...] = (),
) -> bool:
    text = (heading or "").strip()
    if not text:
        return False
    if any(token in text for token in exclude):
        return False
    if exact:
        return text in labels
    return any(label in text for label in labels)



def _collapse_inline(s: str) -> str:
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    s = re.sub(r" *\n *", "\n", s)
    s = re.sub(r"\s+([，。；：、）】》.,;:)\]）])", r"\1", s)
    s = re.sub(r"([（【《(\[])\s+", r"\1", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _collect_flow(el: Tag) -> str:
    parts: list[str] = []
    for child in el.children:
        if isinstance(child, NavigableString):
            parts.append(re.sub(r"\s+", " ", str(child)))
        elif child.name == "br":
            parts.append("\n")
        elif child.name in ("ol", "ul", "li"):
            continue
        elif child.name in ("p", "div", "section", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6", "tr"):
            inner = _field_text_from(child)
            if inner:
                parts.append("\n" + inner + "\n")
        else:
            parts.append(_collect_flow(child))
    return "".join(parts)


def _field_text_from(el: Tag) -> str:
    lis = el.find_all("li")
    if lis:
        items: list[str] = []
        for i, li in enumerate(lis, 1):
            t = _collapse_inline(_collect_flow(li))
            if t:
                items.append(f"{i}. {t}")
        return "\n".join(items)
    return _collapse_inline(_collect_flow(el))


def field_text(el: Tag | None) -> str:
    """Extract case-section text: lists become numbered lines, inline tags stay in-sentence."""
    if el is None:
        return ""
    clone = BeautifulSoup(str(el), "lxml")
    root = clone.body if clone.body else clone
    return _field_text_from(root)


def _section_value(
    art: Tag,
    labels: tuple[str, ...],
    *,
    exact: bool = False,
    exclude: tuple[str, ...] = (),
) -> str:
    for section in art.select(".case-grid section, section"):
        h = section.find(["h4", "h3", "h5"])
        if not h:
            continue
        ht = h.get_text(strip=True)
        if not _heading_matches(ht, labels, exact=exact, exclude=exclude):
            continue
        body = section.select_one(".steps") or section
        if body is section:
            clone = BeautifulSoup(str(section), "lxml")
            for hh in clone.find_all(["h4", "h3", "h5"]):
                hh.decompose()
            return field_text(clone)
        return field_text(body)
    return ""


def _parse_case_card(art: Tag, key_prefix: str | None) -> dict | None:
    raw_num = text_of(art.select_one(".num")) or (art.get("id") or "").replace("case-", "")
    key = _norm_key(raw_num, key_prefix)
    if not key:
        return None
    title = _plain(text_of(art.select_one(".case-title")) or _meta_value(art, "用例描述"))
    priority = art.get("data-pri") or ""
    if not priority:
        tag = art.select_one(".tag-p0, .tag-p1, .tag-p2, .tag-p3, .tag-p4, .pri, .tag")
        if tag:
            m = re.search(r"P[0-4]", tag.get_text(strip=True), re.I)
            if m:
                priority = m.group(0).upper()
    module = _plain(text_of(art.select_one(".case-mod")) or _meta_value(art, "模块"))
    client = _plain(_meta_value(art, "业务端"))
    description = _plain(_meta_value(art, "用例描述") or title)
    return {
        "key": key,
        "title": title or description,
        "module": module,
        "priority": (priority or "").upper(),
        "client": client.lower() if client else "",
        "description": description,
        "preconditions": _section_value(art, ("前置步骤", "前置条件"), exact=True)
        or _section_value(art, ("前置",)),
        "steps": _section_value(art, ("操作步骤",), exact=True)
        or _section_value(art, ("步骤",), exact=True, exclude=("前置",)),
        "expected": _section_value(art, ("预期结果",), exact=True) or _section_value(art, ("预期",)),
    }


def _row_to_case(tr: Tag, mapping: dict[int, str], key_prefix: str | None) -> dict | None:
    cells = tr.find_all("td")
    if not cells:
        return None
    raw: dict[str, str] = {}
    for i, td in enumerate(cells):
        field = mapping.get(i)
        if field:
            raw[field] = text_of(td)
    key = _norm_key(raw.get("key", ""), key_prefix)
    if not key:
        return None
    title = raw.get("title") or ""
    return {
        "key": key,
        "title": title,
        "module": raw.get("module") or "",
        "priority": (raw.get("priority") or "").upper(),
        "client": (raw.get("client") or "").lower(),
        "description": title,
        "preconditions": raw.get("preconditions") or "",
        "steps": raw.get("steps") or "",
        "expected": raw.get("expected") or "",
    }


def extract_result(el: Tag) -> str:
    classes = el.get("class") or []
    for c in classes:
        if c in RESULT_CLASS:
            return RESULT_CLASS[c]
    for node in el.select(
        ".badge, .tag, .pass, .fail, .skip, .ok, .blocked, .paused, [class*='tag-']"
    ):
        for c in node.get("class") or []:
            if c in RESULT_CLASS:
                return RESULT_CLASS[c]
        t = node.get_text(strip=True)
        if t in RESULT_TEXT:
            return RESULT_TEXT[t]
    text = el.get_text(" ", strip=True)
    m = re.search(
        r"(测试结果|推演结果|结果|结论)[:：\s]*[|｜]?\s*(通过|失败|不通过|跳过|阻塞|暂停|未测|不测)",
        text,
    )
    if m:
        return RESULT_TEXT[m.group(2)]
    head = text[:80]
    for word, val in RESULT_TEXT.items():
        if word in head:
            return val
    return ""


def _heading_key(el: Tag, key_prefix: str | None) -> str | None:
    ident = el.get("id") or ""
    if TC_KEY_RE.search(ident or ""):
        return _norm_key(ident, key_prefix)
    num = el.select_one(".num, h2, h3, header, .case-hd")
    blob = text_of(num) if num else ""
    if blob:
        key = _norm_key(blob, key_prefix)
        if key:
            return key
    head = text_of(el)[:300]
    m = TC_KEY_RE.search(head)
    if m:
        return _norm_key(m.group(1), key_prefix)
    m = re.search(r"(推演用例编号|用例编号|执行用例|编号)[:：\s]*([A-Za-z0-9\-]+|\d+)", head)
    if m:
        key = _norm_key(m.group(2), key_prefix)
        if key:
            return key
    m = re.fullmatch(r"case[-_](\d+)(?:[-_](\d+))?", ident or "", re.I)
    if m and key_prefix:
        base = f"{key_prefix}-{int(m.group(1)):03d}"
        return f"{base}-{m.group(2)}" if m.group(2) else base
    # "69-1" style sub-numbers in the heading text
    m = re.search(r"(?:^|\s|#)(\d{1,4})[-_](\d{1,3})(?:\s|$)", head or blob or ident)
    if m and key_prefix:
        return f"{key_prefix}-{int(m.group(1)):03d}-{m.group(2)}"
    return None


def _summary_from_soup(soup: BeautifulSoup) -> tuple[str, str]:
    chunks: list[str] = []
    for sel in (".summary", ".kpi", ".hero-sub", ".conclusion", ".meta", ".sum"):
        for el in soup.select(sel)[:8]:
            t = _plain(el.get_text(" ", strip=True))
            if t and t not in chunks:
                chunks.append(t)
    if not any("结论" in t and len(t) > 6 for t in chunks):
        for el in soup.find_all(["p", "li", "div", "span"], limit=80):
            t = _plain(el.get_text(" ", strip=True))
            if re.match(r"^结论\s*[:：]", t) and len(t) > 6:
                chunks.append(t)
                break
    summary = " ｜ ".join(chunks[:4])
    scored = []
    for t in chunks:
        score = 0
        if re.match(r"^结论\s*[:：]", t):
            score += 5
        if any(w in t for w in ("通过", "失败", "跳过", "共推演", "总共", "共 ")):
            score += 3
        if "结论" in t:
            score += 1
        score += min(len(t), 240) / 240
        if len(t) <= 4:
            score = 0
        scored.append((score, t))
    scored.sort(reverse=True)
    conclusion = scored[0][1] if scored and scored[0][0] > 0 else (chunks[0] if chunks else "")
    return summary, conclusion


def parse_report_html(html: str, filename: str = "", key_prefix: str | None = None) -> dict:
    soup = BeautifulSoup(html, "lxml")
    version = version_from_html(html, filename)
    title = text_of(soup.title) or Path(filename).stem
    summary, conclusion = _summary_from_soup(soup)
    links: list[dict] = []
    seen: set[str] = set()

    cases = soup.select("article.case, section.case, div.case, .case")
    filtered: list[Tag] = []
    for el in cases:
        if any(isinstance(parent, Tag) and parent in cases for parent in el.parents):
            continue
        filtered.append(el)

    for el in filtered:
        key = _heading_key(el, key_prefix)
        if not key or key in seen:
            continue
        seen.add(key)
        links.append({"key": key, "result": extract_result(el)})

    if not links:
        for item in _links_from_tables(soup, key_prefix):
            if item["key"] not in seen:
                seen.add(item["key"])
                links.append(item)

    return {
        "version": version,
        "title": title,
        "summary": summary,
        "conclusion": conclusion,
        "links": links,
    }


def _links_from_tables(soup: BeautifulSoup, key_prefix: str | None) -> list[dict]:
    links: list[dict] = []
    seen: set[str] = set()
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        headers = [c.get_text(" ", strip=True) for c in rows[0].find_all(["th", "td"])]
        joined = " ".join(headers)
        if not any(h in joined for h in ("推演用例", "用例编号", "执行用例", "编号", "序号")):
            continue
        if not any(h in joined for h in ("推演结果", "测试结果", "结果")):
            continue
        key_idx = next(
            (
                i
                for i, h in enumerate(headers)
                if any(x in h for x in ("推演用例", "用例编号", "执行用例", "编号", "序号"))
            ),
            0,
        )
        result_idx = next(
            (i for i, h in enumerate(headers) if any(x in h for x in ("推演结果", "测试结果", "结果"))),
            None,
        )
        for tr in rows[1:]:
            tds = tr.find_all("td")
            if not tds or key_idx >= len(tds):
                continue
            key = _norm_key(text_of(tds[key_idx]), key_prefix)
            if not key or key in seen:
                continue
            result = ""
            if result_idx is not None and result_idx < len(tds):
                cell_text = _plain(text_of(tds[result_idx]))
                result = RESULT_TEXT.get(cell_text, "")
                if not result:
                    result = extract_result(tds[result_idx]) or extract_result(tr)
            seen.add(key)
            links.append({"key": key, "result": result})
    return links


def parse_report_markdown(text: str, filename: str = "", key_prefix: str | None = None) -> dict:
    version = version_from_html(text, filename)
    title_m = re.search(r"^#\s+(.+)$", text, re.M)
    title = title_m.group(1).strip() if title_m else Path(filename).stem
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip() and not p.strip().startswith("#")]
    summary = paras[0][:500] if paras else ""
    conc = ""
    m = re.search(r"^#+\s*结论[^\n]*\n+(.+?)(?:\n#|\Z)", text, re.S | re.M)
    if m:
        conc = _plain(m.group(1))[:800]
    links: list[dict] = []
    seen: set[str] = set()
    for m in TC_KEY_RE.finditer(text):
        key = _norm_key(m.group(1), key_prefix)
        if not key or key in seen:
            continue
        window = text[max(0, m.start() - 80) : m.end() + 80]
        result = ""
        rm = re.search(r"(通过|失败|不通过|跳过|阻塞|暂停|未测|不测)", window)
        if rm:
            result = RESULT_TEXT[rm.group(1)]
        elif not re.search(r"(用例|TC-|###|####)", window):
            continue
        seen.add(key)
        links.append({"key": key, "result": result})
    return {
        "version": version,
        "title": title,
        "summary": summary,
        "conclusion": conc or summary,
        "links": links,
    }


def parse_file(path: Path, key_prefix: str | None = None, kind: str = "auto") -> dict:
    raw = path.read_text(encoding="utf-8", errors="replace")
    suffix = path.suffix.lower()
    if kind == "case" or (kind == "auto" and "用例" in path.name):
        if suffix in {".md", ".markdown"}:
            return {"version": version_from_filename(path.name), "title": path.stem, "cases": []}
        return parse_case_html(raw, path.name, key_prefix)
    if suffix in {".md", ".markdown"}:
        return parse_report_markdown(raw, path.name, key_prefix)
    return parse_report_html(raw, path.name, key_prefix)


# --------------- case-baseline & report section extraction ---------------

BASELINE_LABEL_RE = re.compile(
    r"(?:用例基线|依据用例(?:版本)?|用例版本)\s*[:：]?\s*([^\n<]{0,240})",
    re.I,
)
CASE_FILE_VER_RE = re.compile(
    r"黑盒测试用例[^\n<]{0,80}?[_ ]v(\d+(?:\.\d+){1,3})",
    re.I,
)
CASE_VER_PHRASE_RE = re.compile(
    r"(?:黑盒测试用例|用例)\s*v(\d+(?:\.\d+){1,3})",
    re.I,
)
ACCORDING_CASE_VER_RE = re.compile(
    r"按用例\s*v(\d+(?:\.\d+){1,3})",
    re.I,
)
FULL_CASE_KEY_RE = re.compile(
    r"\b(TC-[A-Z0-9]+-\d{1,4}(?:-\d{1,3})?)\b",
    re.I,
)


def _first_version(text: str | None) -> str | None:
    if not text:
        return None
    m = VERSION_RE.search(text)
    if not m:
        return None
    return normalize_version(m.group(0))


def infer_based_on_case_version(text: str, filename: str = "") -> str | None:
    """Best-effort parse of the case-collection version a report was based on."""
    blob = text or ""

    if "<" in blob and ("用例基线" in blob or "用例版本" in blob or "依据用例" in blob):
        try:
            soup = BeautifulSoup(blob, "lxml")
        except Exception:
            soup = None
        if soup:
            for th in soup.find_all(["th", "td", "b", "strong"]):
                label = th.get_text(" ", strip=True)
                if not any(k in label for k in ("用例基线", "依据用例", "用例版本")):
                    continue
                chunk = label
                sib = th.find_next_sibling(["td", "th"])
                if sib and label in ("用例基线", "依据用例", "依据用例版本", "用例版本"):
                    chunk = sib.get_text(" ", strip=True)
                elif "：" in label or ":" in label:
                    chunk = re.split(r"[:：]", label, maxsplit=1)[-1]
                ver = _first_version(chunk)
                if ver:
                    return ver

    m = BASELINE_LABEL_RE.search(blob)
    if m:
        ver = _first_version(m.group(1))
        if ver:
            return ver

    m = CASE_FILE_VER_RE.search(blob)
    if m:
        return normalize_version("v" + m.group(1))

    m = CASE_VER_PHRASE_RE.search(blob)
    if m:
        return normalize_version("v" + m.group(1))

    m = ACCORDING_CASE_VER_RE.search(blob)
    if m:
        return normalize_version("v" + m.group(1))

    name = Path(filename or "").name
    if name and "用例" in name and not any(k in name for k in ("推演", "报告")):
        ver = version_from_filename(name, default="")
        return ver or None
    return None


def parse_pending_notes(html: str) -> list[str]:
    if not html or "pending" not in html:
        return []
    soup = BeautifulSoup(html, "lxml")
    box = soup.select_one(".pending")
    if not box:
        return []
    items = [_plain(li.get_text(" ", strip=True)) for li in box.select("li")]
    items = [t for t in items if t]
    if items:
        return items
    clone = BeautifulSoup(str(box), "lxml")
    for tag in clone.find_all(["b", "strong", "h3", "h4"]):
        tag.decompose()
    leftover = text_of(clone)
    return [leftover] if leftover else []


def case_seq_from_key(key: str) -> str:
    if not key:
        return ""
    text = key.strip()
    m = re.search(r"TC-[A-Z0-9]+-(\d{1,4})(?:-(\d{1,3}))?$", text, re.I)
    if m:
        seq = str(int(m.group(1)))
        if m.group(2):
            seq = f"{seq}-{m.group(2)}"
        return seq
    m = re.search(r"(\d{1,4})(?:-(\d{1,3}))?$", text)
    if not m:
        return key
    seq = str(int(m.group(1))) if m.group(1).isdigit() else m.group(1)
    if m.group(2):
        seq = f"{seq}-{m.group(2)}"
    return seq


def key_lookup_aliases(key: str) -> list[str]:
    aliases: list[str] = []
    if not key:
        return aliases
    key = key.strip()
    aliases.append(key)
    aliases.append(key.upper())
    aliases.append(key.lower())
    seq = case_seq_from_key(key)
    padded = None
    m = re.search(r"(\d{1,4})(?:-(\d{1,3}))?$", key)
    if m:
        padded = m.group(1).zfill(3)
        if m.group(2):
            padded = f"{padded}-{m.group(2)}"
    for token in filter(None, {seq, padded, m.group(0) if m else None}):
        aliases.extend(
            [
                token,
                f"#{token}",
                f"case-{token}",
                f"case_{token}",
                f"TC-{token}",
            ]
        )
        if token.isdigit():
            aliases.extend(
                [
                    str(int(token)),
                    f"#{int(token)}",
                    f"case-{int(token)}",
                ]
            )
    # unique, keep order
    seen: set[str] = set()
    out: list[str] = []
    for a in aliases:
        if not a:
            continue
        k = a.lower()
        if k not in seen:
            seen.add(k)
            out.append(a)
    return out


def _clean_fragment(el: Tag) -> str:
    clone = BeautifulSoup(str(el), "lxml")
    root = clone.body or clone
    for tag in root.find_all(["script", "style"]):
        tag.decompose()
    inner = root.decode_contents() if hasattr(root, "decode_contents") else str(el)
    return inner.strip()


def _outer_fragment(el: Tag) -> str:
    clone = BeautifulSoup(str(el), "lxml")
    root = clone.body or clone
    for tag in root.find_all("script"):
        tag.decompose()
    node = next((c for c in root.children if getattr(c, "name", None)), None)
    return str(node).strip() if node is not None else _clean_fragment(el)


def extract_style_text(soup: BeautifulSoup) -> str:
    parts: list[str] = []
    for style in soup.find_all("style"):
        css = style.get_text("\n") or ""
        if css.strip():
            parts.append(css)
    return "\n\n".join(parts)


DEFAULT_FRAGMENT_CSS = """
:root { --bg:#F4F6F9; --surface:#FFFFFF; --text:#1A2332; --muted:#5B6575; --border:#E4E8EE; }
body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Noto Sans SC","Microsoft YaHei",sans-serif;font-size:14px;line-height:1.55;color:var(--text);background:var(--bg)}
table{border-collapse:collapse;width:100%}
th,td{border:1px solid var(--border);padding:8px 10px;vertical-align:top;text-align:left}
code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;background:#EEF2F7;padding:1px 6px;border-radius:4px}
"""

FRAGMENT_CHROME_CSS = """
html,body{margin:0;}
body{padding:16px 18px 24px;}
body>.case,body>article.case,body>section.case{margin:0;}
"""


def build_fragment_page(section_html: str, css: str = "", title: str = "") -> str:
    if not (section_html or "").strip():
        return ""
    style = (css or "").strip() or DEFAULT_FRAGMENT_CSS
    title_safe = html_lib.escape(title or "推演结果")
    return (
        "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{title_safe}</title>"
        f"<style>{style}\n{FRAGMENT_CHROME_CSS}</style>"
        f"</head><body>{section_html}</body></html>"
    )


def _fields_from_case_block(el: Tag) -> list[dict]:
    fields: list[dict] = []
    for table in el.find_all("table"):
        for tr in table.find_all("tr"):
            cells = tr.find_all(["th", "td"])
            if len(cells) >= 2:
                label = text_of(cells[0])
                value_el = cells[1]
                if not label:
                    continue
                fields.append(
                    {
                        "label": label,
                        "value_text": text_of(value_el),
                        "value_html": _clean_fragment(value_el),
                    }
                )
    return fields


def _block_matches_key(el: Tag, key: str, aliases: list[str]) -> bool:
    ident = (el.get("id") or "").strip()
    ident_l = ident.lower()
    for a in aliases:
        if ident_l == a.lower() or ident_l.endswith("-" + a.lower()):
            return True
    classes = " ".join(el.get("class") or []).lower()
    if "toc" in classes or "目录" in (ident or ""):
        return False
    head = ""
    h = el.find(["h2", "h3", "h4", "header"])
    if h:
        head = text_of(h)
    # Only id + heading, not the whole body (TOC / index cards mention every key)
    blob = f"{ident} {head}"
    key_u = key.upper()
    if key_u and key_u in blob.upper():
        return True
    seq = case_seq_from_key(key)
    tokens = [
        rf"#{re.escape(seq)}(?!\d)",
        rf"\b{re.escape(key)}\b",
        rf"\bcase[-_]{re.escape(seq)}\b",
    ]
    if seq.isdigit():
        tokens.append(rf"#{int(seq)}(?!\d)")
    for pat in tokens:
        if re.search(pat, blob, re.I):
            return True
    return False



_STYLE_TAG_RE = re.compile(r"<style\b[^>]*>(.*?)</style>", re.I | re.S)
_CASE_START_RE = re.compile(
    r"<(?:section|article|div)\b(?=[^>]*\b(?:class|id)\s*=)[^>]*?"
    r"(?:class\s*=\s*([\"'])[^\"']*\bcase\b[^\"']*\1"
    r"|id\s*=\s*([\"'])case[-_][^\"']*\2)[^>]*>",
    re.I,
)
_OPEN_TAG_RE = re.compile(r"<([A-Za-z][A-Za-z0-9:-]*)\b", re.S)
_CLOSE_TAG_RE = re.compile(r"</([A-Za-z][A-Za-z0-9:-]*)\s*>", re.I)
_ANY_OPEN_RE = re.compile(r"<([A-Za-z][A-Za-z0-9:-]*)\b[^>]*>", re.S)
_ID_ATTR_RE = re.compile(
    r"""\sid\s*=\s*(['"])([^"']+)\1""",
    re.I,
)


def extract_style_text_from_raw(html: str) -> str:
    """Collect <style> blocks without parsing the whole document."""
    if not html:
        return ""
    parts = [m.group(1) for m in _STYLE_TAG_RE.finditer(html)]
    return "\n\n".join(p for p in parts if p and p.strip())


def _slice_preamble_html(html: str) -> str:
    """HTML before the first case section; header meta lives here."""
    if not html:
        return ""
    m = _CASE_START_RE.search(html)
    if m:
        return html[: m.start()]
    # Large reports without a recognizable case still have the header at the top.
    return html if len(html) <= 262144 else html[:262144]


def _element_span(html: str, start: int) -> tuple[int, int] | None:
    """Return [start, end) of the element whose opening '<' is at start."""
    if start < 0 or start >= len(html) or html[start] != "<":
        return None
    opened = _OPEN_TAG_RE.match(html, start)
    if not opened:
        return None
    name = opened.group(1).lower()
    gt = html.find(">", opened.end())
    if gt < 0:
        return None
    if html[gt - 1] == "/":
        return (start, gt + 1)
    depth = 1
    i = gt + 1
    n = len(html)
    raw_close = f"</{name}"
    while i < n:
        lt = html.find("<", i)
        if lt < 0:
            return None
        if html.startswith("<!--", lt):
            end = html.find("-->", lt + 4)
            if end < 0:
                return None
            i = end + 3
            continue
        closer = _CLOSE_TAG_RE.match(html, lt)
        if closer:
            if closer.group(1).lower() == name:
                depth -= 1
                if depth == 0:
                    return (start, closer.end())
            i = closer.end()
            continue
        opener = _ANY_OPEN_RE.match(html, lt)
        if not opener:
            i = lt + 1
            continue
        tname = opener.group(1).lower()
        raw = opener.group(0)
        if tname in {"script", "style", "textarea"}:
            m_end = re.search(rf"</{re.escape(tname)}\s*>", html[opener.end() :], re.I)
            if not m_end:
                return None
            i = opener.end() + m_end.end()
            continue
        if tname == name and not raw.rstrip().endswith("/>") and not raw.endswith("/>"):
            depth += 1
        i = opener.end()
    return None


def _find_id_tag_start(html: str, ident: str) -> int:
    pat = re.compile(
        rf"""(?is)<(?=[^>]*\sid\s*=\s*(['\"]){re.escape(ident)}\1)[A-Za-z][A-Za-z0-9:-]*\b[^>]*>"""
    )
    m = pat.search(html)
    return m.start() if m else -1


def _slice_case_section_html(html: str, case_key: str) -> str:
    """Cut out the single case element by id so we do not parse the whole report."""
    if not html or not case_key:
        return ""
    for ident in key_lookup_aliases(case_key):
        start = _find_id_tag_start(html, ident)
        if start < 0:
            continue
        span = _element_span(html, start)
        if span:
            return html[span[0] : span[1]]
    return ""


def _iter_case_section_html(html: str):
    """Yield raw HTML for each top-level case section."""
    if not html:
        return
    last_end = 0
    for m in _CASE_START_RE.finditer(html):
        if m.start() < last_end:
            continue
        span = _element_span(html, m.start())
        if not span:
            continue
        last_end = span[1]
        yield html[span[0] : span[1]]


def _finalize_case_detail(found: Tag, css: str, case_key: str) -> dict:
    _rewrite_case_heading(found)
    _strip_review_chrome_fields(found)
    heading = ""
    h = found.find(["h2", "h3", "h4", "header"])
    if h:
        heading = text_of(h)
    result = extract_result(found)
    anchor = found.get("id") or ""
    section_html = _outer_fragment(found)
    return {
        "found": True,
        "anchor": anchor,
        "html": section_html,
        "fragment_page": build_fragment_page(section_html, css, title=heading or case_key),
        "text": text_of(found),
        "fields": _fields_from_case_block(found),
        "result": result,
        "heading": heading,
    }


def index_report_case_details(html: str, key_prefix: str | None = None) -> dict:
    """Parse header, CSS, and every case section once for persistence."""
    header = extract_report_header_meta(html)
    css = extract_style_text_from_raw(html)
    cases: list[dict] = []
    seen: set[str] = set()
    for raw in _iter_case_section_html(html):
        soup = BeautifulSoup(raw, "lxml")
        found = soup.select_one("section.case, article.case, div.case, .case")
        if found is None:
            found = soup.find(True)
        if found is None:
            continue
        key = _heading_key(found, key_prefix)
        detail = _finalize_case_detail(found, css, key or "")
        if key:
            if key in seen:
                continue
            seen.add(key)
        detail["key"] = key or ""
        cases.append(detail)
    return {"header": header, "css": css, "cases": cases}


def extract_report_case_detail(html: str, case_key: str) -> dict:
    """Pull the per-case section out of a review HTML report."""
    empty = {
        "found": False,
        "anchor": "",
        "html": "",
        "fragment_page": "",
        "text": "",
        "fields": [],
        "result": "",
        "heading": "",
    }
    if not html or not case_key:
        return empty
    sliced = _slice_case_section_html(html, case_key)
    soup = BeautifulSoup(sliced or html, "lxml")
    aliases = key_lookup_aliases(case_key)

    found: Tag | None = None
    for a in aliases:
        el = soup.find(id=re.compile(rf"^{re.escape(a)}$", re.I))
        if el:
            found = el
            break
        # id="TC-OPA-001" already covered; some wrap in section
    if found is None:
        candidates = soup.select("section.case, article.case, div.case, .case")
        for el in candidates:
            if _block_matches_key(el, case_key, aliases):
                found = el
                break
    if found is None:
        candidates = soup.select("section, article")
        for el in candidates:
            if _block_matches_key(el, case_key, aliases):
                found = el
                break
    if found is None:
        # last resort: any element whose id looks like the case
        for el in soup.find_all(id=True):
            if _block_matches_key(el, case_key, aliases):
                found = el
                break
    if found is None:
        return empty

    css = extract_style_text_from_raw(html) if sliced else extract_style_text(soup)
    return _finalize_case_detail(found, css, case_key)


def detect_app_platforms(text: str, title: str = "", filename: str = "") -> list[str]:
    """Classify an APP review report as android, ios, or both."""
    meta = text[:20000] if text else ""
    # Prefer the official "范围" sentence when present
    m = re.search(r"范围\s*[:：]?\s*([^\n]{0,400})", meta)
    scope = m.group(1) if m else ""
    probe = " ".join(filter(None, [scope, title, Path(filename or "").name, meta[:4000]]))

    if re.search(r"仅\s*iOS|只推\s*iOS|仅\s*ios", probe, re.I):
        return ["ios"]
    if re.search(r"仅\s*安卓|仅\s*Android|只推\s*安卓|只推\s*Android", probe, re.I):
        return ["android"]

    no_ios = bool(re.search(r"不推\s*iOS|不含\s*iOS|不测\s*iOS", probe, re.I))
    no_android = bool(re.search(r"不推\s*安卓|不推\s*Android|不含\s*安卓", probe, re.I))
    if no_ios and not no_android:
        return ["android"]
    if no_android and not no_ios:
        return ["ios"]

    has_ios = bool(re.search(r"\biOS\b|苹果|iPhone", probe, re.I))
    has_android = bool(re.search(r"安卓|\bAndroid\b", probe, re.I))
    if has_ios and not has_android:
        return ["ios"]
    if has_android and not has_ios:
        return ["android"]
    return ["android", "ios"]


def is_app_review(title: str = "", filename: str = "", typ: str = "") -> bool:
    blob = f"{title} {Path(filename or '').name} {typ}"
    if typ and typ not in {"frontend_review", ""}:
        return False
    return bool(re.search(r"(?<![A-Za-z])APP(?![A-Za-z])|安卓|\bAndroid\b|\biOS\b", blob, re.I))


# ---- case document preamble / priority stats / report header meta ----

# Rows kept in the review-detail table only; heading/chrome outside the table is unchanged.
KEPT_REVIEW_LABELS = {
    "推演链路",
    "前端链路",
    "后端链路",
    "APP链路",
    "安卓链路",
    "iOS链路",
    "ios链路",
    "推演结果",
    "不通过原因",
    "不通过/跳过原因",
    "跳过原因",
    "备注",
    "备注/证据",
}

_HEADING_SEQ_RE = re.compile(
    r"^(#{1,6}[ \t]+)?#?(\d{1,4})(?!\d)(.*)$",
    re.S,
)
_ALREADY_HASH_SEQ_RE = re.compile(r"^(#{1,6}[ \t]+)?#\d")


def count_untested_cases(html: str) -> int:
    """Count case cards marked 不测; ignore kpi chips and other non-card marks."""
    if not html or "data-skip" not in html:
        return 0
    soup = BeautifulSoup(html, "lxml")
    seen: set[int] = set()
    count = 0
    for el in soup.select("article.case[data-skip], .case[data-skip]"):
        if el.find_parent(class_="kpi-row"):
            continue
        classes = el.get("class") or []
        if el.name != "article" and "case" not in classes:
            continue
        ident = id(el)
        if ident in seen:
            continue
        seen.add(ident)
        count += 1
    return count


def build_priority_stats(priority_values: list[str], untested: int = 0) -> dict:
    """priority_values is one entry per case in the version (empty string allowed)."""
    total = len(priority_values)
    counts: dict[str, int] = {}
    for raw in priority_values:
        label = (raw or "").strip()
        if not label:
            continue
        counts[label] = counts.get(label, 0) + 1

    def sort_key(name: str) -> tuple:
        order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
        return (order.get(name, 100), name)

    priorities = []
    for name in sorted(counts, key=sort_key):
        count = counts[name]
        percent = round(count / total * 100, 1) if total else 0
        priorities.append({"priority": name, "count": count, "percent": percent})
    return {
        "total": total,
        "priorities": priorities,
        "untested": int(untested or 0),
    }


def _normalize_meta_label(label: str) -> str:
    return re.sub(r"\s+", " ", (label or "").strip()).rstrip("：:").strip()


def _is_kept_review_label(label: str) -> bool:
    text = _normalize_meta_label(label)
    if not text:
        return False
    if text in KEPT_REVIEW_LABELS:
        return True
    if text.startswith("链路推演"):
        return True
    if text.startswith("不通过原因") or text.startswith("不通过/跳过原因"):
        return True
    if text.startswith("备注"):
        return True
    return False


def _format_heading_seq(text: str) -> str:
    raw = text or ""
    if _ALREADY_HASH_SEQ_RE.match(raw.lstrip("\n")):
        # still format if leading whitespace-only prefix
        m_lead = re.match(r"^([ \t]*)(.*)$", raw, re.S)
        if m_lead and _ALREADY_HASH_SEQ_RE.match(m_lead.group(2)):
            return raw
    m = _HEADING_SEQ_RE.match(raw)
    if not m:
        return raw
    prefix, num, rest = m.group(1) or "", m.group(2), m.group(3) or ""
    if raw[len(prefix) :].startswith("#"):
        return raw
    return f"{prefix}#{num}{rest}"


def _rewrite_case_heading(el: Tag) -> None:
    heading = el.find(["h2", "h3", "h4", "header"])
    if heading is None:
        return
    # Prefer a bare .num chip when present (e.g. <span class="num">1</span>)
    num_el = heading.find(class_="num")
    if num_el is not None:
        current = text_of(num_el)
        if re.fullmatch(r"\d{1,4}", current or ""):
            num_el.clear()
            num_el.append(f"#{current}")
            return
    for node in heading.contents:
        if isinstance(node, NavigableString) and str(node).strip():
            raw = str(node)
            lead = re.match(r"^(\s*)(.*)$", raw, re.S)
            if not lead:
                break
            updated = _format_heading_seq(lead.group(2))
            if updated != lead.group(2):
                node.replace_with(lead.group(1) + updated)
            break


def _strip_review_chrome_fields(el: Tag) -> None:
    for tr in list(el.find_all("tr")):
        cells = tr.find_all(["th", "td"], recursive=False)
        if not cells:
            cells = tr.find_all(["th", "td"])
        if not cells:
            continue
        if not _is_kept_review_label(text_of(cells[0])):
            tr.decompose()
    for field in list(el.select(".field")):
        k = field.select_one(".k") or field.find(["dt", "th", "strong", "b"])
        label = text_of(k) if k else ""
        if label and not _is_kept_review_label(label):
            field.decompose()
    for table in list(el.find_all("table")):
        if not table.find("tr"):
            table.decompose()


def apply_review_table_keep_list(section_html: str, fields: list | None = None) -> tuple[str, list]:
    """Re-apply the in-table keep-list to stored HTML/fields (heading/chrome unchanged)."""
    kept_fields = [
        item
        for item in (fields or [])
        if isinstance(item, dict) and _is_kept_review_label(str(item.get("label") or ""))
    ]
    html = section_html or ""
    if not html.strip():
        return html, kept_fields
    soup = BeautifulSoup(html, "lxml")
    root = soup.body or soup
    _strip_review_chrome_fields(root)
    if soup.body:
        html = soup.body.decode_contents()
    else:
        html = str(soup)
    return html.strip(), kept_fields


REVIEW_DETAIL_FIELD_NAMES = ("推演链路", "推演结果", "不通过原因", "备注")
REVIEW_EMPTY_VALUE = "—"

REVIEW_CARD_CSS = """
section.case, .review-card {
  background:#FFFFFF;border:1px solid #E4E8EE;border-radius:12px;
  box-shadow:0 1px 2px rgba(16,24,40,.06),0 1px 3px rgba(16,24,40,.08);
  margin:0;padding:0;overflow:hidden;
}
section.case[data-result="不通过"], .review-card[data-result="不通过"] {
  border-color:#FECACA;border-left:4px solid #F87171;
}
section.case[data-result="跳过"], .review-card[data-result="跳过"],
section.case[data-result="不测"], .review-card[data-result="不测"] {
  border-color:#FDBA74;border-left:4px solid #F59E0B;
}
section.case[data-result="通过"], .review-card[data-result="通过"] {
  border-left:4px solid #86EFAC;
}
section.case h3, .review-card h3, .review-card-title {
  margin:0;padding:12px 16px;font-size:15px;line-height:22px;font-weight:700;
  background:#F8FAFC;border-bottom:1px solid #E4E8EE;
  overflow-wrap:anywhere;word-break:break-word;
}
section.case[data-result="不通过"] h3, .review-card[data-result="不通过"] h3,
.review-card[data-result="不通过"] .review-card-title { background:#FEF2F2; }
section.case[data-result="跳过"] h3, section.case[data-result="不测"] h3,
.review-card[data-result="跳过"] h3, .review-card[data-result="不测"] h3,
.review-card[data-result="跳过"] .review-card-title,
.review-card[data-result="不测"] .review-card-title { background:#FFF7ED; }
.review-card table, section.case table, .review-card-table {
  border-collapse:collapse;width:100%;margin:0;table-layout:fixed;
}
.review-card th, .review-card td, section.case th, section.case td,
.review-card-table th, .review-card-table td {
  border:1px solid #E4E8EE;padding:8px 10px;vertical-align:top;text-align:left;
  overflow-wrap:anywhere;word-break:break-word;
}
.review-card th, section.case th, .review-card-table th {
  width:140px;background:#F6F7F9;color:#1A2332;font-weight:600;
}
.review-card tr:last-child th, .review-card tr:last-child td,
section.case tr:last-child th, section.case tr:last-child td,
.review-card-table tr:last-child th, .review-card-table tr:last-child td { border-bottom:0; }
.review-card th, .review-card td, section.case th, section.case td,
.review-card-table th, .review-card-table td { border-left:0;border-right:0; }
.review-card .ok, section.case .ok { color:#0a7a2f;font-weight:600; }
.review-card .fail, section.case .fail { color:#b00020;font-weight:600; }
.review-card .skip, section.case .skip { color:#b45309;font-weight:600; }
.review-card code, section.case code {
  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  font-size:12px;background:#EEF2F7;padding:1px 6px;border-radius:4px;
}
"""

_DETAIL_LABEL_RE = (
    r"不通过/跳过原因|不通过原因|跳过原因|备注/证据|"
    r"推演链路|后端链路|前端链路|APP链路|安卓链路|iOS链路|ios链路|链路推演|"
    r"推演结果|用例标题|推演用例编号|备注|标题"
)
_LINE_LABEL_RE = re.compile(
    rf"^\s*(?:\*\*|__)?(?P<label>{_DETAIL_LABEL_RE})(?:\*\*|__)?\s*[:：]?\s*(?P<rest>.*)$"
)
_BACKTICK_RE = re.compile(r"`([^`]+)`")
_HTML_TAG_RE = re.compile(r"<[a-zA-Z][^>]*>")


def _canonical_review_kind(label: str) -> str | None:
    text = _normalize_meta_label(label)
    if not text:
        return None
    if text in {
        "推演链路",
        "后端链路",
        "前端链路",
        "APP链路",
        "安卓链路",
        "iOS链路",
        "ios链路",
    } or text.startswith("链路推演"):
        return "推演链路"
    if text == "推演结果":
        return "推演结果"
    if (
        text.startswith("不通过原因")
        or text.startswith("不通过/跳过原因")
        or text == "跳过原因"
        or text.startswith("跳过原因")
    ):
        return "不通过原因"
    if text == "备注" or text == "备注/证据" or text.startswith("备注"):
        return "备注"
    if text in {"用例标题", "标题"} or text.startswith("用例标题"):
        return "_title"
    return None


def _is_empty_review_value(text: str) -> bool:
    value = (text or "").strip()
    return (not value) or value == REVIEW_EMPTY_VALUE


def _text_to_html(text: str) -> str:
    raw = text or ""
    if _is_empty_review_value(raw):
        return ""
    escaped = html_lib.escape(raw).replace("\r\n", "\n").replace("\r", "\n")
    escaped = escaped.replace("\n", "<br/>\n")
    return _BACKTICK_RE.sub(r"<code>\1</code>", escaped)


def _inner_html_value(raw: str) -> str:
    html = (raw or "").strip()
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    root = soup.body or soup
    for tag in root.find_all(["script", "style"]):
        tag.decompose()

    def _cell_inner(cell: Tag) -> str:
        return cell.decode_contents().strip() if hasattr(cell, "decode_contents") else text_of(cell)

    start = html.lstrip().lower()
    cell = None
    if start.startswith("<td") or start.startswith("<th"):
        cell = root.find(["td", "th"])
    if cell is None:
        children = [
            child
            for child in list(root.children)
            if getattr(child, "name", None) or str(child).strip()
        ]
        if len(children) == 1 and getattr(children[0], "name", None) in {"td", "th"}:
            cell = children[0]
        elif len(children) == 1 and getattr(children[0], "name", None) == "table":
            tds = children[0].find_all(["td", "th"], recursive=True)
            if len(tds) == 1:
                cell = tds[0]
    if cell is not None:
        return _cell_inner(cell)
    if hasattr(root, "decode_contents"):
        return root.decode_contents().strip()
    return html


def _field_text_and_html(item: dict | None = None, value_el: Tag | None = None, text: str = "", html: str = "") -> tuple[str, str]:
    if item and isinstance(item, dict):
        html = str(item.get("value_html") or html or "")
        text = str(item.get("value_text") or item.get("value") or text or "")
        if html.strip():
            html = _inner_html_value(html)
            if not text.strip():
                text = text_of(BeautifulSoup(html, "lxml"))
        elif text.strip():
            html = _text_to_html(text)
        return text.strip(), html
    if value_el is not None:
        html = _inner_html_value(str(value_el))
        text = text_of(value_el)
        return (text or "").strip(), html
    if html and _HTML_TAG_RE.search(html):
        html = _inner_html_value(html)
        if not text:
            text = text_of(BeautifulSoup(html, "lxml"))
        return (text or "").strip(), html
    text = (text or "").strip()
    return text, _text_to_html(text)


def _remember_review_value(store: dict, kind: str | None, text: str, html: str) -> None:
    value_text = (text or "").strip()
    value_html = (html or "").strip()
    if kind == "_title":
        if value_text and "_title" not in store:
            store["_title"] = value_text
        return
    if kind not in REVIEW_DETAIL_FIELD_NAMES:
        return
    current = store.get(kind)
    if current and not _is_empty_review_value(current.get("value_text") or ""):
        return
    store[kind] = {
        "label": kind,
        "value_text": value_text,
        "value_html": value_html,
        "value": value_text,
    }


def _collect_fields_from_items(store: dict, fields: list | None) -> None:
    for item in fields or []:
        if not isinstance(item, dict):
            continue
        kind = _canonical_review_kind(str(item.get("label") or ""))
        text, html = _field_text_and_html(item)
        _remember_review_value(store, kind, text, html)


def _collect_fields_from_html(store: dict, section_html: str) -> str:
    heading = ""
    html = section_html or ""
    if not html.strip() or not _HTML_TAG_RE.search(html):
        return heading
    soup = BeautifulSoup(html, "lxml")
    root = soup.body or soup
    head = root.find(["h2", "h3", "h4", "header"])
    if head:
        heading = text_of(head)
    for tr in root.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        if len(cells) < 2:
            continue
        kind = _canonical_review_kind(text_of(cells[0]))
        text, html = _field_text_and_html(value_el=cells[1])
        _remember_review_value(store, kind, text, html)
    for field in root.select(".field"):
        k = field.select_one(".k") or field.find(["dt", "th", "strong", "b"])
        v = field.select_one(".v") or field.find(["dd", "td"])
        if k is None:
            continue
        kind = _canonical_review_kind(text_of(k))
        if v is not None:
            text, html = _field_text_and_html(value_el=v)
        else:
            clone = BeautifulSoup(str(field), "lxml")
            node = clone.body or clone
            label_el = node.select_one(".k") or node.find(["dt", "th", "strong", "b"])
            if label_el:
                label_el.decompose()
            text, html = _field_text_and_html(text=text_of(node), html=_clean_fragment(node))
        _remember_review_value(store, kind, text, html)
    return heading


def _collect_fields_from_prose(store: dict, source: str) -> None:
    if not (source or "").strip():
        return
    work = source
    if "<" in work:
        work = re.sub(r"(?i)<br\s*/?>", "\n", work)
        work = re.sub(r"(?i)</(p|div|li|h[1-6]|tr|section|article)>", "\n", work)
        work = re.sub(r"(?i)<(p|div|li|h[1-6]|tr|section|article)[^>]*>", "", work)
        work = re.sub(r"(?i)</?(strong|b|em|span|font)[^>]*>", "", work)
        work = BeautifulSoup(work, "lxml").get_text("\n")
    lines = work.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    current: str | None = None
    buf: list[str] = []

    def flush() -> None:
        nonlocal current, buf
        if current:
            value = "\n".join(buf).strip().lstrip("：:").strip()
            _remember_review_value(store, current, value, _text_to_html(value))
        current = None
        buf = []

    for line in lines:
        raw = line.strip()
        m = _LINE_LABEL_RE.match(raw)
        if m:
            kind = _canonical_review_kind(m.group("label"))
            flush()
            current = kind
            rest = (m.group("rest") or "").strip()
            buf = [rest] if rest else []
            continue
        if current and not buf and raw[:1] in {":", "："}:
            rest = raw.lstrip("：:").strip()
            if rest:
                buf = [rest]
            continue
        if current:
            buf.append(line)
    flush()


def _result_mark(result: str, result_label: str, field_text: str) -> str:
    blob = f"{result} {result_label} {field_text}"
    if result == "fail" or "不通过" in blob or "失败" in blob:
        return "不通过"
    if result in {"skip", "untested"} or "跳过" in blob or "不测" in blob:
        return "跳过"
    if result == "pass" or "通过" in blob:
        return "通过"
    return (result_label or result or "").strip()


def _result_cell_class(mark: str) -> str:
    if mark == "不通过":
        return "fail"
    if mark in {"跳过", "不测"}:
        return "skip"
    if mark == "通过":
        return "ok"
    return ""


def _build_review_card_html(heading: str, fields: list[dict], result_mark: str) -> str:
    title = html_lib.escape(heading or "推演详情")
    mark_attr = html_lib.escape(result_mark, quote=True)
    rows = []
    for item in fields:
        label = html_lib.escape(item["label"])
        raw_html = (item.get("value_html") or "").strip()
        text = (item.get("value_text") or item.get("value") or "").strip()
        if raw_html and not _is_empty_review_value(text):
            cell = raw_html
        elif not _is_empty_review_value(text):
            cell = _text_to_html(text)
        else:
            cell = REVIEW_EMPTY_VALUE
            text = REVIEW_EMPTY_VALUE
        css = ""
        if item["label"] == "推演结果":
            klass = _result_cell_class(result_mark or _result_mark("", "", text))
            if klass:
                css = f' class="{klass}"'
        elif item["label"] == "推演链路" and cell != REVIEW_EMPTY_VALUE:
            css = ' class="chain"'
        rows.append(f"<tr><th>{label}</th><td{css}>{cell}</td></tr>")
    body = "\n".join(rows)
    return (
        f'<section class="case review-card" data-result="{mark_attr}">'
        f"<h3>{title}</h3>"
        f"<table class=\"review-card-table\">\n{body}\n</table>"
        "</section>"
    )


def _source_has_review_labels(source: str) -> bool:
    if not (source or "").strip():
        return False
    if "<" in source:
        soup = BeautifulSoup(source, "lxml")
        root = soup.body or soup
        for tr in root.find_all("tr"):
            cells = tr.find_all(["th", "td"])
            if cells and _canonical_review_kind(text_of(cells[0])):
                return True
        for field in root.select(".field"):
            k = field.select_one(".k") or field.find(["dt", "th", "strong", "b"])
            if k and _canonical_review_kind(text_of(k)):
                return True
        probe = text_of(root)
    else:
        probe = source
    return any(_LINE_LABEL_RE.match(line.strip()) for line in probe.splitlines())


def _collect_unlabeled_body(store: dict, section_html: str, text: str) -> None:
    """If 推演链路 is empty and the body has no field labels, use it as the chain."""
    current = store.get("推演链路") or {}
    if not _is_empty_review_value(current.get("value_text") or ""):
        return
    if _source_has_review_labels(section_html) or _source_has_review_labels(text):
        return
    html = (section_html or "").strip()
    value_text = ""
    value_html = ""
    if html:
        soup = BeautifulSoup(html, "lxml")
        root = soup.body or soup
        for head in root.find_all(["h2", "h3", "h4", "header"]):
            head.decompose()
        value_text = text_of(root).strip()
        value_html = root.decode_contents().strip() if hasattr(root, "decode_contents") else html
        if value_html:
            value_html = _inner_html_value(value_html)
    if _is_empty_review_value(value_text) and (text or "").strip():
        value_text = text.strip()
        value_html = _text_to_html(value_text)
    if not _is_empty_review_value(value_text):
        _remember_review_value(store, "推演链路", value_text, value_html)


def build_review_detail_view(
    section_html: str = "",
    fields: list | None = None,
    *,
    heading: str = "",
    text: str = "",
    result: str = "",
    result_label: str = "",
    fallback_title: str = "",
) -> tuple[str, list, str]:
    """Normalize stored review HTML/fields/text into the v0.0.2 4-field card.

    Returns (section_html, fields, heading). Every display field uses a
    canonical Chinese label; missing values are "—". Extra labels such as
    用例标题 are not emitted as rows.
    """
    store: dict = {}
    _collect_fields_from_items(store, fields)
    html_heading = _collect_fields_from_html(store, section_html or "")
    _collect_fields_from_prose(store, section_html or "")
    _collect_fields_from_prose(store, text or "")
    _collect_unlabeled_body(store, section_html or "", text or "")

    display_heading = (heading or "").strip() or html_heading.strip() or str(store.get("_title") or "").strip() or (fallback_title or "").strip()
    display_heading = _format_heading_seq(display_heading)

    result_field = store.get("推演结果") or {}
    if _is_empty_review_value(result_field.get("value_text") or ""):
        fallback = (result_label or "").strip()
        if not fallback:
            fallback = {
                "pass": "通过",
                "fail": "失败",
                "skip": "跳过",
                "blocked": "阻塞",
                "untested": "未测",
            }.get((result or "").strip(), (result or "").strip())
        if fallback:
            _remember_review_value(store, "推演结果", fallback, _text_to_html(fallback))

    mark = _result_mark(
        result or "",
        result_label or "",
        (store.get("推演结果") or {}).get("value_text") or "",
    )
    out_fields = []
    for name in REVIEW_DETAIL_FIELD_NAMES:
        item = store.get(name) or {}
        value_text = (item.get("value_text") or item.get("value") or "").strip()
        value_html = (item.get("value_html") or "").strip()
        if _is_empty_review_value(value_text):
            value_text = REVIEW_EMPTY_VALUE
            value_html = ""
        out_fields.append(
            {
                "label": name,
                "value": value_text,
                "value_text": value_text,
                "value_html": value_html,
            }
        )

    has_content = any(
        not _is_empty_review_value(item["value_text"]) for item in out_fields
    ) or bool(display_heading) or bool((section_html or "").strip()) or bool((text or "").strip())
    if not has_content:
        return "", [], display_heading
    return _build_review_card_html(display_heading, out_fields, mark), out_fields, display_heading


def _value_after_label(node: Tag, label_el: Tag) -> str:
    clone = BeautifulSoup(str(node), "lxml")
    root = clone.body or clone
    target = root.find(["b", "strong"])
    if target:
        target.decompose()
    return text_of(root).lstrip("：: ").strip()


def _fields_from_doc_meta(soup: BeautifulSoup) -> list[dict]:
    fields: list[dict] = []
    seen: set[str] = set()

    def add(label: str, value: str) -> None:
        lab = _normalize_meta_label(label)
        val = (value or "").strip()
        if not lab or not val:
            return
        key = lab
        if key in seen:
            return
        seen.add(key)
        fields.append({"label": lab, "value": val})

    for meta in soup.select(".meta"):
        for tr in meta.select("table tr"):
            cells = tr.find_all(["th", "td"])
            if len(cells) >= 2:
                add(text_of(cells[0]), text_of(cells[1]))
        for node in meta.find_all(["p", "div", "li", "span"]):
            if node.find("table"):
                continue
            if node.find_parent("table"):
                continue
            label_el = node.find(["b", "strong"], recursive=False)
            if label_el is None:
                # one level down, e.g. GMA <div><b>…</b> value</div> already is this node
                continue
            # skip containers that themselves wrap several labeled children
            labeled_kids = [
                child
                for child in node.find_all(["p", "div"], recursive=False)
                if child.find(["b", "strong"], recursive=False)
            ]
            if labeled_kids:
                continue
            add(text_of(label_el), _value_after_label(node, label_el))
    return fields


def _is_case_list_table(table: Tag) -> bool:
    if table.find_parent(class_=["skip-sum", "meta", "card", "hero", "pending", "summary", "hero-meta"]):
        return False
    classes = " ".join(table.get("class") or []).lower()
    ident = (table.get("id") or "").lower()
    if "cases" in classes or ident in {"cases", "case-table", "case-list"}:
        return True
    first = table.find("tr")
    if not first:
        return False
    headers = " ".join(text_of(c) for c in first.find_all(["th", "td"]))
    row_count = len(table.find_all("tr"))
    has_id = any(token in headers for token in ("编号", "用例描述", "标题", "序号"))
    has_body = any(token in headers for token in ("优先级", "步骤", "预期结果", "前置", "操作步骤"))
    return row_count >= 5 and has_id and has_body


def extract_case_document_info(html: str) -> dict:
    """Preamble of a case HTML document, excluding the case list itself."""
    empty = {"available": False, "title": "", "fields": [], "fragment_page": ""}
    if not html or not html.strip():
        return empty
    soup = BeautifulSoup(html, "lxml")
    title = ""
    h1 = soup.select_one(".hero h1") or soup.find("h1")
    if h1:
        title = text_of(h1)
    if not title:
        title_el = soup.find("title")
        title = text_of(title_el) if title_el else ""

    fields = _fields_from_doc_meta(soup)

    work = BeautifulSoup(html, "lxml")
    for tag in work.find_all("script"):
        tag.decompose()
    for el in work.select(".toolbar, .kpi-row"):
        el.decompose()
    for el in list(work.select("article.case")):
        el.decompose()
    for el in list(work.select(".case")):
        if el.find_parent(class_=["skip-sum", "meta", "hero", "card", "summary", "pending"]):
            continue
        el.decompose()
    for table in list(work.find_all("table")):
        if _is_case_list_table(table):
            table.decompose()

    body = work.body or work
    section_html = body.decode_contents() if hasattr(body, "decode_contents") else str(body)
    # Drop leftover empty wrappers that only contained the case list
    section_html = section_html.strip()
    text_probe = text_of(body)
    if not text_probe and not fields:
        return {**empty, "title": title}

    fragment_page = build_fragment_page(
        section_html,
        extract_style_text(soup),
        title=title or "用例信息",
    )
    available = bool(fields or (fragment_page and text_probe))
    return {
        "available": available,
        "title": title,
        "fields": fields,
        "fragment_page": fragment_page if available else "",
    }


def _header_meta_kind(label: str) -> str | None:
    text = _normalize_meta_label(label)
    if not text:
        return None
    if text.startswith("分支"):
        return "branch"
    if text == "仓库" or (text.startswith("仓库") and "分支" not in text):
        return "repo"
    if text == "参与人" or text.startswith("参与人"):
        return "participants"
    return None


def _iter_preamble_roots(soup: BeautifulSoup) -> list[Tag]:
    roots: list[Tag] = []
    for sel in (".hero", ".meta"):
        for el in soup.select(sel):
            roots.append(el)
    # Intro content before the first case section, so case-body mentions are ignored
    body = soup.body or soup
    wrap = soup.select_one(".wrap") or body
    for child in list(wrap.children):
        if not getattr(child, "name", None):
            continue
        classes = child.get("class") or []
        if child.name in {"section", "article"} and (
            "case" in classes or (child.get("id") or "").lower().startswith("case")
        ):
            break
        if "case" in classes and child.name in {"section", "article", "div"}:
            break
        if child in roots:
            continue
        roots.append(child)
    return roots


def _collect_header_pairs(root: Tag) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    # tables (typical GMA .meta)
    for tr in root.find_all("tr"):
        # skip rows inside a later case if root is a large wrap — callers pass preamble only
        if tr.find_parent(class_="case"):
            continue
        cells = tr.find_all(["th", "td"])
        if len(cells) >= 2:
            pairs.append((text_of(cells[0]), text_of(cells[1])))
    # <p><strong>仓库</strong>：...
    for node in root.find_all(["p", "div", "li"]):
        if node.find_parent(class_="case"):
            continue
        if node.find("table") or node.find_parent("table"):
            continue
        label_el = node.find(["b", "strong"], recursive=False)
        if label_el is None:
            continue
        labeled_kids = [
            child
            for child in node.find_all(["p", "div"], recursive=False)
            if child.find(["b", "strong"], recursive=False)
        ]
        if labeled_kids:
            continue
        pairs.append((text_of(label_el), _value_after_label(node, label_el)))
    return pairs


def extract_report_header_meta(html: str) -> dict:
    """Parse 仓库 / 分支 / 参与人 from a review report header. Never invent values."""
    empty = {"repo": "", "branch": "", "participants": ""}
    if not html or not html.strip():
        return dict(empty)
    soup = BeautifulSoup(_slice_preamble_html(html), "lxml")
    found = dict(empty)
    # Prefer .meta (table rows or <p><strong>…</strong> lines), then other preamble
    roots: list[Tag] = []
    roots.extend(soup.select(".meta"))
    for root in _iter_preamble_roots(soup):
        if root not in roots:
            roots.append(root)
    for root in roots:
        for label, value in _collect_header_pairs(root):
            kind = _header_meta_kind(label)
            if not kind:
                continue
            val = re.sub(r"\s+", " ", value or "").strip()
            if val and not found[kind]:
                found[kind] = val
        if found["repo"] and found["branch"] and found["participants"]:
            break
    return found

def repair_misparsed_card_steps(db) -> int:
    """Rewrite steps only when the stored value was copied from preconditions."""
    from app.config import FILES_DIR
    from app.models import TestCase, TestCaseVersion

    rows = (
        db.query(TestCaseVersion, TestCase)
        .join(TestCase, TestCase.id == TestCaseVersion.case_id)
        .filter(TestCaseVersion.steps == TestCaseVersion.preconditions)
        .filter(TestCaseVersion.steps != "")
        .all()
    )
    if not rows:
        return 0
    grouped: dict[str, list] = {}
    for version, case in rows:
        if version.source_file:
            grouped.setdefault(version.source_file, []).append((version, case))
    parsed_cache: dict[str, dict[str, dict]] = {}
    updated = 0
    for source_file, group in grouped.items():
        path = FILES_DIR / source_file
        if not path.is_file():
            continue
        if source_file not in parsed_cache:
            html = path.read_text(encoding="utf-8")
            prefix = None
            first_key = group[0][1].key if group else ""
            parts = (first_key or "").split("-")
            if len(parts) >= 3:
                prefix = "-".join(parts[:-1])
            parsed_cache[source_file] = {
                rec["key"]: rec
                for rec in parse_case_html(html, path.name, key_prefix=prefix).get("cases") or []
            }
        by_key = parsed_cache[source_file]
        for version, case in group:
            rec = by_key.get(case.key)
            if not rec:
                continue
            new_steps = rec.get("steps") or ""
            if not new_steps or new_steps == version.steps:
                continue
            version.steps = new_steps
            updated += 1
    if updated:
        db.commit()
    return updated

def repair_case_section_text(db) -> int:
    """Re-parse source HTML and rewrite preconditions/steps/expected when they differ."""
    from app.config import FILES_DIR
    from app.models import TestCase, TestCaseVersion

    rows = (
        db.query(TestCaseVersion, TestCase)
        .join(TestCase, TestCase.id == TestCaseVersion.case_id)
        .filter(TestCaseVersion.source_file.isnot(None))
        .filter(TestCaseVersion.source_file != "")
        .all()
    )
    if not rows:
        return 0
    grouped: dict[str, list] = {}
    for version, case in rows:
        grouped.setdefault(version.source_file, []).append((version, case))
    updated = 0
    fields = ("preconditions", "steps", "expected")
    for source_file, group in grouped.items():
        path = FILES_DIR / source_file
        if not path.is_file():
            continue
        prefix = None
        first_key = group[0][1].key if group else ""
        parts = (first_key or "").split("-")
        if len(parts) >= 3:
            prefix = "-".join(parts[:-1])
        by_key = {
            rec["key"]: rec
            for rec in parse_case_html(path.read_text(encoding="utf-8"), path.name, key_prefix=prefix).get("cases") or []
        }
        for version, case in group:
            rec = by_key.get(case.key)
            if not rec:
                continue
            changed = False
            for field in fields:
                new = rec.get(field) or ""
                if not new or new == getattr(version, field):
                    continue
                setattr(version, field, new)
                changed = True
            if changed:
                updated += 1
    if updated:
        db.commit()
    return updated
