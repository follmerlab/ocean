@echo off
REM Double-click to start the Flame spectrometer interface on Windows.
REM The first run builds a private Python environment in .venv (needs internet, ~2 min).
setlocal
cd /d "%~dp0"

REM Use the environment if it works (this also repairs an interrupted first install).
if exist .venv\Scripts\python.exe (
    .venv\Scripts\python -c "import flask, numpy, seabreeze" >nul 2>&1 && goto :run
    echo The Python environment is incomplete; rebuilding it...
    rmdir /s /q .venv
)

REM The spectrometer library (seabreeze) has Windows packages for Python 3.11-3.14,
REM not yet for 3.15, so pick a supported version through the py launcher.
set "PY="
for %%v in (3.14 3.13 3.12 3.11) do (
    if not defined PY (
        py -%%v -c "" >nul 2>&1 && set "PY=py -%%v"
    )
)
if not defined PY goto :nopython

echo First run: setting up Python with %PY% (needs internet, about 2 minutes)...
%PY% -m venv .venv || goto :fail
.venv\Scripts\python -m pip install --upgrade pip --quiet || goto :fail
.venv\Scripts\python -m pip install -r requirements.txt || goto :fail
echo Setup finished.

:run
if /i "%~1"=="--setup-only" exit /b 0
.venv\Scripts\python app.py %*
if not defined CI pause
exit /b 0

:nopython
echo.
echo  Python 3.14 (or 3.11-3.13) is needed and was not found.
echo  Python 3.15 is too new: the spectrometer library does not support it yet.
echo.
echo  Install Python 3.14 from https://www.python.org/downloads/windows/
echo  (pick a 3.14.x "Windows installer (64-bit)"), or, if you have the
echo  Python install manager, run:   py install 3.14
echo  Then double-click start.bat again.
echo.
if not defined CI pause
exit /b 1

:fail
echo.
echo  Setup failed; see the messages above. Check the internet connection and
echo  double-click start.bat again (it resumes automatically).
if not defined CI pause
exit /b 1
