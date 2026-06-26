# -*- coding: utf-8 -*-
"""
Scimago Journal Rank(SJR) 쿼타일 매칭.

scimago_sjr/scimagojr YYYY.csv (세미콜론 구분, 소수점 콤마) 를 읽어
ISSN -> {quartile, sjr, categories, title} 인덱스를 만들고,
OpenAlex 결과 레코드(issn_l)에 Q1~Q4 를 붙인다.

데이터 출처: scimagojr.com — 사용자가 수동 다운로드(자동수집 Cloudflare 차단).
라이선스: SJR 데이터는 CC BY-NC. 연구 내부용.
"""
import csv
import glob
import os
import re

SCIMAGO_DIR = os.path.join(os.path.dirname(__file__), "scimago_sjr")


def find_csv(folder=SCIMAGO_DIR):
    """scimago_sjr/ 에서 가장 최신 'scimagojr*.csv' 경로 반환 (없으면 None)."""
    cands = glob.glob(os.path.join(folder, "scimagojr*.csv"))
    if not cands:
        return None
    # 파일명에 연도가 있으면 큰 연도 우선
    def yr(p):
        m = re.search(r"(\d{4})", os.path.basename(p))
        return int(m.group(1)) if m else 0
    return sorted(cands, key=yr, reverse=True)[0]


def norm_issn(s):
    """'1542-4863' / '15424863' -> '15424863' (하이픈 제거, 대문자, 8자리)."""
    if not s:
        return ""
    s = re.sub(r"[^0-9Xx]", "", str(s)).upper()
    return s


def _to_float(s):
    if not s:
        return None
    try:
        return float(str(s).replace(".", "").replace(",", ".")) if "," in str(s) else float(s)
    except ValueError:
        return None


def _parse(reader):
    """csv.DictReader -> {issn_norm: {'quartile','sjr','categories','title'}}."""
    index = {}
    for row in reader:
        q = (row.get("SJR Best Quartile") or "").strip()
        if q not in ("Q1", "Q2", "Q3", "Q4"):
            q = ""  # '-' 등은 미분류
        rec = {
            "quartile": q,
            "sjr": _to_float(row.get("SJR")),
            "categories": (row.get("Categories") or "").strip(),
            "title": (row.get("Title") or "").strip(),
        }
        for raw in (row.get("Issn") or "").split(","):
            key = norm_issn(raw)
            if len(key) == 8 and key not in index:
                index[key] = rec
    return index


def _index_from_text(text):
    """CSV 텍스트 -> 인덱스. 구분자(; 또는 ,) 자동 감지."""
    import io
    first = text.split("\n", 1)[0]
    delim = ";" if first.count(";") >= first.count(",") else ","
    return _parse(csv.DictReader(io.StringIO(text), delimiter=delim))


def load_index(path=None):
    """로컬 Scimago CSV -> 인덱스 (한 저널의 ISSN 여러 개를 모두 키로)."""
    path = path or find_csv()
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return _index_from_text(fh.read())


def load_index_from_text(text):
    """업로드된 CSV 텍스트 -> 인덱스 (Streamlit file_uploader 용)."""
    return _index_from_text(text or "")


def category_quartile(categories, want_substr):
    """
    Scimago Categories('분야명 (Q1); 분야명 (Q2)') 에서
    want_substr 포함 카테고리의 쿼타일을 찾아 반환 (없으면 '').
    """
    if not categories or not want_substr:
        return ""
    for part in categories.split(";"):
        m = re.search(r"(.*?)\((Q[1-4])\)", part)
        if m and want_substr.lower() in m.group(1).lower():
            return m.group(2)
    return ""


def annotate(records, index, field_category=None):
    """
    records 각 항목에 sj_quartile / sj_sjr / sj_cats / (sj_field_q) 추가.
    field_category: 카테고리명(부분일치)을 주면 그 분야의 쿼타일도 따로 채움.
    """
    for r in records:
        hit = index.get(norm_issn(r.get("issn_l", "")))
        if not hit:
            for alt in (r.get("issn") or []):
                hit = index.get(norm_issn(alt))
                if hit:
                    break
        if hit:
            r["sj_quartile"] = hit["quartile"]
            r["sj_sjr"] = hit["sjr"]
            r["sj_cats"] = hit["categories"]
            if field_category:
                r["sj_field_q"] = category_quartile(hit["categories"], field_category)
        else:
            r["sj_quartile"] = ""
            r["sj_sjr"] = None
            r["sj_cats"] = ""
            if field_category:
                r["sj_field_q"] = ""
    return records
