# scimago_sjr — 저널 쿼타일(Q1~Q4) 데이터

이 폴더의 CSV/XLSX 원본은 **저작권(CC BY-NC)** 때문에 저장소에 포함하지 않습니다(`.gitignore`).
저널 쿼타일을 보려면 각자 한 번 내려받으세요. **없어도 앱은 동작**하며, SJR 열만 비게 됩니다.

## 받는 법
1. https://www.scimagojr.com/journalrank.php 접속
2. (선택) 분야/연도 필터 지정
3. 우측 상단 **Download data** 클릭 → `scimagojr 2025.csv` 저장
4. 이 폴더(`scimago_sjr/`)에 그대로 넣기

파일명이 `scimagojr*.csv` 패턴이면 앱이 자동 인식합니다(연도 큰 파일 우선).
세미콜론(`;`) 구분·소수점 콤마(`,`) 형식 그대로 두면 됩니다 — `scimago.py`가 처리합니다.

## 출처·라이선스
- SCImago, (n.d.). *SJR — SCImago Journal & Country Rank.* https://www.scimagojr.com
- 라이선스: CC BY-NC. 연구 내부용으로만 사용하세요.
