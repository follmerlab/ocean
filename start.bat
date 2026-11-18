@echo off
REM Double-click to start the Flame spectrometer interface on Windows.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    echo First run: creating Python environment...
    py -3 -m venv .venv || python -m venv .venv || goto :nopython
    .venv\Scripts\python -m pip install --upgrade pip
    .venv\Scripts\python -m pip install -r requirements.txt || goto :fail
)
.venv\Scripts\python app.py %*
pause
exit /b

:nopython
echo Python 3.11+ was not found. Install it from https://www.python.org/downloads/ (tick "Add to PATH").
pause
exit /b 1

:fail
echo Package install failed; see the messages above.
pause
exit /b 1
