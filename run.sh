#!/usr/bin/env bash
# 연구동향 조사 도구 실행 (Mac/Linux)
cd "$(dirname "$0")" || exit 1
echo "=== 연구동향 조사 도구 시작 ==="
echo "(처음 한 번은 라이브러리 설치로 1~2분 걸립니다)"

PY=python3
command -v $PY >/dev/null 2>&1 || PY=python
if ! command -v $PY >/dev/null 2>&1; then
  echo "[오류] Python 을 찾지 못했습니다. Python 3.9+ 를 설치하세요: https://www.python.org"
  exit 1
fi

$PY -m pip install -q -r requirements.txt || { echo "[오류] 라이브러리 설치 실패"; exit 1; }
echo "브라우저에서 앱이 열립니다... (끄려면 Ctrl+C)"
$PY -m streamlit run app.py
