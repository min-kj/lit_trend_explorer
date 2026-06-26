# -*- coding: utf-8 -*-
"""
lit_trend_explorer — 공통 설정 (single source of truth)

OpenAlex API 기반 연구동향·연구자 분석 도구.
분야 분류 ID는 OpenAlex /domains·/fields·/subfields 에서 동적으로 조회한다(app.get_taxonomy).
"""
import os as _os

# ============================================================
# 1. OpenAlex API (polite pool)
# ============================================================
OPENALEX_BASE = "https://api.openalex.org"
# polite pool 식별용 이메일 — 각자 환경변수/Secrets 로 설정:
#   (Windows) set OPENALEX_MAILTO=you@example.com   (mac/Linux) export OPENALEX_MAILTO=you@example.com
#   Streamlit Cloud: 앱 Settings → Secrets 에 OPENALEX_MAILTO="you@example.com"
MAILTO = _os.environ.get("OPENALEX_MAILTO", "anonymous@example.com")
REQUEST_TIMEOUT = 20             # seconds
SLEEP_BETWEEN = 0.1              # seconds, 페이지 간 호출 예의

# ============================================================
# 2. 검색 동작 한계
# ============================================================
PER_PAGE = 200                   # OpenAlex 한 페이지 최대치
MAX_RESULTS_CAP = 600            # 한 번에 가져올 최대 레코드(인터랙티브 보호). "더 가져오기"로 확장.

# ============================================================
# 3. 분야 분류 — OpenAlex Topics 4계층(Domain4 > Field26 > Subfield252 > Topic)
#    UI는 '수준 선택 + 복수 체크' (도메인/필드/세분류 중 한 수준).
#    옵션 목록은 app.get_taxonomy()가 OpenAlex /domains·/fields·/subfields 로 채움.
# ============================================================
DOMAIN_KR = {"1": "생명과학", "2": "사회과학", "3": "자연과학", "4": "보건과학"}

# 기본 분야 선택 — 환경변수/Secrets 로 개인별 설정(공개 기본값은 제한 없음).
#   OPENALEX_DEFAULT_LEVEL: none(기본) | domain | field | subfield
#   OPENALEX_DEFAULT_IDS: '|' 로 구분한 ID (예: "3321" 또는 "33|22")
DEFAULT_FIELD_LEVEL = _os.environ.get("OPENALEX_DEFAULT_LEVEL", "none")
DEFAULT_FIELD_IDS = [x for x in _os.environ.get("OPENALEX_DEFAULT_IDS", "").split("|") if x]

# 세분류(subfield) ID -> Scimago 카테고리 (세분류 1개만 선택 시 분야별 쿼타일에 사용).
# 자신의 분야 세분류 매핑을 추가하면 활성화. 예: {"<subfield_id>": "<Scimago 카테고리명>"}
SUBFIELD_SCIMAGO_CAT = {}

# ============================================================
# 4. 정렬 / 언어 옵션 — 표시명 -> OpenAlex 파라미터 값
# ============================================================
SORT_OPTIONS = {
    "관련도순":   "relevance_score:desc",
    "피인용순":   "cited_by_count:desc",
    "최신순":     "publication_date:desc",
}
DEFAULT_SORT = "관련도순"

LANG_OPTIONS = {
    "전체 언어": None,
    "영어만":    "en",
    "한국어만":  "ko",
}
DEFAULT_LANG = "전체 언어"

# 연도 슬라이더 범위
YEAR_MIN = 1950
YEAR_MAX = 2026

# ============================================================
# 5. 기관 집계 주의 — OpenAlex 자동 disambiguation 일반 캐비엇
# ============================================================
# 비영어권(한국 포함) 기관은 자동 disambiguation 과정에서 유사 기관명 흡수·
# 캠퍼스/분원 합산·자국어 기관명 누락 등이 일어나 논문 수가 과대/과소집계될 수 있음.
INST_CAVEAT = (
    "비영어권(한국 포함) 기관은 OpenAlex 자동 disambiguation 과정에서 "
    "유사 기관명 흡수·캠퍼스/분원 합산·자국어 기관명 누락 등이 일어날 수 있어 "
    "논문 수가 과대/과소집계될 수 있습니다. 곧이곧대로 비교하지 마세요."
)
