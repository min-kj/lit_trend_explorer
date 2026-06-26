# -*- coding: utf-8 -*-
"""
KCI/RISS 병합 (#12) — OpenAlex가 못 잡는 한국 논문 보강.

RISS/KCI/DBpia 등에서 내려받은 RIS(.ris/.txt) 또는 Excel(.xlsx)을 파싱해
앱의 레코드 스키마로 변환하고, OpenAlex 결과와 DOI/제목으로 중복제거 후 병합한다.
병합분은 표·내보내기·토픽발견에 들어가지만 **동향 대시보드(OpenAlex group_by)에는 미포함**.
"""
import io
import re

# 앱이 기대하는 레코드 키 전부 — KCI 레코드도 동일 스키마로 채운다
RECORD_DEFAULTS = dict(
    openalex_id="", openalex_url="", title="", year=None, authors=[], author_str="",
    n_authors=0, has_orcid=False, countries=[], has_country=False, institutions=[], venue="",
    source_id="", issn_l="", issn=[], sj_quartile="", sj_sjr=None, sj_cats="",
    j_if2y=None, j_hindex=None, j_doaj=None, cited_by=0, is_oa=False, oa_status="",
    topic="", doi="", doi_url="", abstract="", abstract_clean="", title_in_abstract=False,
    data_source="KCI",
)


def _author_short(authors, n=3):
    if not authors:
        return ""
    return ", ".join(authors) if len(authors) <= n else ", ".join(authors[:n]) + f" 외 {len(authors)-n}명"


def _record(**kw):
    r = dict(RECORD_DEFAULTS)
    r.update(kw)
    r["authors"] = r["authors"] or []
    r["author_str"] = _author_short(r["authors"])
    r["n_authors"] = len(r["authors"])
    d = (r["doi"] or "").strip()
    r["doi"] = d
    r["doi_url"] = (d if d.startswith("http") else f"https://doi.org/{d}") if d else ""
    r["abstract"] = (r["abstract"] or "").strip()
    r["abstract_clean"] = r["abstract"]
    return r


# ============================================================
# RIS 파싱
# ============================================================
def parse_ris(text):
    recs, cur, last = [], None, None
    for line in (text or "").splitlines():
        m = re.match(r"^([A-Z][A-Z0-9])  - ?(.*)$", line)
        if not m:
            if cur is not None and last == "AB" and line.strip():
                cur["AB"] = (cur.get("AB", "") + " " + line.strip()).strip()
            continue
        tag, val = m.group(1), m.group(2).strip()
        if tag == "TY":
            cur, last = {"AU": []}, "TY"
        elif tag == "ER":
            if cur is not None:
                recs.append(cur)
            cur, last = None, None
        elif cur is not None:
            if tag == "AU":
                cur["AU"].append(val)
            elif tag == "AB":
                cur["AB"] = (cur.get("AB", "") + " " + val).strip()
            else:
                cur[tag] = val
            last = tag
    out = []
    for c in recs:
        year = None
        for t in ("PY", "Y1", "DA"):
            if c.get(t):
                mm = re.search(r"(\d{4})", c[t])
                if mm:
                    year = int(mm.group(1))
                    break
        out.append(_record(
            title=c.get("TI") or c.get("T1") or "",
            authors=c.get("AU", []),
            year=year,
            venue=c.get("JO") or c.get("JF") or c.get("T2") or "",
            doi=c.get("DO") or "",
            abstract=c.get("AB", ""),
        ))
    return [r for r in out if r["title"]]


# ============================================================
# Excel 파싱 (RISS/KCI 내보내기 — 컬럼명 자동 매핑)
# ============================================================
def parse_excel(data_bytes):
    import pandas as pd
    df = pd.read_excel(io.BytesIO(data_bytes))
    cols = {str(c).lower().strip(): c for c in df.columns}

    def pick(*names):
        for n in names:
            for lc, orig in cols.items():
                if n in lc:
                    return orig
        return None

    c_t = pick("제목", "논문명", "title", "article title")
    c_a = pick("저자", "author")
    c_y = pick("발행연도", "출판연도", "연도", "year", "pub")
    c_j = pick("학술지", "저널", "수록지", "journal", "source")
    c_d = pick("doi")
    c_ab = pick("초록", "abstract", "요약")
    out = []
    import pandas as pd  # noqa (notna)
    for _, row in df.iterrows():
        title = str(row[c_t]).strip() if c_t and pd.notna(row[c_t]) else ""
        if not title or title.lower() == "nan":
            continue
        authors = []
        if c_a and pd.notna(row[c_a]):
            authors = [a.strip() for a in re.split(r"[;,/·∙]", str(row[c_a])) if a.strip()]
        year = None
        if c_y and pd.notna(row[c_y]):
            mm = re.search(r"(\d{4})", str(row[c_y]))
            year = int(mm.group(1)) if mm else None
        out.append(_record(
            title=title, authors=authors, year=year,
            venue=str(row[c_j]).strip() if c_j and pd.notna(row[c_j]) else "",
            doi=str(row[c_d]).strip() if c_d and pd.notna(row[c_d]) else "",
            abstract=str(row[c_ab]).strip() if c_ab and pd.notna(row[c_ab]) else "",
        ))
    return out


def parse_upload(filename, data_bytes):
    """확장자로 RIS/Excel 분기. (records, 오류문자열|None)."""
    name = (filename or "").lower()
    try:
        if name.endswith((".xlsx", ".xls")):
            return parse_excel(data_bytes), None
        text = data_bytes.decode("utf-8-sig", "replace")
        return parse_ris(text), None
    except Exception as e:
        return [], f"{type(e).__name__}: {str(e)[:120]}"


# ============================================================
# 병합 (DOI·제목 중복제거)
# ============================================================
def _norm_doi(d):
    return re.sub(r"^https?://(dx\.)?doi\.org/", "", (d or "").lower()).strip().strip("/")


def _norm_title(t):
    return re.sub(r"[^a-z0-9가-힣]", "", (t or "").lower())


def merge(openalex_records, kci_records):
    """OpenAlex + KCI 병합, DOI→제목 순 중복제거. (merged, info)."""
    seen_doi = {_norm_doi(r["doi"]) for r in openalex_records if r.get("doi")}
    seen_title = {_norm_title(r["title"]) for r in openalex_records}
    merged = list(openalex_records)
    added = dup = 0
    for k in kci_records:
        nd, nt = _norm_doi(k["doi"]), _norm_title(k["title"])
        if (nd and nd in seen_doi) or (nt and nt in seen_title):
            dup += 1
            continue
        merged.append(k)
        added += 1
        if nd:
            seen_doi.add(nd)
        if nt:
            seen_title.add(nt)
    return merged, {"added": added, "dup": dup, "kci_total": len(kci_records)}
