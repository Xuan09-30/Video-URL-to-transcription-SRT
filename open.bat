@echo off
if not exist venv ( python -m venv venv )
call venv\Scripts\activate
python -m pip install -U -r requirements.txt
python -m pip install -U --pre "yt-dlp[default]"
echo Open http://127.0.0.1:8000 in your browser
python -m uvicorn app:app
pause