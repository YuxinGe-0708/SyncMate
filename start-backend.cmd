@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
)
.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
if "%DASHSCOPE_API_KEY%"=="" (
  echo [SyncMate] Warning: DASHSCOPE_API_KEY is not set. AI receipt splitting will be unavailable.
)
.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
