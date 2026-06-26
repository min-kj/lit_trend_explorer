# -*- coding: utf-8 -*-
"""
내보내기 — 정규화 work 레코드 -> CSV / BibTeX / RIS.

BibTeX·RIS 는 Zotero/EndNote import 호환. citation_key = lastname-year.
"""
import io
import csv
import re
import unicodedata


def _first_lastname(authors):
    if not authors:
        return "anon"
    first = authors[0]
    # "Christopher Ansell" -> "Ansell"; "Ansell, C." -> "Ansell"
    if "," in first:
        last = first.split(",")[0]
    else:
        last = first.split()[-1] if first.split() else first
    last = unicodedata.normalize("NFKD", last)
    last = re.sub(r"[^A-Za-z가-힣]", "", last)
    return last.lower() or "anon"


def citation_key(rec):
    return f"{_first_lastname(rec.get('authors'))}-{rec.get('year') or 'nd'}"


# ============================================================
# CSV
# ============================================================
CSV_COLUMNS = ["title", "year", "author_str", "venue",
               "sj_quartile", "sj_sjr", "j_if2y", "j_hindex", "j_doaj",
               "cited_by", "is_oa", "oa_status", "topic",
               "doi_url", "openalex_url", "abstract"]


def to_csv(records):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    w.writeheader()
    for r in records:
        row = {k: r.get(k, "") for k in CSV_COLUMNS}
        # 초록은 정제본(제목중복 제거) 우선
        if r.get("abstract_clean"):
            row["abstract"] = r["abstract_clean"]
        w.writerow(row)
    # UTF-8 BOM: Excel(한국어 로캘)이 UTF-8 로 인식하게 해 한글 깨짐 방지
    return "﻿" + buf.getvalue()


# ============================================================
# 코퍼스 투명성 명세 (#16) — 이 결과셋이 어떻게 만들어졌나
# ============================================================
def corpus_manifest(query_desc, criteria, total, n_shown):
    lines = ["# 코퍼스 정의 (이 결과셋이 만들어진 방식)", ""]
    lines.append(f"- 요약: {query_desc}")
    lines.append(f"- OpenAlex 전체 매칭: {total:,}건 / 내려받아 표시: {n_shown:,}건")
    if criteria:
        for k, v in criteria.items():
            if v not in (None, "", []):
                lines.append(f"- {k}: {v}")
    lines.append("- 출처: OpenAlex API (https://openalex.org)")
    lines.append("- 주의: 표시분은 정렬 상위 일부일 수 있고, 동향 집계는 전체 매칭 기준입니다.")
    return "\n".join(lines) + "\n"


# ============================================================
# LLM 분류용 zero-shot 프롬프트 (#14) — 앱 밖 Claude Code 핸드오프
# ============================================================
def to_classification_prompt(records, scheme="research_type"):
    head = (
        "[SYSTEM]\n"
        "You are a scientometric analyst. Classify each paper STRICTLY from the given text only.\n"
        "If a field is not stated, output null. Output valid JSON array only, no preamble.\n\n"
        "[TASK] 각 논문을 아래 스키마로 분류:\n"
        "{\n"
        '  "id": "OpenAlex id",\n'
        '  "research_type": "empirical|theoretical|review|method|case_study|null",\n'
        '  "topic_1sentence": "한 문장",\n'
        '  "method": ["..."],\n'
        '  "novelty_claim": "저자 주장 | null"\n'
        "}\n\n"
        "[PAPERS]\n"
    )
    body = []
    for r in records:
        ab = (r.get("abstract_clean") or r.get("abstract") or "")[:1200]
        body.append(
            f"- id: {r.get('openalex_id')}\n"
            f"  year: {r.get('year')}\n"
            f"  title: {r.get('title')}\n"
            f"  abstract: {ab}"
        )
    return head + "\n".join(body) + "\n"


# ============================================================
# BibTeX
# ============================================================
def _bib_authors(authors):
    return " and ".join(authors) if authors else ""


def to_bibtex(records):
    out = []
    seen = {}
    for r in records:
        key = citation_key(r)
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 1:
            key = f"{key}{chr(ord('a') + seen[key] - 2)}"  # -a, -b 중복 회피
        doi = r.get("doi") or ""
        doi = doi.replace("https://doi.org/", "")
        lines = [f"@article{{{key},"]
        lines.append(f"  title = {{{r.get('title','')}}},")
        if r.get("authors"):
            lines.append(f"  author = {{{_bib_authors(r['authors'])}}},")
        if r.get("year"):
            lines.append(f"  year = {{{r['year']}}},")
        if r.get("venue"):
            lines.append(f"  journal = {{{r['venue']}}},")
        if doi:
            lines.append(f"  doi = {{{doi}}},")
        if r.get("abstract"):
            abs = r["abstract"].replace("\n", " ").strip()
            lines.append(f"  abstract = {{{abs}}},")
        if r.get("openalex_url"):
            lines.append(f"  url = {{{r['openalex_url']}}},")
        lines.append("}")
        out.append("\n".join(lines))
    return "\n\n".join(out) + "\n"


# ============================================================
# RIS
# ============================================================
def to_ris(records):
    out = []
    for r in records:
        lines = ["TY  - JOUR"]
        lines.append(f"TI  - {r.get('title','')}")
        for a in (r.get("authors") or []):
            lines.append(f"AU  - {a}")
        if r.get("year"):
            lines.append(f"PY  - {r['year']}")
        if r.get("venue"):
            lines.append(f"JO  - {r['venue']}")
        doi = (r.get("doi") or "").replace("https://doi.org/", "")
        if doi:
            lines.append(f"DO  - {doi}")
        if r.get("abstract"):
            lines.append(f"AB  - {r['abstract']}")
        if r.get("openalex_url"):
            lines.append(f"UR  - {r['openalex_url']}")
        lines.append("ER  - ")
        out.append("\n".join(lines))
    return "\n\n".join(out) + "\n"
