@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === 연구동향 조사 도구 시작 ===
echo (처음 한 번은 라이브러리 설치로 1~2분 걸립니다)
python -m pip install -q -r requirements.txt
if errorlevel 1 (
  echo.
  echo [오류] Python 또는 pip 를 찾지 못했습니다.
  echo Python 3.9+ 를 https://www.python.org 에서 설치하세요 ^(설치 시 "Add to PATH" 체크^).
  pause
  exit /b 1
)
echo 브라우저에서 앱이 열립니다... (끄려면 이 창에서 Ctrl+C)
python -m streamlit run app.py
pause
