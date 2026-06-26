# -*- coding: utf-8 -*-
"""
OpenAlex 클라이언트 — 검색 / 초록 복원 / 저자·기관 조회 / group_by 집계 / 분류체계.

polite-pool(mailto) 호출, hit/miss/error 분류, 초록 inverted-index 복원(OpenAlex 표준).
Streamlit 비의존 — 순수 함수 모듈이라 단독 테스트/재사용 가능.
"""
import re
import time
import requests

import config as C

# ORCID: 0000-0000-0000-000X (마지막 자리 X 가능)
_ORCID_RE = re.compile(r"\d{4}-\d{4}-\d{4}-\d{3}[\dXx]")
# OpenAlex author id: A + 숫자
_AID_RE = re.compile(r"\bA\d{6,}\b")


def _extract_orcid(text):
    """이름/URL/숫자에서 ORCID 추출 → '0000-0000-0000-000X' 또는 None."""
    m = _ORCID_RE.search(text or "")
    if m:
        return m.group(0).upper()
    digits = re.sub(r"[^0-9Xx]", "", text or "")
    if len(digits) == 16:
        d = digits.upper()
        return f"{d[0:4]}-{d[4:8]}-{d[8:12]}-{d[12:16]}"
    return None


def _extract_author_id(text):
    m = _AID_RE.search(text or "")
    return m.group(0) if m else None


def _clean_doi(text):
    """https://doi.org/10.x/y, doi:10.x/y → 10.x/y."""
    t = (text or "").strip()
    t = re.sub(r"(?i)^\s*(https?://(dx\.)?doi\.org/|doi:\s*)", "", t)
    return t.strip().strip("/")


# ============================================================
# 저수준 호출
# ============================================================
def _get(path, params):
    """OpenAlex GET. (ok, payload_or_reason) 반환. probe_openalex 패턴."""
    url = f"{C.OPENALEX_BASE}/{path}"
    params = dict(params)
    params["mailto"] = C.MAILTO
    try:
        r = requests.get(url, params=params, timeout=C.REQUEST_TIMEOUT)
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:80]}"
    if r.status_code != 200:
        return False, f"HTTP {r.status_code}: {r.text[:120]}"
    return True, r.json()


def _short_id(openalex_url):
    """'https://openalex.org/A5021817508' -> 'A5021817508'."""
    if not openalex_url:
        return ""
    return openalex_url.rstrip("/").split("/")[-1]


# ============================================================
# 초록 복원
# ============================================================
def reconstruct_abstract(inverted_index):
    """abstract_inverted_index({단어: [위치...]}) -> 원문 문자열."""
    if not inverted_index:
        return ""
    positions = []
    for word, idxs in inverted_index.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort(key=lambda x: x[0])
    return " ".join(w for _, w in positions)


# ============================================================
# work 정규화 (UI/내보내기가 쓰는 평평한 dict)
# ============================================================
def clean_abstract(abstract, title=""):
    """초록 정제: 앞에 중복 삽입된 제목 제거 + 공백 정리. (#18 / 토픽모델링용)"""
    a = (abstract or "").strip()
    t = (title or "").strip()
    if a and t and len(t) > 8 and a.lower().startswith(t.lower()):
        a = a[len(t):].lstrip(" .:-—")
    return " ".join(a.split())


def _title_in_abstract(abstract, title):
    a = (abstract or "").strip().lower()
    t = (title or "").strip().lower()
    return bool(a) and len(t) > 8 and a.startswith(t[:40])


def normalize_work(w):
    auths = w.get("authorships") or []
    authors = [(a.get("author") or {}).get("display_name", "") for a in auths]
    authors = [a for a in authors if a]

    has_orcid = any((a.get("author") or {}).get("orcid") for a in auths)
    countries, institutions = [], []
    for a in auths:
        for inst in (a.get("institutions") or []):
            cc = inst.get("country_code")
            if cc and cc not in countries:
                countries.append(cc)
            nm = inst.get("display_name")
            if nm and nm not in institutions:
                institutions.append(nm)

    src = (w.get("primary_location") or {}).get("source") or {}
    topic = (w.get("primary_topic") or {}) or {}
    oa = w.get("open_access") or {}
    doi = w.get("doi") or ""
    abstract = reconstruct_abstract(w.get("abstract_inverted_index"))
    title = w.get("title") or "(제목 없음)"

    return {
        "openalex_id": _short_id(w.get("id")),
        "openalex_url": w.get("id") or "",
        "title": title,
        "year": w.get("publication_year"),
        "authors": authors,
        "author_str": _author_short(authors),
        "n_authors": len(auths),
        "has_orcid": has_orcid,
        "countries": countries,
        "has_country": bool(countries),
        "institutions": institutions,
        "venue": src.get("display_name") or "",
        "source_id": _short_id(src.get("id")),
        "issn_l": src.get("issn_l") or "",
        "issn": src.get("issn") or [],
        # Scimago SJR 쿼타일 — app 에서 scimago.annotate 로 채움
        "sj_quartile": "",
        "sj_sjr": None,
        "sj_cats": "",
        # 저널 지표 — search_works 가 /sources 배치 조회로 채움
        "j_if2y": None,      # OpenAlex 2년 평균 피인용수 (IF 유사 지표)
        "j_hindex": None,    # 저널 h-index
        "j_doaj": None,      # DOAJ 등재 여부(오픈액세스 품질 신호)
        "cited_by": w.get("cited_by_count", 0),
        "is_oa": bool(oa.get("is_oa")),
        "oa_status": oa.get("oa_status") or "",
        "topic": topic.get("display_name") or "",
        "doi": doi,
        "doi_url": doi if doi.startswith("http") else (f"https://doi.org/{doi}" if doi else ""),
        "abstract": abstract,
        "abstract_clean": clean_abstract(abstract, title),
        "title_in_abstract": _title_in_abstract(abstract, title),
        "data_source": "OpenAlex",
    }


def _author_short(authors, n=3):
    if not authors:
        return ""
    if len(authors) <= n:
        return ", ".join(authors)
    return ", ".join(authors[:n]) + f" 외 {len(authors) - n}명"


# ============================================================
# 필터 조립
# ============================================================
def _prep_query(query, phrase):
    q = (query or "").strip()
    if q and phrase and not (q.startswith('"') and q.endswith('"')):
        q = f'"{q}"'
    return q


def build_filter(year_from=None, year_to=None, field_filter="",
                 author_id="", scope="title_abstract", query="", lang=None,
                 institution_id=""):
    """
    OpenAlex works filter 문자열 조립.
    scope: 'title' | 'title_abstract' | 'all'
      - title          -> filter=title.search:q
      - title_abstract -> filter=title_and_abstract.search:q  (정밀, 기본)
      - all            -> query 는 filter 가 아니라 search= 로 (search_works 에서 처리)
    query 는 _prep_query 로 따옴표 처리된 상태로 들어온다.
    institution_id: OpenAlex 기관 id(I…) 또는 ROR URL(https://ror.org/…).
    """
    parts = []
    if field_filter:
        parts.append(field_filter)
    if year_from and year_to:
        parts.append(f"publication_year:{year_from}-{year_to}")
    elif year_from:
        parts.append(f"publication_year:>{year_from - 1}")
    elif year_to:
        parts.append(f"publication_year:<{year_to + 1}")
    if author_id:
        parts.append(f"authorships.author.id:{_short_id(author_id)}")
    if institution_id:
        key = "ror" if "ror.org" in institution_id else "id"
        val = institution_id if key == "ror" else _short_id(institution_id)
        parts.append(f"authorships.institutions.{key}:{val}")
    if lang:
        parts.append(f"language:{lang}")
    if query and scope == "title":
        parts.append(f"title.search:{query}")
    elif query and scope == "title_abstract":
        parts.append(f"title_and_abstract.search:{query}")
    return ",".join(parts)


# ============================================================
# 저널 지표 — /sources 배치 조회 (2년 평균 피인용 ≈ IF, h-index, DOAJ)
# ============================================================
def fetch_source_stats(source_ids):
    """source 단축ID 리스트 -> {id: {'if2y','hindex','doaj'}}. 50개씩 배치."""
    out = {}
    ids = [s for s in dict.fromkeys(source_ids) if s]  # 중복 제거, 순서 유지
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        ok, payload = _get("sources", {
            "filter": "ids.openalex:" + "|".join(chunk),
            "select": "id,issn_l,is_in_doaj,summary_stats",
            "per-page": 50,
        })
        if not ok:
            continue
        for s in payload.get("results", []):
            ss = s.get("summary_stats") or {}
            out[_short_id(s.get("id"))] = {
                "if2y": round(ss.get("2yr_mean_citedness", 0) or 0, 2),
                "hindex": ss.get("h_index"),
                "doaj": bool(s.get("is_in_doaj")),
            }
        time.sleep(C.SLEEP_BETWEEN)
    return out


# ============================================================
# 검색
# ============================================================
SELECT_FIELDS = (
    "id,doi,title,publication_year,authorships,primary_location,"
    "cited_by_count,open_access,abstract_inverted_index,primary_topic"
)


def search_works(query="", year_from=None, year_to=None, field_filter="",
                 author_id="", sort="relevance_score:desc", lang=None,
                 scope="title_abstract", phrase=False, max_results=None,
                 with_journal_stats=True, institution_id=""):
    """
    works 검색. (ok, {'total','records','truncated'}) 반환.
    scope: 'title' | 'title_abstract'(기본) | 'all'(제목+초록+본문)
    phrase: True 면 query 를 따옴표로 묶어 정확한 구문 일치.
    with_journal_stats: True 면 결과 저널의 2년평균피인용(IF유사)·h-index·DOAJ 보강.
    institution_id: 기관 id(I…)/ROR 로 소속 필터.
    """
    max_results = max_results or C.MAX_RESULTS_CAP
    q = _prep_query(query, phrase)
    filt = build_filter(year_from, year_to, field_filter, author_id,
                        scope, q, lang, institution_id)

    params = {
        "filter": filt,
        "sort": sort,
        "per-page": C.PER_PAGE,
        "select": SELECT_FIELDS,
        "cursor": "*",
    }
    # scope=all 일 때만 query 를 broad search= 로
    if q and scope == "all":
        params["search"] = q
    # 검색어가 전혀 없으면 relevance 정렬은 의미 없음 → 최신순
    if sort.startswith("relevance_score") and not q:
        params["sort"] = "publication_date:desc"

    records = []
    total = None
    cursor = "*"
    truncated = False

    while True:
        params["cursor"] = cursor
        ok, payload = _get("works", params)
        if not ok:
            return False, payload
        if total is None:
            total = payload.get("meta", {}).get("count", 0)
        for w in payload.get("results", []):
            records.append(normalize_work(w))
            if len(records) >= max_results:
                break
        if len(records) >= max_results:
            truncated = (total or 0) > len(records)
            break
        cursor = payload.get("meta", {}).get("next_cursor")
        if not cursor or not payload.get("results"):
            break
        time.sleep(C.SLEEP_BETWEEN)

    # 저널 지표 보강
    if with_journal_stats and records:
        stats = fetch_source_stats([r["source_id"] for r in records])
        for r in records:
            st = stats.get(r["source_id"])
            if st:
                r["j_if2y"] = st["if2y"]
                r["j_hindex"] = st["hindex"]
                r["j_doaj"] = st["doaj"]

    return True, {"total": total or 0, "records": records, "truncated": truncated}


# ============================================================
# 저자 조회 — 이름 / ORCID / OpenAlex ID
# ============================================================
_AUTHOR_SELECT = "id,display_name,orcid,works_count,cited_by_count,last_known_institutions"


def _author_candidate(a):
    insts = a.get("last_known_institutions") or []
    inst = insts[0].get("display_name") if insts else ""
    country = insts[0].get("country_code") if insts else ""
    orcid = (a.get("orcid") or "").split("/")[-1]
    return {
        "id": _short_id(a.get("id")),
        "name": a.get("display_name", ""),
        "orcid": orcid,
        "works_count": a.get("works_count", 0),
        "cited_by_count": a.get("cited_by_count", 0),
        "institution": inst or "",
        "country": country or "",
    }


def lookup_authors(name, limit=8):
    """이름으로 OpenAlex author 후보 조회. (ok, [후보 dict...])."""
    ok, payload = _get("authors", {
        "search": name, "per-page": limit, "select": _AUTHOR_SELECT,
    })
    if not ok:
        return False, payload
    return True, [_author_candidate(a) for a in payload.get("results", [])]


def lookup_institutions(name, limit=8):
    """기관명으로 OpenAlex institution 후보 조회(autocomplete). (ok, [후보...])."""
    ok, payload = _get("autocomplete/institutions", {"q": name})
    if not ok:
        return False, payload
    out = []
    for a in payload.get("results", [])[:limit]:
        out.append({
            "id": _short_id(a.get("id")),
            "name": a.get("display_name", ""),
            "hint": a.get("hint") or "",        # 보통 국가/지역
            "works_count": a.get("works_count", 0),
            "ror": (a.get("external_id") or ""),  # ror URL (있으면)
        })
    return True, out


def resolve_author(text):
    """
    입력을 ORCID / OpenAlex ID / 이름으로 자동 판별해 저자 후보 반환.
    (ok, [후보...]). ORCID·ID 는 정확히 1명, 이름은 동명이인 여러 명.
    """
    t = (text or "").strip()
    if not t:
        return False, "빈 입력"
    orcid = _extract_orcid(t)
    if orcid:
        ok, payload = _get(f"authors/orcid:{orcid}", {"select": _AUTHOR_SELECT})
        if not ok:
            return False, f"ORCID 조회 실패({orcid}): {payload}"
        return True, [_author_candidate(payload)]
    aid = _extract_author_id(t)
    if aid:
        ok, payload = _get(f"authors/{aid}", {"select": _AUTHOR_SELECT})
        if not ok:
            return False, f"ID 조회 실패({aid}): {payload}"
        return True, [_author_candidate(payload)]
    return lookup_authors(t)


# ============================================================
# 연구자 분석 — 저자/기관 프로필 + 범용 group_by
# ============================================================
def entity_top(filter_str, group_by, top=15, exclude_id=""):
    """임의 filter + group_by 집계. (ok, [(label, count, short_id)...])."""
    ok, payload = _get("works", {"filter": filter_str, "group_by": group_by, "per-page": 200})
    if not ok:
        return False, payload
    rows = []
    for g in payload.get("group_by", []):
        key = g.get("key")
        if key in (None, "", "unknown"):
            continue
        sid = _short_id(key)
        if exclude_id and sid == _short_id(exclude_id):
            continue
        rows.append((g.get("key_display_name") or str(key), g.get("count", 0), sid))
    return True, (rows[:top] if top else rows)


def top_coauthors(author_id, top=15):
    """저자의 주요 공저자(해당 저자 제외). (ok, [(name, 공저수, id)...])."""
    aid = _short_id(author_id)
    return entity_top(f"authorships.author.id:{aid}", "authorships.author.id",
                      top=top, exclude_id=aid)


def fetch_author(author_id_or_orcid):
    """저자 프로필. (ok, dict) / (False, 사유). ORCID/ID/full-URL 모두 허용."""
    t = (author_id_or_orcid or "").strip()
    orcid = _extract_orcid(t)
    path = f"authors/orcid:{orcid}" if orcid else f"authors/{_short_id(t)}"
    ok, a = _get(path, {})
    if not ok:
        return False, f"저자 조회 실패: {a}"
    ss = a.get("summary_stats") or {}
    insts = a.get("last_known_institutions") or []
    affs = []
    for af in (a.get("affiliations") or []):
        inst = af.get("institution") or {}
        yrs = af.get("years") or []
        affs.append({
            "name": inst.get("display_name", ""),
            "country": inst.get("country_code", ""),
            "years": f"{min(yrs)}–{max(yrs)}" if yrs else "",
            "year_min": min(yrs) if yrs else None,
        })
    return True, {
        "id": _short_id(a.get("id")), "openalex_url": a.get("id") or "",
        "orcid": (a.get("orcid") or "").split("/")[-1],
        "name": a.get("display_name", ""),
        "works_count": a.get("works_count", 0), "cited_by_count": a.get("cited_by_count", 0),
        "h_index": ss.get("h_index"), "i10_index": ss.get("i10_index"),
        "mean_citedness2y": round(ss.get("2yr_mean_citedness", 0) or 0, 2),
        "last_institution": insts[0].get("display_name") if insts else "",
        "last_country": insts[0].get("country_code") if insts else "",
        "counts_by_year": [(c["year"], c.get("works_count", 0), c.get("cited_by_count", 0))
                           for c in (a.get("counts_by_year") or [])],
        "topics": [(t.get("display_name", ""), t.get("count", 0)) for t in (a.get("topics") or [])[:12]],
        "affiliations": affs,
    }


def fetch_institution(inst_id_or_ror):
    """기관 프로필. (ok, dict) / (False, 사유). ROR/ID/full-URL 허용."""
    t = (inst_id_or_ror or "").strip()
    path = f"institutions/ror:{t}" if "ror.org" in t else f"institutions/{_short_id(t)}"
    ok, i = _get(path, {})
    if not ok:
        return False, f"기관 조회 실패: {i}"
    ss = i.get("summary_stats") or {}
    geo = i.get("geo") or {}
    return True, {
        "id": _short_id(i.get("id")), "openalex_url": i.get("id") or "",
        "ror": i.get("ror") or "", "name": i.get("display_name", ""),
        "country_code": i.get("country_code") or "", "type": i.get("type") or "",
        "homepage": i.get("homepage_url") or "",
        "works_count": i.get("works_count", 0), "cited_by_count": i.get("cited_by_count", 0),
        "h_index": ss.get("h_index"), "i10_index": ss.get("i10_index"),
        "mean_citedness2y": round(ss.get("2yr_mean_citedness", 0) or 0, 2),
        "geo": {"city": geo.get("city", ""), "country": geo.get("country", ""),
                "lat": geo.get("latitude"), "lon": geo.get("longitude")},
        "counts_by_year": [(c["year"], c.get("works_count", 0), c.get("cited_by_count", 0))
                           for c in (i.get("counts_by_year") or [])],
        "topics": [(t.get("display_name", ""), t.get("count", 0)) for t in (i.get("topics") or [])[:12]],
        "associated": [(x.get("display_name", ""), x.get("relationship", ""), _short_id(x.get("id")))
                       for x in (i.get("associated_institutions") or [])],
    }


# ============================================================
# 분류 체계(taxonomy) — 도메인/필드/세분류 (수준-선택 분야 UI용)
# ============================================================
def fetch_taxonomy():
    """OpenAlex 분류 4계층. {domains:[(id,name)], fields:[(id,name,dom_id,dom_name)],
       subfields:[(id,name,field_id,field_name,dom_name)]}."""
    out = {"domains": [], "fields": [], "subfields": []}
    ok, d = _get("domains", {"per-page": 10})
    if ok:
        out["domains"] = [(_short_id(x["id"]), x["display_name"]) for x in d.get("results", [])]
    ok, f = _get("fields", {"per-page": 50})
    if ok:
        for x in f.get("results", []):
            dom = x.get("domain") or {}
            out["fields"].append((_short_id(x["id"]), x["display_name"],
                                  _short_id(dom.get("id")), dom.get("display_name", "")))
    cursor = "*"
    while cursor:
        ok, s = _get("subfields", {"per-page": 200, "cursor": cursor,
                                   "select": "id,display_name,field,domain"})
        if not ok:
            break
        for x in s.get("results", []):
            fld = x.get("field") or {}
            dom = x.get("domain") or {}
            out["subfields"].append((_short_id(x["id"]), x["display_name"],
                                     _short_id(fld.get("id")), fld.get("display_name", ""),
                                     dom.get("display_name", "")))
        cursor = s.get("meta", {}).get("next_cursor")
        if not s.get("results"):
            break
        time.sleep(C.SLEEP_BETWEEN)
    return out


# ============================================================
# DOI 로 단일 논문 조회
# ============================================================
def fetch_by_doi(doi):
    """DOI 로 논문 1편 조회. (ok, 정규화 record) / (False, 사유)."""
    clean = _clean_doi(doi)
    if not clean:
        return False, "빈 DOI"
    ok, payload = _get(f"works/doi:{clean}", {"select": SELECT_FIELDS})
    if not ok:
        return False, f"DOI 미발견({clean}): {payload}"
    return True, normalize_work(payload)


# ============================================================
# 연도별 집계 (Phase 2 대시보드용 — 다운로드 없이 group_by)
# ============================================================
def group_aggregate(group_by, query="", scope="title_abstract", phrase=False,
                    year_from=None, year_to=None, field_filter="", author_id="",
                    lang=None, top=15, institution_id=""):
    """
    검색 조건과 동일한 필터로 group_by 집계. (ok, [(label, count, key)...]).
    다운로드 없이 OpenAlex가 전체 매칭 집합을 집계 → 표시된 N건이 아니라 '전체' 동향.
    OpenAlex group_by 는 count 내림차순 정렬되어 옴.
    """
    q = _prep_query(query, phrase)
    filt = build_filter(year_from, year_to, field_filter, author_id, scope, q, lang,
                        institution_id)
    params = {"filter": filt, "group_by": group_by, "per-page": 200}
    if q and scope == "all":
        params["search"] = q
    ok, payload = _get("works", params)
    if not ok:
        return False, payload
    rows = []
    for g in payload.get("group_by", []):
        key = g.get("key")
        if key in (None, "", "unknown"):
            continue
        rows.append((g.get("key_display_name") or str(key), g.get("count", 0), key))
    rows.sort(key=lambda x: x[1], reverse=True)
    return True, (rows[:top] if top else rows)


def trend_by_year(query="", field_filter="", author_id="", lang=None,
                  year_from=None, year_to=None, scope="all", phrase=False):
    """연도별 출판 수 집계. (ok, [(year, count)...])."""
    q = _prep_query(query, phrase)
    filt = build_filter(year_from, year_to, field_filter, author_id,
                        scope, q, lang)
    params = {"filter": filt, "group_by": "publication_year"}
    if q and scope == "all":
        params["search"] = q
    ok, payload = _get("works", params)
    if not ok:
        return False, payload
    rows = [(g["key"], g["count"]) for g in payload.get("group_by", [])]
    rows.sort(key=lambda x: x[0])
    return True, rows
