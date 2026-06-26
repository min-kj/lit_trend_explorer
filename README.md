# lit_trend_explorer

OpenAlex 기반 **연구동향·선행연구·연구자 분석** Streamlit 워크벤치.
검색 쿼리든 · DOI 세트든 · RIS/Excel 업로드든 — **같은 분석 엔진**(표·동향·토픽·연구자·네트워크)에 태웁니다.
회원가입·API 키·결제 불필요(OpenAlex 무료 polite pool).

> **원칙:** 화면의 모든 수치는 OpenAlex의 집계(`group_by`)/공개 통계 또는 비지도 통계입니다 — **LLM 추론이 아니라 레코드까지 역추적 가능**합니다.

## 입력 3가지 → 같은 분석
- **검색**: 전 분야(OpenAlex 도메인4·필드26·세분류252, 수준 선택 + 복수 체크) · 키워드(동의어 OR `|`) · 검색범위·구문일치 · 저자(이름·ORCID·ID) · 기관(autocomplete·ROR) · 연도
- **🔗 DOI 세트**: 가진 DOI 목록만 붙여넣어 그 논문들로 바로 분석(검색 불필요)
- **🇰🇷 KCI/RIS 병합**: RISS·KCI·DBpia 등의 RIS/Excel 업로드 → OpenAlex가 못 잡는 논문 보강(DOI/제목 중복 자동 제거)

## 4개 탭
- **🔎 검색 결과** — 표(제목·연도·저자·학술지·SJR·IF\*·저널h·DOAJ·피인용·OA·DOI), **SJR 우선 정렬** 토글(Scimago 업로드 시 Q1→Q4 순·미등재 아래로), 행 선택 시 초록·상세, 커버리지 결측률 배지, 코퍼스 투명성 패널, **CSV/BibTeX/RIS/분류 프롬프트** 내보내기
- **📊 동향 대시보드** — 연도추이 + 상위 저자·학술지·기관·기관유형·토픽·분야·국가 + OA비율 + 국가 공저 매트릭스. 저자·기관·국가는 **전수(full) ↔ 분수(fractional)** 전환(다수공저 보정)
- **🔬 토픽 발견** — 복원한 초록을 **LDA 주제 클러스터링** + **최적 토픽수(k) 추천**(coherence/perplexity) + **rising terms**(연도 전후 TF-IDF). *탐색적 분석*임을 명시
- **👤 연구자 분석** — 저자/기관 **프로필**(h-index·i10·2yr피인용, 생산성·피인용 연도추이, 연구주제, 주요 공저자/소속 상위저자, 소속이력, 기관 지도·연관기관) + 국가 분석 + **협업 네트워크**

## 실행
가장 쉬운 법: `run.bat` 더블클릭(Windows) / `bash run.sh`(Mac·Linux).
직접:
```bash
pip install -r requirements.txt
streamlit run app.py
```
(선택) polite-pool 이메일: 환경변수 `OPENALEX_MAILTO=you@example.com`.

## Streamlit Community Cloud 배포
1. 이 폴더를 GitHub 레포로 두고(루트에 `app.py`·`requirements.txt`), share.streamlit.io 에서 **Main file = `app.py`** 로 Deploy.
2. (선택) 앱 **Settings → Secrets**:
   ```toml
   OPENALEX_MAILTO = "you@example.com"
   # 기본 분야를 두고 싶으면:
   OPENALEX_DEFAULT_LEVEL = "subfield"   # none|domain|field|subfield
   OPENALEX_DEFAULT_IDS = "3321"          # '|' 로 복수 (예: "33|22")
   ```

## 분야 분류
OpenAlex Topics 4계층(Domain 4 · Field 26 · Subfield 252 · Topic). UI에서 **수준을 고르고 그 수준에서 복수 선택**(OR `|` 결합). 옵션 목록은 앱이 OpenAlex에서 동적으로 가져옵니다. 기본 분야는 위 `OPENALEX_DEFAULT_*` 로 설정(미설정 시 제한 없음).

## 저널 쿼타일(SJR)
사이드바 "저널 쿼타일 데이터"에서 **Scimago CSV**(scimagojr.com → Download data)를 업로드하면 ISSN 매칭으로 Q1~Q4 표시. SJR이 빈 저널 = Scopus 비등재·ISSN 불일치·단행본 등(IF\*·저널h로 가늠 가능). 저작권(CC BY-NC)상 데이터 파일은 저장소에 미포함 — 각자 내려받으세요(`scimago_sjr/README.md`).

## 한계
- **메타데이터+초록만**(전문 PDF 없음). 초록 없는 레코드 존재.
- **저자·기관 disambiguation은 자동** — 동명이인 병합/분할·기관 오귀속 가능(특히 한국 기관; 앱에 캐비엇 표시).
- **한국어·KCI 커버리지 부분적** — 국내 문헌은 누락 가능 → RIS/Excel 병합으로 보강.
- h-index·피인용은 **오픈 인용 기반** → 상용 DB(WoS/Scopus)보다 과소집계일 수 있음. SJR/Scimago는 Scopus 등재지 한정.
- 동향 대시보드는 OpenAlex `group_by`(전체 매칭) 기준, 네트워크·분수계수·국가 매트릭스는 표시된 결과 기준.

## 파일
| 파일 | 역할 |
|---|---|
| `config.py` | 설정·polite pool·기본 분야·SJR 카테고리 매핑 |
| `openalex_client.py` | 검색·집계·초록복원·저자/기관 프로필·분류체계 |
| `analysis.py` | LDA·k 추천·rising terms·공동등장 네트워크·분수계수 |
| `scimago.py` | Scimago SJR 쿼타일 매칭 |
| `kci_merge.py` | RIS/Excel 파싱·병합 |
| `exporters.py` | CSV/BibTeX/RIS/분류 프롬프트 |
| `app.py` | Streamlit UI |

## 의존성
`streamlit · requests · pandas · plotly · scikit-learn · openpyxl · networkx`
