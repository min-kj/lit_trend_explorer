# -*- coding: utf-8 -*-
"""
연구동향·선행연구 조사 도구 (lit_trend_explorer) — Streamlit 앱.

실행:  pip install -r requirements.txt  →  streamlit run app.py

OpenAlex 검색(제목·연도·저자·기관·분야·DOI) → 결과·초록 → 선별 → CSV/BibTeX/RIS/프롬프트 내보내기
+ 동향 대시보드(group_by 집계) + 토픽 발견(초록 LDA·rising terms). 전부 코드 집계 — LLM 추론 아님.
LLM 요약은 앱 밖(Claude Code)에서: 내보낸 CSV/프롬프트를 세션에 넘겨 처리.
"""
import os
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

# Streamlit Cloud: Secrets 에 OPENALEX_MAILTO 를 넣으면 공개 레포에 이메일 안 박아도 됨
try:
    for _k in st.secrets:
        if str(_k).startswith("OPENALEX_"):
            os.environ[str(_k)] = str(st.secrets[_k])
except Exception:
    pass

import config as C
import openalex_client as oa
import exporters as ex
import scimago
import analysis
import kci_merge

st.set_page_config(page_title="연구동향 조사", page_icon="📚", layout="wide")
st.markdown(
    "<style>html,body,[class*='css']{font-family:'Noto Sans KR','Segoe UI',sans-serif;}</style>",
    unsafe_allow_html=True,
)


# ============================================================
# 캐시 래퍼
# ============================================================
@st.cache_data(show_spinner=False, ttl=3600)
def cached_search(query, year_from, year_to, field_filter, author_id, sort, lang,
                  scope, phrase, max_results, institution_id):
    return oa.search_works(query=query, year_from=year_from, year_to=year_to,
                           field_filter=field_filter, author_id=author_id, sort=sort,
                           lang=lang, scope=scope, phrase=phrase, max_results=max_results,
                           institution_id=institution_id)


@st.cache_data(show_spinner=False, ttl=3600)
def cached_resolve_author(text):
    return oa.resolve_author(text)


@st.cache_data(show_spinner=False, ttl=3600)
def cached_institutions(name):
    return oa.lookup_institutions(name)


@st.cache_data(show_spinner=False, ttl=3600)
def cached_doi(doi):
    return oa.fetch_by_doi(doi)


@st.cache_data(show_spinner=False, ttl=3600)
def cached_agg(group_by, top, query, scope, phrase, year_from, year_to,
               field_filter, author_id, lang, institution_id):
    ok, rows = oa.group_aggregate(group_by=group_by, top=top, query=query, scope=scope,
                                  phrase=phrase, year_from=year_from, year_to=year_to,
                                  field_filter=field_filter, author_id=author_id,
                                  lang=lang, institution_id=institution_id)
    return rows if ok else []


@st.cache_resource(show_spinner=False)
def get_taxonomy():
    return oa.fetch_taxonomy()


def build_field_filter(selected, tax):
    """선택한 분야 엔티티(층위 혼합 가능)를 OpenAlex filter 조각으로 변환.
    selected: [(level, id, name)] (level='domain'|'field'|'subfield').
    단일 층위면 그 층위 키로 OR, 층위가 섞이면 전부 세분류로 내려 OR(한 필터 키).
    OpenAlex는 서로 다른 필터 키 사이 OR을 막아서(400) 세분류 정규화로 우회.
    반환: (field_filter, field_label, scimago_cat)."""
    if not selected:
        return "", "전체 분야", ""
    by = {"domain": [], "field": [], "subfield": []}
    names = []
    for lvl, eid, nm in selected:
        by[lvl].append(eid)
        names.append(nm)
    used = [lvl for lvl in ("domain", "field", "subfield") if by[lvl]]
    label = "분야: " + ", ".join(names)
    if len(used) == 1:  # 단일 층위 → 해당 키로 직접 OR (URL 짧음)
        lvl = used[0]
        key = {"domain": "primary_topic.domain.id", "field": "primary_topic.field.id",
               "subfield": "primary_topic.subfield.id"}[lvl]
        ids = by[lvl]
        cat = C.SUBFIELD_SCIMAGO_CAT.get(ids[0], "") if (lvl == "subfield" and len(ids) == 1) else ""
        return f"{key}:" + "|".join(ids), label, cat
    # 층위 혼합 → 모든 선택을 세분류 id 로 정규화 후 OR (세분류=가장 하위 공통분모)
    field_to_dom = {fid: dom for fid, _nm, dom, _dnm in tax["fields"]}
    sel_dom, sel_fld, sel_sub = set(by["domain"]), set(by["field"]), set(by["subfield"])
    sub_ids = [sid for sid, _n, fid, _fn, _dn in tax["subfields"]
               if sid in sel_sub or fid in sel_fld or field_to_dom.get(fid) in sel_dom]
    if not sub_ids:
        return "", "전체 분야", ""
    return "primary_topic.subfield.id:" + "|".join(sub_ids), label, ""


@st.cache_resource(show_spinner=False)
def get_scimago_local():
    path = scimago.find_csv()
    return (scimago.load_index(path) if path else {}), path


@st.cache_data(show_spinner=False)
def get_scimago_uploaded(data):
    return scimago.load_index_from_text(data.decode("utf-8-sig", "replace"))


@st.cache_data(show_spinner=False)
def parse_kci(filename, data):
    return kci_merge.parse_upload(filename, data)


@st.cache_data(show_spinner=False, ttl=3600)
def cached_author(aid):
    return oa.fetch_author(aid)


@st.cache_data(show_spinner=False, ttl=3600)
def cached_institution(iid):
    return oa.fetch_institution(iid)


@st.cache_data(show_spinner=False, ttl=3600)
def cached_coauthors(aid, top):
    ok, rows = oa.top_coauthors(aid, top)
    return rows if ok else []


@st.cache_data(show_spinner=False, ttl=3600)
def cached_entity_top(filt, gb, top):
    ok, rows = oa.entity_top(filt, gb, top)
    return rows if ok else []


# ============================================================
# 차트 헬퍼 (plotly)
# ============================================================
def chart_hbar(rows, title, color="#4C78A8"):
    if not rows:
        st.caption(f"{title} — 데이터 없음")
        return
    d = pd.DataFrame(rows, columns=["항목", "건수", "key"]).iloc[::-1]
    fig = px.bar(d, x="건수", y="항목", orientation="h", text="건수")
    fig.update_traces(textposition="outside", cliponaxis=False, marker_color=color)
    fig.update_layout(title=title, height=max(240, 26 * len(d) + 90),
                      margin=dict(l=8, r=28, t=44, b=8), yaxis_title=None, xaxis_title=None)
    st.plotly_chart(fig, use_container_width=True)


def chart_year(rows, title="연도별 출판 추이"):
    if not rows:
        st.caption("연도 데이터 없음")
        return
    d = pd.DataFrame(rows, columns=["항목", "건수", "key"])
    d["연도"] = pd.to_numeric(d["항목"], errors="coerce")
    d = d.dropna(subset=["연도"]).sort_values("연도")
    fig = px.area(d, x="연도", y="건수", markers=True)
    fig.update_traces(line_color="#4C78A8")
    fig.update_layout(title=title, height=320, margin=dict(l=8, r=8, t=44, b=8),
                      xaxis_title=None, yaxis_title="건수")
    st.plotly_chart(fig, use_container_width=True)


def chart_oa(rows):
    if not rows:
        st.caption("OA 데이터 없음")
        return
    label = {"true": "오픈액세스", "false": "비OA"}
    d = pd.DataFrame([(label.get(str(k).lower(), str(k)), c) for (lbl, c, k) in rows],
                     columns=["구분", "건수"])
    fig = px.pie(d, names="구분", values="건수", hole=0.5,
                 color_discrete_sequence=["#54A24B", "#BAB0AC"])
    fig.update_layout(title="오픈액세스 비율", height=300, margin=dict(l=8, r=8, t=44, b=8))
    st.plotly_chart(fig, use_container_width=True)


def chart_counts_year(counts, title):
    """저자/기관 counts_by_year → 논문수(막대)+피인용(선) 이중축."""
    if not counts:
        st.caption("연도 데이터 없음")
        return
    d = pd.DataFrame(counts, columns=["연도", "논문수", "피인용"]).sort_values("연도")
    fig = go.Figure()
    fig.add_trace(go.Bar(x=d["연도"], y=d["논문수"], name="논문수", marker_color="#4C78A8"))
    fig.add_trace(go.Scatter(x=d["연도"], y=d["피인용"], name="피인용", yaxis="y2",
                             mode="lines+markers", line=dict(color="#E45756")))
    fig.update_layout(title=title, height=300, margin=dict(l=8, r=8, t=44, b=8),
                      yaxis=dict(title="논문수"), yaxis2=dict(title="피인용", overlaying="y", side="right"),
                      legend=dict(orientation="h", y=1.18))
    st.plotly_chart(fig, use_container_width=True)


def chart_network(data, title):
    """공동등장 네트워크 (plotly)."""
    if not data or len(data["nodes"]) < 2:
        st.caption(f"{title} — 노드 부족")
        return
    fig = go.Figure()
    ex, ey = [], []
    for e in data["edges"]:
        ex += [e["x0"], e["x1"], None]
        ey += [e["y0"], e["y1"], None]
    fig.add_trace(go.Scatter(x=ex, y=ey, mode="lines", line=dict(width=0.5, color="#cbd5e1"),
                             hoverinfo="none"))
    nx_ = [n["x"] for n in data["nodes"]]
    ny_ = [n["y"] for n in data["nodes"]]
    sizes = [n["size"] for n in data["nodes"]]
    labels = [n["id"] for n in data["nodes"]]
    mx = max(sizes) or 1
    fig.add_trace(go.Scatter(
        x=nx_, y=ny_, mode="markers+text", text=labels, textposition="top center",
        textfont=dict(size=10), marker=dict(size=[12 + 32 * s / mx for s in sizes], color="#4C78A8"),
        hovertext=[f"{l}: {s}회" for l, s in zip(labels, sizes)], hoverinfo="text"))
    fig.update_layout(title=title, height=560, margin=dict(l=8, r=8, t=44, b=8), showlegend=False,
                      xaxis=dict(visible=False), yaxis=dict(visible=False))
    st.plotly_chart(fig, use_container_width=True)


def render_author(p):
    st.subheader(f"👤 {p['name']}")
    m = st.columns(4)
    m[0].metric("h-index", p["h_index"] if p["h_index"] is not None else "—")
    m[1].metric("i10-index", p["i10_index"] if p["i10_index"] is not None else "—")
    m[2].metric("2yr 평균피인용", p["mean_citedness2y"])
    m[3].metric("총 논문", f"{p['works_count']:,}")
    meta = f"**현재 소속:** {p['last_institution'] or '—'} ({p['last_country'] or '—'}) · 총 피인용 {p['cited_by_count']:,}"
    links = []
    if p["orcid"]:
        links.append(f"[ORCID](https://orcid.org/{p['orcid']})")
    if p["openalex_url"]:
        links.append(f"[OpenAlex]({p['openalex_url']})")
    if links:
        meta += "  ·  " + " · ".join(links)
    st.markdown(meta)
    chart_counts_year(p["counts_by_year"], "생산성·피인용 추이")
    a1, a2 = st.columns(2)
    with a1:
        chart_hbar([(n, c, "") for n, c in p["topics"]], "연구 주제 (topics)")
    with a2:
        chart_hbar(cached_coauthors(p["id"], 15), "주요 공저자")
    if p["affiliations"]:
        with st.expander(f"소속 이력 {len(p['affiliations'])}개"):
            adf = pd.DataFrame([{"기관": a["name"], "국가": a["country"], "연도": a["years"]}
                               for a in p["affiliations"]])
            st.dataframe(adf, hide_index=True, use_container_width=True)
    st.caption("⚠️ OpenAlex 저자 disambiguation은 자동이라 동명이인 병합/분할 오류 가능. "
               "h-index·피인용은 오픈 인용 기반이라 WoS/Scopus보다 과소집계일 수 있습니다.")


def render_institution(p, crit):
    st.subheader(f"🏛️ {p['name']}")
    m = st.columns(4)
    m[0].metric("h-index", p["h_index"] if p["h_index"] is not None else "—")
    m[1].metric("i10-index", p["i10_index"] if p["i10_index"] is not None else "—")
    m[2].metric("2yr 평균피인용", p["mean_citedness2y"])
    m[3].metric("총 논문", f"{p['works_count']:,}")
    meta = f"**국가:** {p['country_code'] or '—'} · **유형:** {p['type'] or '—'} · **도시:** {p['geo']['city'] or '—'}"
    links = []
    if p["ror"]:
        links.append(f"[ROR]({p['ror']})")
    if p["homepage"]:
        links.append(f"[홈페이지]({p['homepage']})")
    if p["openalex_url"]:
        links.append(f"[OpenAlex]({p['openalex_url']})")
    if links:
        meta += "  ·  " + " · ".join(links)
    st.markdown(meta)
    if p["geo"]["lat"] and p["geo"]["lon"]:
        st.map(pd.DataFrame([{"lat": p["geo"]["lat"], "lon": p["geo"]["lon"]}]), zoom=3)
    chart_counts_year(p["counts_by_year"], "생산성·피인용 추이")
    i1, i2 = st.columns(2)
    with i1:
        chart_hbar([(n, c, "") for n, c in p["topics"]], "연구 주제 (topics)")
    with i2:
        filt = f"authorships.institutions.id:{p['id']}"
        suffix = ""
        if crit and crit.get("field_filter"):
            filt += "," + crit["field_filter"]
            suffix = " (현재 분야)"
        chart_hbar(cached_entity_top(filt, "authorships.author.id", 15), "소속 상위 저자" + suffix)
    if p["associated"]:
        with st.expander(f"연관 기관 {len(p['associated'])}개 (parent/child/related)"):
            for nm, rel, _ in p["associated"]:
                st.markdown(f"- {nm} — _{rel}_")
    with st.expander("⚠️ 기관 집계 주의 (OpenAlex disambiguation)"):
        st.markdown(C.INST_CAVEAT)


def chart_heatmap(cc, title="국가 공동등장(공저) 매트릭스", key=None):
    labels = cc["labels"]
    if len(labels) < 2:
        st.caption(f"{title} — 국가 정보 부족")
        return
    fig = px.imshow(cc["matrix"], x=labels, y=labels, text_auto=True,
                    color_continuous_scale="Blues", aspect="auto")
    fig.update_layout(title=title + " · 대각선=단독, 칸=공저 (표시 결과 기준)",
                      height=420, margin=dict(l=8, r=8, t=44, b=8),
                      coloraxis_showscale=False)
    st.plotly_chart(fig, use_container_width=True, key=key)


# ============================================================
# 세션 상태
# ============================================================
ss = st.session_state
for k, v in {"author_id": "", "author_label": "", "author_candidates": [],
             "inst_id": "", "inst_label": "", "inst_candidates": [],
             "result": None, "query_desc": "", "criteria": None,
             "field_label": "전체 분야", "kci_records": [],
             "topic_result": None, "rising_result": None, "suggest_result": None,
             "net_result": None}.items():
    ss.setdefault(k, v)

# ============================================================
# 사이드바 — 검색 패널
# ============================================================
with st.sidebar:
    st.header("🔎 검색 조건")

    # ---- 분야: 도메인·분야·세분류를 한 곳에서 섞어 복수 선택 ----
    tax = get_taxonomy()
    field_opts = {}   # 표시 라벨 -> (level, id, 이름)

    def _add_field_opt(label, level, eid, name):
        key = label if label not in field_opts else f"{label} ({eid})"  # 동명 충돌 방지
        field_opts[key] = (level, eid, name)

    for _did, _nm in tax["domains"]:
        _add_field_opt(f"[도메인] {C.DOMAIN_KR.get(_did, _nm)} ({_nm})", "domain", _did, C.DOMAIN_KR.get(_did, _nm))
    for _fid, _nm, _did, _dnm in tax["fields"]:
        _add_field_opt(f"[분야] {_nm} · {C.DOMAIN_KR.get(_did, _dnm)}", "field", _fid, _nm)
    for _sid, _nm, _fid, _fnm, _dnm in tax["subfields"]:
        _add_field_opt(f"[세분류] {_nm} · {_fnm}", "subfield", _sid, _nm)

    _dflt = [lbl for lbl, (lvl, eid, nm) in field_opts.items() if eid in C.DEFAULT_FIELD_IDS]
    sel_labels = st.multiselect(
        "분야 (도메인·분야·세분류를 섞어 검색·복수 선택)", list(field_opts), default=_dflt,
        help="한 검색창에서 모든 층위를 찾아 섞어 고를 수 있어요. "
             "예: '[세분류] Public Administration' + '[분야] Computer Science' 를 함께 선택. "
             "층위가 섞이면 자동으로 세분류 단위로 묶어 OR 검색합니다. 비우면 전체 분야.")
    selected_fields = [field_opts[l] for l in sel_labels]
    field_filter, field_label, field_scimago_cat = build_field_filter(selected_fields, tax)

    with st.expander("분야 직접 지정 (OpenAlex filter, 고급)"):
        custom = st.text_input("filter 조각", value="",
                               placeholder="예: primary_topic.subfield.id:3321|3320",
                               help="입력하면 위 선택을 덮어씁니다.")
        if custom.strip():
            field_filter = custom.strip()
            field_label = "직접지정"

    query = st.text_input("키워드 / 제목", placeholder="예: collaborative governance",
                          help="동의어는 | 로 묶어 OR 검색: gpt|chatgpt|llama")
    SCOPES = {"제목+초록 (정밀, 기본)": "title_abstract", "제목만": "title", "전체 본문": "all"}
    scope_label = st.radio("검색 범위", list(SCOPES.keys()), index=0,
                           help="'전체 본문'은 잠깐 언급/인용만 한 논문까지 잡혀 인용수 정렬 시 무관한 논문이 섞입니다.")
    scope = SCOPES[scope_label]
    phrase = st.checkbox("정확한 구문 일치(따옴표)", value=False,
                         help='예: "machine learning" 를 한 덩어리로 매칭 (|OR과 함께 쓰지 마세요)')

    st.divider()
    st.caption("저자 (선택) — 이름·ORCID·OpenAlex ID")
    author_name = st.text_input(
        "저자", placeholder="Chris Ansell · 0000-0002-7723-1283 · A5021817508",
        label_visibility="collapsed",
        help="이름은 동명이인 후보가 뜹니다. 정확히는 ORCID(0000-…)·OpenAlex ID(A…).")
    a1, a2 = st.columns(2)
    if a1.button("후보 찾기", use_container_width=True, disabled=not author_name.strip(), key="afind"):
        ok, cands = cached_resolve_author(author_name.strip())
        ss.author_candidates = cands if ok else []
        if not ok:
            st.error(f"저자 조회 실패: {cands}")
        elif not cands:
            st.warning("일치 저자 없음 — 철자/이니셜 변경 또는 ORCID·ID로.")
    if a2.button("저자 해제", use_container_width=True, disabled=not ss.author_id, key="aclr"):
        ss.author_id = ss.author_label = ""
        ss.author_candidates = []
    if ss.author_candidates:
        opts = {f"{a['name']} · 논문 {a['works_count']}"
                f"{' · ORCID '+a['orcid'] if a.get('orcid') else ''}"
                f" · {a['institution'] or '소속미상'}": a for a in ss.author_candidates}
        pick = st.selectbox("저자 후보 선택", list(opts.keys()))
        if st.button("이 저자로 지정", use_container_width=True):
            a = opts[pick]
            ss.author_id, ss.author_label, ss.author_candidates = a["id"], a["name"], []
            st.rerun()
    if ss.author_id:
        st.success(f"저자: {ss.author_label} ({ss.author_id})")

    st.caption("기관 (선택) — 이름 검색 또는 ROR")
    inst_name = st.text_input(
        "기관", placeholder="Seoul National University · https://ror.org/…",
        label_visibility="collapsed", help="기관명을 넣고 후보를 고르거나 ROR/OpenAlex ID 직접 입력.")
    b1, b2 = st.columns(2)
    if b1.button("기관 찾기", use_container_width=True, disabled=not inst_name.strip(), key="ifind"):
        if "ror.org" in inst_name or inst_name.strip().startswith("I"):
            ss.inst_id, ss.inst_label, ss.inst_candidates = inst_name.strip(), inst_name.strip(), []
            st.rerun()
        ok, cands = cached_institutions(inst_name.strip())
        ss.inst_candidates = cands if ok else []
        if not ok:
            st.error(f"기관 조회 실패: {cands}")
    if b2.button("기관 해제", use_container_width=True, disabled=not ss.inst_id, key="iclr"):
        ss.inst_id = ss.inst_label = ""
        ss.inst_candidates = []
    if ss.inst_candidates:
        iopts = {f"{x['name']} · {x['hint'] or ''} · 논문 {x['works_count']:,}": x
                 for x in ss.inst_candidates}
        ipick = st.selectbox("기관 후보 선택", list(iopts.keys()))
        if st.button("이 기관으로 지정", use_container_width=True):
            x = iopts[ipick]
            ss.inst_id, ss.inst_label, ss.inst_candidates = x["id"], x["name"], []
            st.rerun()
    if ss.inst_id:
        st.success(f"기관: {ss.inst_label} ({ss.inst_id})")

    st.divider()
    yr = st.slider("연도 범위", C.YEAR_MIN, C.YEAR_MAX, (2010, C.YEAR_MAX))
    sort_label = st.selectbox("정렬", list(C.SORT_OPTIONS.keys()),
                              index=list(C.SORT_OPTIONS.keys()).index(C.DEFAULT_SORT))
    lang_label = st.selectbox("언어", list(C.LANG_OPTIONS.keys()),
                              index=list(C.LANG_OPTIONS.keys()).index(C.DEFAULT_LANG))
    max_results = st.number_input("최대 결과 수", min_value=50, max_value=2000,
                                  value=C.MAX_RESULTS_CAP, step=50)
    run = st.button("🔍 검색", type="primary", use_container_width=True)

    with st.expander("저널 쿼타일(Q1~Q4) 데이터"):
        st.caption("scimagojr.com → **Download data** CSV를 올리면 SJR 쿼타일 표시. (없어도 정상)")
        up = st.file_uploader("Scimago CSV", type=["csv"], label_visibility="collapsed")
    sj_local, sj_path = get_scimago_local()
    if up is not None:
        sj_index, sj_source = get_scimago_uploaded(up.getvalue()), f"업로드: {up.name}"
    elif sj_local:
        sj_index, sj_source = sj_local, f"로컬: {sj_path.split(chr(92))[-1] if sj_path else ''}"
    else:
        sj_index, sj_source = {}, None
    st.caption(f"✅ SJR {len(sj_index):,} ISSN · {sj_source}" if sj_index
               else "⚠️ SJR 미로드 — Scimago CSV 업로드 시 Q1~Q4 표시")

    st.divider()
    with st.expander("🔗 DOI로 논문 1편 찾기"):
        doi_input = st.text_input("DOI", placeholder="10.1093/jopart/mum032",
                                  label_visibility="collapsed", help="DOI 또는 https://doi.org/…")
        doi_run = st.button("DOI 조회", use_container_width=True, disabled=not doi_input.strip())

    with st.expander("📋 DOI 세트로 분석 (검색 없이)"):
        st.caption("내가 가진 DOI 목록만으로 논문 세트를 만들어 **표·초록·토픽발견·협업 네트워크·연구자 분석**에 씁니다. "
                   "(동향 대시보드는 검색 조건 기반이라 DOI 세트엔 미적용)")
        doiset_text = st.text_area("DOI 목록 (줄바꿈/쉼표 구분, 최대 200개)", height=110,
                                   placeholder="10.1093/jopart/mum032\n10.1111/padm.12209\nhttps://doi.org/…",
                                   label_visibility="collapsed")
        doiset_run = st.button("DOI 세트 분석", use_container_width=True,
                               disabled=not doiset_text.strip())

    with st.expander("🇰🇷 KCI/RISS 병합 (한국 논문 보강)"):
        st.caption("RISS·KCI·DBpia에서 받은 **RIS(.ris/.txt) 또는 Excel(.xlsx)** 을 올리면 "
                   "OpenAlex가 놓친 한국 논문을 결과에 합칩니다. (DOI/제목 중복은 자동 제거)")
        st.markdown(
            "**받는 법:** RISS/KCI/DBpia 검색 → 내보내기에서 **RIS** 선택(가장 안전). "
            "Excel이면 **제목·저자·발행연도·학술지·DOI·초록** 열이 있으면 자동 인식.\n\n"
            "**RIS 양식 예시:**")
        st.code("TY  - JOUR\nTI  - 논문 제목\nAU  - 저자1\nAU  - 저자2\nPY  - 2023\n"
                "JO  - 학술지명\nDO  - 10.xxxx/xxxx\nAB  - 초록 …\nER  - ", language="text")
        kci_up = st.file_uploader("KCI/RISS 파일", type=["ris", "txt", "xlsx", "xls"],
                                  label_visibility="collapsed")
        if kci_up is not None:
            recs, err = parse_kci(kci_up.name, kci_up.getvalue())
            if err:
                st.error(f"파싱 실패: {err}")
            else:
                ss.kci_records = recs
                st.success(f"KCI 파싱 {len(recs)}건 — 검색 결과에 병합됩니다.")
        if ss.kci_records and st.button("KCI 병합 해제", use_container_width=True):
            ss.kci_records = []
            st.rerun()

# ============================================================
# 검색 실행
# ============================================================
if run:
    with st.spinner("OpenAlex 검색 중…"):
        ok, payload = cached_search(
            query=query.strip(), year_from=yr[0], year_to=yr[1], field_filter=field_filter,
            author_id=ss.author_id, sort=C.SORT_OPTIONS[sort_label],
            lang=C.LANG_OPTIONS[lang_label], scope=scope, phrase=phrase,
            max_results=int(max_results), institution_id=ss.inst_id)
    if not ok:
        st.error(f"검색 실패: {payload}")
        ss.result = None
    else:
        if sj_index:
            scimago.annotate(payload["records"], sj_index, field_category=field_scimago_cat)
        ss.result = payload
        ss.field_label = field_label
        ss.topic_result = ss.rising_result = ss.suggest_result = ss.net_result = None  # 새 검색 초기화
        desc = [field_label]
        if query.strip():
            desc.append(f"'{query.strip()}' ({scope_label})")
        if ss.author_id:
            desc.append(f"저자={ss.author_label}")
        if ss.inst_id:
            desc.append(f"기관={ss.inst_label}")
        desc.append(f"{yr[0]}–{yr[1]}")
        ss.query_desc = " · ".join(desc)
        ss.criteria = dict(query=query.strip(), scope=scope, phrase=phrase,
                           year_from=yr[0], year_to=yr[1], field_filter=field_filter,
                           author_id=ss.author_id, lang=C.LANG_OPTIONS[lang_label],
                           institution_id=ss.inst_id)

if doi_run:
    with st.spinner("DOI 조회 중…"):
        ok, rec = cached_doi(doi_input.strip())
    if not ok:
        st.error(f"DOI 조회 실패: {rec}")
    else:
        if sj_index:
            scimago.annotate([rec], sj_index, field_category="")
        ss.result = {"total": 1, "records": [rec], "truncated": False}
        ss.query_desc = f"DOI: {doi_input.strip()}"
        ss.criteria = None
        ss.topic_result = ss.rising_result = ss.suggest_result = ss.net_result = None

# DOI 세트 분석 (검색 없이)
if doiset_run:
    import re as _re
    dois = [d.strip() for d in _re.split(r"[\s,;]+", doiset_text) if d.strip()][:200]
    recs, fails = [], 0
    prog = st.progress(0.0, text="DOI 세트 조회 중…")
    for k, d in enumerate(dois, 1):
        ok, rec = cached_doi(d)
        if ok:
            recs.append(rec)
        else:
            fails += 1
        prog.progress(k / max(len(dois), 1))
    prog.empty()
    if not recs:
        st.error("유효한 DOI가 없습니다. 형식을 확인하세요.")
    else:
        if sj_index:
            scimago.annotate(recs, sj_index, field_category="")
        ss.result = {"total": len(recs), "records": recs, "truncated": False}
        ss.query_desc = f"DOI 세트 {len(recs)}건" + (f" · 실패 {fails}건" if fails else "")
        ss.criteria = None
        ss.topic_result = ss.rising_result = ss.suggest_result = ss.net_result = None

# ============================================================
# 메인
# ============================================================
st.title("📚 연구동향·선행연구 조사")
st.caption("OpenAlex · 전 분야 검색 · 검색→선별→내보내기 · 동향 대시보드 · 토픽 발견")

result = ss.result
if not result:
    st.info("← 왼쪽에서 분야·키워드 등을 정하고 **검색**을 누르세요. (또는 DOI 세트로 바로 분석)")
    st.stop()
oa_records = result["records"]
total = result["total"]
if not oa_records:
    st.warning("결과가 없습니다. 조건을 완화해 보세요.")
    st.stop()

# KCI/RISS 병합 (#12) — 표·내보내기·토픽발견에만 반영(대시보드는 OpenAlex 집계 유지)
kci_note = ""
if ss.kci_records:
    records, minfo = kci_merge.merge(oa_records, ss.kci_records)
    kci_note = f"  ·  🇰🇷 KCI 병합 +{minfo['added']}건(중복 {minfo['dup']} 제외)"
else:
    records = oa_records

head = f"**{ss.query_desc}** — 총 **{total:,}건** 중 {len(oa_records):,}건 표시{kci_note}"
if result["truncated"]:
    head += f"  ·  ⚠️ 상한({len(oa_records)}건)에서 잘림 — '최대 결과 수'를 늘리세요"
st.markdown(head)

# 커버리지 배지 (#2) — 표시된 결과 기준 메타데이터 결측률
n = len(records)
cov = {
    "초록": sum(bool(r["abstract"]) for r in records),
    "DOI": sum(bool(r["doi"]) for r in records),
    "저자 ORCID": sum(r["has_orcid"] for r in records),
    "기관/국가": sum(r["has_country"] for r in records),
}
cols = st.columns(len(cov))
for col, (k, v) in zip(cols, cov.items()):
    col.metric(k, f"{100*v/n:.0f}%", help=f"{v}/{n}건에 {k} 있음")
st.caption("⚠️ OpenAlex는 **한국·최근연도·한국어(KCI) 커버리지가 불완전**(타임랩·메타데이터 결손)하고, "
           "기관/국가 식별엔 오귀속이 있습니다. 위 결측률을 감안해 해석하세요.")

tab_search, tab_dash, tab_topic, tab_people = st.tabs(
    ["🔎 검색 결과", "📊 동향 대시보드", "🔬 토픽 발견", "👤 연구자 분석"])

def _sjr_sort_key(r):
    """SJR 우선 정렬 키: Q1→Q4 먼저, 같은 쿼타일은 SJR 값 높은 순, 미등재(쿼타일 없음)는 맨 뒤."""
    rank = {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4}.get(r.get("sj_quartile", ""), 9)
    sjr = r.get("sj_sjr")
    sjr = sjr if isinstance(sjr, (int, float)) else -1.0
    return (rank, -sjr)


# ------------------------------------------------------------
# 탭 1: 검색 결과
# ------------------------------------------------------------
with tab_search:
    show_src = any(r.get("data_source") == "KCI" for r in records)
    has_sjr = any(r.get("sj_quartile") for r in records)
    if has_sjr:
        sjr_sort = st.checkbox(
            "SJR 우선 정렬 (Q1→Q4, 미등재는 아래로)", value=False, key="sjr_sort",
            help="이미 가져온 결과를 Scimago SJR 쿼타일 순으로 재정렬합니다(새로 검색하지 않음). "
                 "SJR 없는 저널(Scopus 비등재·ISSN 불일치·단행본 등)은 맨 아래로 내려갑니다.")
    else:
        sjr_sort = False
    disp_records = sorted(records, key=_sjr_sort_key) if sjr_sort else records
    df = pd.DataFrame([{
        "제목": r["title"], "연도": r["year"], "저자": r["author_str"], "학술지": r["venue"],
        **({"출처": ("🇰🇷KCI" if r.get("data_source") == "KCI" else "OA")} if show_src else {}),
        "SJR": r.get("sj_quartile", ""), "IF*": r["j_if2y"], "저널h": r["j_hindex"],
        "DOAJ": "🟢" if r["j_doaj"] else "", "피인용": r["cited_by"],
        "OA": "🟢" if r["is_oa"] else "", "DOI": r["doi_url"],
    } for r in disp_records])
    event = st.dataframe(
        df, use_container_width=True, hide_index=True, height=440,
        on_select="rerun", selection_mode="multi-row",
        column_config={
            "제목": st.column_config.TextColumn(width="large"),
            "DOI": st.column_config.LinkColumn("DOI", display_text="link"),
            "피인용": st.column_config.NumberColumn(format="%d"),
            "SJR": st.column_config.TextColumn("SJR", help="Scimago 최우수 쿼타일 (Q1~Q4)"),
            "IF*": st.column_config.NumberColumn("IF*", format="%.2f",
                  help="OpenAlex 2년 평균 피인용수 (JCR IF 아님)"),
            "저널h": st.column_config.NumberColumn(help="저널 h-index"),
        },
    )
    sel_rows = event.selection.rows if event and event.selection else []
    selected = [disp_records[i] for i in sel_rows]
    st.caption("ℹ️ **SJR**=Scimago 쿼타일 · **IF\\***=OpenAlex 2년 평균 피인용(JCR IF 아님) · "
               "**저널h**=h-index · **DOAJ**=등재 OA. · ⚠️ 표시 목록은 정렬 상위 일부이며 "
               "최신 논문은 수집·인용 지연으로 과소대표될 수 있습니다(동향은 대시보드의 전체 집계 참고).")
    st.caption(f"선택: {len(selected)}건 · 행 체크 시 아래 상세·초록 + 내보내기 대상.")

    if selected:
        st.subheader("📄 선택한 논문")
        for r in selected:
            with st.expander(f"[{r['year']}] {r['title']} · 피인용 {r['cited_by']}"):
                st.markdown(f"**저자:** {', '.join(r['authors']) or '미상'}")
                meta = f"**학술지:** {r['venue'] or '—'}  |  **토픽:** {r['topic'] or '—'}"
                jbits = []
                if r.get("sj_quartile"):
                    fq = r.get("sj_field_q")
                    qd = f"SJR {r['sj_quartile']}" + (f" (분야 {fq})" if fq and fq != r["sj_quartile"] else "")
                    if r.get("sj_sjr") is not None:
                        qd += f", SJR={r['sj_sjr']}"
                    jbits.append(qd)
                if r["j_if2y"] is not None:
                    jbits.append(f"IF* {r['j_if2y']:.2f}")
                if r["j_hindex"] is not None:
                    jbits.append(f"h {r['j_hindex']}")
                if r["j_doaj"]:
                    jbits.append("DOAJ")
                if jbits:
                    meta += "  |  **저널:** " + " · ".join(jbits)
                if r.get("sj_cats"):
                    meta += f"  \n  ↳ _SJR 카테고리: {r['sj_cats']}_"
                if r["is_oa"]:
                    meta += f"  |  **OA:** {r['oa_status']}"
                st.markdown(meta)
                links = [f"[DOI]({r['doi_url']})"] if r["doi_url"] else []
                if r["openalex_url"]:
                    links.append(f"[OpenAlex]({r['openalex_url']})")
                if links:
                    st.markdown(" · ".join(links))
                if r.get("title_in_abstract"):
                    st.caption("⚠️ 이 초록은 앞에 제목이 중복 삽입돼 있어 내보내기 땐 정제본을 씁니다.")
                st.markdown("**초록**")
                st.write(r["abstract"] or "_(초록 없음)_")

    # 코퍼스 투명성 (#16)
    with st.expander("🔍 이 코퍼스는 어떻게 만들어졌나 (투명성)"):
        st.code(ex.corpus_manifest(ss.query_desc, ss.criteria, total, len(records)),
                language="markdown")

    # 내보내기
    st.divider()
    export_set = selected if selected else records
    escope = f"선택 {len(selected)}건" if selected else f"전체 표시 {len(records)}건"
    miss_abs = sum(1 for r in export_set if not r["abstract"])
    dup_title = sum(1 for r in export_set if r.get("title_in_abstract"))
    st.subheader(f"⬇️ 내보내기 ({escope})")
    flags = []
    if miss_abs:
        flags.append(f"초록 없음 {miss_abs}건")
    if dup_title:
        flags.append(f"제목중복 초록 {dup_title}건(정제 적용)")
    st.caption("⚠️ Excel 한글 깨지면 표 툴바 아이콘 말고 **아래 CSV 버튼**(UTF-8 BOM). "
               "BibTeX·RIS=Zotero/EndNote. **분류 프롬프트**=앱 밖 Claude Code 분류용. "
               + (" · 초록 점검: " + ", ".join(flags) if flags else ""))
    e1, e2, e3, e4 = st.columns(4)
    e1.download_button("CSV", ex.to_csv(export_set), file_name="lit_export.csv",
                       mime="text/csv", use_container_width=True)
    e2.download_button("BibTeX", ex.to_bibtex(export_set), file_name="lit_export.bib",
                       mime="text/plain", use_container_width=True)
    e3.download_button("RIS", ex.to_ris(export_set), file_name="lit_export.ris",
                       mime="application/x-research-info-systems", use_container_width=True)
    e4.download_button("분류 프롬프트", ex.to_classification_prompt(export_set),
                       file_name="classify_prompt.txt", mime="text/plain",
                       use_container_width=True, help="zero-shot 분류 프롬프트+데이터 (Claude Code에 붙여넣기)")

# ------------------------------------------------------------
# 탭 2: 동향 대시보드 (group_by 전체 집계)
# ------------------------------------------------------------
with tab_dash:
    crit = ss.criteria
    if not crit:
        st.info("먼저 검색을 실행하면 그 조건으로 동향을 집계합니다. (DOI 단일 조회엔 동향 없음)")
    else:
        st.caption(f"**{ss.query_desc}** — 검색 조건의 **전체 매칭 집합** 집계 "
                   f"(표시분이 아니라 총 {total:,}건 기준). 막대·점 = 실제 논문 수."
                   + ("  ·  🇰🇷 KCI 병합분은 OpenAlex 집계라 **여기 동향엔 미포함**(표·내보내기·토픽발견엔 반영)."
                      if ss.kci_records else ""))
        tc1, tc2 = st.columns([2, 3])
        topn = tc1.slider("상위 N", 5, 30, 15, key="dash_topn")
        count_mode = tc2.radio("저자·기관·국가 집계 방식",
                               ["전수(full)", "분수(fractional)"], horizontal=True,
                               help="full=공저 1편을 각자 1로(전체 매칭 집합). "
                                    "fractional=1/n로 나눠 공저 부풀림 보정(표시분 기준).")
        frac = count_mode.startswith("분수")

        def agg(gb, top=topn):
            return cached_agg(gb, top, crit["query"], crit["scope"], crit["phrase"],
                              crit["year_from"], crit["year_to"], crit["field_filter"],
                              crit["author_id"], crit["lang"], crit.get("institution_id", ""))

        with st.spinner("동향 집계 중…"):
            year_rows = agg("publication_year", 0)
            sources = agg("primary_location.source.id")
            inst_types = agg("authorships.institutions.type", 0)
            topics = agg("primary_topic.id")
            fields = agg("primary_topic.field.id", 0)
            oa_rows = agg("open_access.is_oa", 0)
            if frac:
                authors = analysis.fractional_counts(records, "authors", topn)
                insts = analysis.fractional_counts(records, "institutions", topn)
                countries = analysis.fractional_counts(records, "countries", topn)
            else:
                authors = agg("authorships.author.id")
                insts = agg("authorships.institutions.id")
                countries = agg("authorships.countries")

        _ms = "(분수·표시분)" if frac else "(전수)"
        chart_year(year_rows)
        d1, d2 = st.columns(2)
        with d1:
            chart_hbar(authors, f"상위 저자 {_ms}")
        with d2:
            chart_hbar(sources, "상위 학술지")
        d3, d4 = st.columns(2)
        with d3:
            chart_hbar(insts, f"상위 기관 {_ms} ⚠️오귀속 가능")
        with d4:
            chart_hbar(inst_types, "기관 유형", color="#72B7B2")
        # 기관 집계 캐비엇 (비영어권 자동 disambiguation)
        with st.expander("⚠️ 기관 집계 주의 (OpenAlex disambiguation)"):
            st.markdown(C.INST_CAVEAT)
        d5, d6 = st.columns(2)
        with d5:
            chart_hbar(topics, "상위 토픽")
        with d6:
            chart_hbar(fields, "상위 분야(field)", color="#54A24B")
        d7, d8 = st.columns(2)
        with d7:
            chart_hbar(countries, f"상위 국가 {_ms}")
        with d8:
            chart_oa(oa_rows)
        if frac:
            st.caption("ℹ️ **분수계수**: 공저 1편을 참여 저자/기관/국가 수로 나눠(1/n) 합산 — "
                       "다수공저 부풀림 보정. 단 **표시된 결과 기준**(전체 매칭 아님)이라 전수(full)와 모집단이 다릅니다.")

        st.divider()
        chart_heatmap(analysis.country_cooccurrence(records, top=12), key="dash_cooc")

        # 저자 연구궤적 (#9) — 저자 지정 시
        if crit.get("author_id"):
            st.divider()
            st.subheader("🧭 저자 연구궤적 (표시된 논문 기준)")
            traj = [{"연도": r["year"], "토픽": r["topic"] or "(미상)",
                     "피인용": r["cited_by"], "제목": r["title"]}
                    for r in records if r["year"]]
            if traj:
                td = pd.DataFrame(traj)
                fig = px.scatter(td, x="연도", y="토픽", size="피인용", hover_name="제목",
                                 size_max=28, color="토픽")
                fig.update_layout(height=max(320, 22 * td["토픽"].nunique() + 120),
                                  margin=dict(l=8, r=8, t=10, b=8), showlegend=False)
                st.plotly_chart(fig, use_container_width=True)

        st.caption("ℹ️ 막대·점은 LLM 추론이 아니라 OpenAlex GROUP BY 집계 — 실제 논문 수, 역추적 가능. "
                   "국가 매트릭스·저자궤적은 표시 결과 기준(전체 아님).")

# ------------------------------------------------------------
# 탭 3: 토픽 발견 (초록 LDA · rising terms)
# ------------------------------------------------------------
with tab_topic:
    st.caption("OpenAlex Topic은 알고리즘 라벨이라 추상적 → **복원한 초록을 직접 LDA·TF-IDF로 세분화**. "
               "비지도 통계(LLM 아님). 표시된 결과의 초록만 사용 — '전체 본문' 범위로 많이 모을수록 좋습니다.")
    abstracts = [r["abstract_clean"] for r in records]
    have = sum(bool(a) for a in abstracts)
    st.caption(f"사용 가능한 초록: {have}/{len(records)}건")

    st.subheader("주제 클러스터 (LDA)")
    st.caption("탐색적 분석입니다. 토픽 수 k는 분석자가 지정하는 값으로(자동 결정 아님), "
               "출판용이면 아래 **'최적 k 추천'(coherence/perplexity)** 으로 근거를 남기거나 "
               "비모수 방법(BERTopic·HDP)을 함께 검토하세요. 이 표는 선행연구 **'발견'용**이며 "
               "확정된 주제 구조가 아닙니다.")
    cL, cR = st.columns([1, 3])
    n_topics = cL.slider("토픽 수 k", 2, 12, 6, key="lda_n")
    if cL.button("토픽 추출", use_container_width=True):
        with st.spinner("LDA 토픽모델링 중…"):
            ss.topic_result = analysis.topic_model(abstracts, n_topics=n_topics)
    if cL.button("📐 최적 k 추천", use_container_width=True,
                 help="k=2~8을 쓸어 coherence·perplexity 계산 (클라우드는 30~60초)"):
        with st.spinner("k별 coherence/perplexity 계산 중… (수십 초)"):
            ss.suggest_result = analysis.suggest_k(abstracts, k_min=2, k_max=8)

    if ss.topic_result:
        topics, info = ss.topic_result
        if topics:
            cR.caption(f"문서 {info.get('used_docs')}건 · 어휘 {info.get('vocab')}개")
            tdf = pd.DataFrame([{"토픽": t["topic"], "문서수": t["size"],
                                 "대표어": ", ".join(t["words"])} for t in topics])
            cR.dataframe(tdf, hide_index=True, use_container_width=True)
        else:
            cR.warning(info.get("error", "토픽 추출 실패"))

    # 최적 k 추천 (coherence ↑좋음 / perplexity ↓좋음)
    if ss.suggest_result:
        sdata, serr = ss.suggest_result
        if serr:
            st.warning(serr)
        else:
            st.success(f"📐 추천 k = **{sdata['best_coherence']}** "
                       f"(UMass coherence 최대) · 문서 {sdata['used_docs']}건. "
                       "coherence가 꺾이는/최대인 k, perplexity가 낮은 k를 함께 보고 정하세요.")
            sd = pd.DataFrame(sdata["rows"])
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=sd["k"], y=sd["coherence"], name="coherence (↑좋음)",
                                     mode="lines+markers", line=dict(color="#E45756")))
            fig.add_trace(go.Scatter(x=sd["k"], y=sd["perplexity"], name="perplexity (↓좋음)",
                                     mode="lines+markers", yaxis="y2", line=dict(color="#4C78A8")))
            fig.update_layout(height=300, margin=dict(l=8, r=8, t=10, b=8),
                              xaxis_title="k (토픽 수)",
                              yaxis=dict(title="coherence"),
                              yaxis2=dict(title="perplexity", overlaying="y", side="right"),
                              legend=dict(orientation="h", y=1.15))
            st.plotly_chart(fig, use_container_width=True)
            st.caption("UMass coherence = 토픽 대표어들이 같은 문서에 함께 등장하는 정도(응집도). "
                       "perplexity = 모델이 데이터를 얼마나 잘 설명하나(예측 혼란도). "
                       "둘 다 휴리스틱이라 절대 기준 아님 — 해석가능성과 함께 판단하세요.")

    st.divider()
    st.subheader("뜨는/지는 용어 (rising terms · 연도 cutoff 전후 TF-IDF)")
    rL, rR = st.columns([1, 3])
    yrs = [r["year"] for r in records if r["year"]]
    lo, hi = (min(yrs), max(yrs)) if yrs else (2010, 2026)
    cutoff = rL.slider("cutoff 연도", lo + 1, hi, min(max(lo + 1, 2020), hi), key="rt_cut") if hi > lo else lo
    if rL.button("용어 변화 추출", use_container_width=True, disabled=hi <= lo):
        with st.spinner("TF-IDF 비교 중…"):
            ss.rising_result = analysis.rising_terms(records, cutoff_year=cutoff)
    if ss.rising_result:
        rr = ss.rising_result
        if "error" in rr:
            rR.warning(rr["error"])
        else:
            rR.caption(f"cutoff {rr['info']['cutoff']} · 이전 {rr['info']['before']}건 / 이후 {rr['info']['after']}건")
            up_df = pd.DataFrame([(t, d) for t, d, b, a in rr["rising"]], columns=["용어", "증가"])
            dn_df = pd.DataFrame([(t, -d) for t, d, b, a in rr["falling"]], columns=["용어", "감소"])
            g1, g2 = rR.columns(2)
            with g1:
                f1 = px.bar(up_df.iloc[::-1], x="증가", y="용어", orientation="h", title="📈 뜨는 용어")
                f1.update_traces(marker_color="#E45756"); f1.update_layout(height=420, margin=dict(l=8, r=8, t=40, b=8), yaxis_title=None)
                st.plotly_chart(f1, use_container_width=True)
            with g2:
                f2 = px.bar(dn_df.iloc[::-1], x="감소", y="용어", orientation="h", title="📉 지는 용어")
                f2.update_traces(marker_color="#4C78A8"); f2.update_layout(height=420, margin=dict(l=8, r=8, t=40, b=8), yaxis_title=None)
                st.plotly_chart(f2, use_container_width=True)

# ------------------------------------------------------------
# 탭 4: 연구자 분석 (저자·기관·국가 프로필 + 협업 네트워크)
# ------------------------------------------------------------
with tab_people:
    crit = ss.criteria
    st.caption("주요 저자–기관–국가를 **프로파일**(지표·연도추이·주제·이력)하고 **협업 관계**를 봅니다. "
               "전부 OpenAlex `/authors`·`/institutions`·group_by 집계 — 역추적 가능, LLM 추론 아님.")
    view = st.radio("분석 대상", ["저자", "기관", "국가", "협업 네트워크"],
                    horizontal=True, key="people_view")

    # ===== 저자 =====
    if view == "저자":
        src = st.radio("진입", ["검색 상위 저자에서 선택", "직접 조회(이름·ORCID·ID)"],
                       horizontal=True, key="auth_src")
        target_aid = None
        if src.startswith("검색"):
            if not crit:
                st.info("먼저 검색을 실행하거나 '직접 조회'를 쓰세요.")
            else:
                rows = cached_agg("authorships.author.id", 20, crit["query"], crit["scope"],
                                  crit["phrase"], crit["year_from"], crit["year_to"],
                                  crit["field_filter"], crit["author_id"], crit["lang"],
                                  crit.get("institution_id", ""))
                if rows:
                    opts = {f"{nm} ({cnt}편)": aid for nm, cnt, aid in rows}
                    target_aid = opts[st.selectbox("상위 저자", list(opts.keys()), key="auth_pick")]
                else:
                    st.caption("상위 저자 없음")
        else:
            t = st.text_input("저자 (이름·ORCID·OpenAlex ID)", key="auth_direct",
                              placeholder="Chris Ansell · 0000-0002-7723-1283 · A5021817508")
            if t.strip():
                if oa._extract_orcid(t) or oa._extract_author_id(t):
                    target_aid = t.strip()
                else:
                    ok, cands = cached_resolve_author(t.strip())
                    if ok and cands:
                        copts = {f"{c['name']} · 논문 {c['works_count']} · {c['institution'] or '소속미상'}": c["id"]
                                 for c in cands}
                        target_aid = copts[st.selectbox("후보 선택", list(copts.keys()), key="auth_dcand")]
                    elif ok:
                        st.warning("일치 저자 없음 — 철자·이니셜 변경 또는 ORCID/ID로.")
        if target_aid:
            with st.spinner("저자 프로필 로드 중…"):
                ok, p = cached_author(target_aid)
            st.error(p) if not ok else render_author(p)

    # ===== 기관 =====
    elif view == "기관":
        src = st.radio("진입", ["검색 상위 기관에서 선택", "직접 조회(기관명·ROR·ID)"],
                       horizontal=True, key="inst_src")
        target_iid = None
        if src.startswith("검색"):
            if not crit:
                st.info("먼저 검색을 실행하거나 '직접 조회'를 쓰세요.")
            else:
                rows = cached_agg("authorships.institutions.id", 20, crit["query"], crit["scope"],
                                  crit["phrase"], crit["year_from"], crit["year_to"],
                                  crit["field_filter"], crit["author_id"], crit["lang"],
                                  crit.get("institution_id", ""))
                if rows:
                    opts = {f"{nm} ({cnt}편)": iid for nm, cnt, iid in rows}
                    target_iid = opts[st.selectbox("상위 기관", list(opts.keys()), key="inst_pick")]
                else:
                    st.caption("상위 기관 없음")
        else:
            t = st.text_input("기관 (이름·ROR·OpenAlex ID)", key="inst_direct",
                              placeholder="Seoul National University · https://ror.org/… · I139264467")
            if t.strip():
                if "ror.org" in t or t.strip().startswith("I"):
                    target_iid = t.strip()
                else:
                    ok, cands = cached_institutions(t.strip())
                    if ok and cands:
                        copts = {f"{c['name']} · {c['hint'] or ''} · 논문 {c['works_count']:,}": c["id"]
                                 for c in cands}
                        target_iid = copts[st.selectbox("후보 선택", list(copts.keys()), key="inst_dcand")]
                    elif ok:
                        st.warning("일치 기관 없음")
        if target_iid:
            with st.spinner("기관 프로필 로드 중…"):
                ok, p = cached_institution(target_iid)
            st.error(p) if not ok else render_institution(p, crit)

    # ===== 국가 =====
    elif view == "국가":
        if not crit:
            st.info("먼저 검색을 실행하세요.")
        else:
            countries = cached_agg("authorships.countries", 20, crit["query"], crit["scope"],
                                   crit["phrase"], crit["year_from"], crit["year_to"],
                                   crit["field_filter"], crit["author_id"], crit["lang"],
                                   crit.get("institution_id", ""))
            c1, c2 = st.columns(2)
            with c1:
                chart_hbar(countries, "국가별 논문 수 (전체 집계)")
            with c2:
                chart_heatmap(analysis.country_cooccurrence(records, top=12), key="people_cooc")
            if countries:
                copts = {f"{lbl} ({cnt}편)": key for lbl, cnt, key in countries}
                pick = st.selectbox("국가 선택 → 그 나라 상위 기관 (현재 분야)", list(copts.keys()))
                code = copts[pick]
                filt = f"authorships.institutions.country_code:{code}"
                if crit.get("field_filter"):
                    filt += "," + crit["field_filter"]
                chart_hbar(cached_entity_top(filt, "authorships.institutions.id", 15),
                           f"{pick.split(' (')[0]} 상위 기관")
            st.caption("ℹ️ 국가별 막대는 OpenAlex 전체 집계, 공저 매트릭스는 표시된 결과 기준.")

    # ===== 협업 네트워크 =====
    else:
        st.caption("⚠️ **표시된 결과(records) 기준** 네트워크입니다(전체 매칭 집합 아님). "
                   "노드=엔티티·크기=빈도, 엣지=같은 논문 동시등장.")
        mode_label = st.radio("연결 유형", ["공저자", "기관", "국가"], horizontal=True, key="net_mode")
        mode = {"공저자": "coauthor", "기관": "institution", "국가": "country"}[mode_label]
        nL, nR = st.columns([1, 4])
        net_top = nL.slider("상위 N 노드", 10, 40, 25, key="net_n")
        if nL.button("네트워크 생성", use_container_width=True):
            with st.spinner("네트워크 구성 중…"):
                ss.net_result = analysis.cooccurrence_network(records, mode=mode, top_n=net_top)
        if ss.net_result:
            ndata, nerr = ss.net_result
            if nerr:
                st.warning(nerr)
            else:
                chart_network(ndata, f"{mode_label} 협업 네트워크 (노드 {len(ndata['nodes'])}·엣지 {ndata['n_edges']})")
