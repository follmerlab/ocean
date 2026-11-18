@echo off
REM Run ONCE per computer, with the spectrometer plugged in: installs its USB driver.
REM You will answer "y" twice: once here, and once in the administrator window that opens.
setlocal
cd /d "%~dp0"
call start.bat --setup-only || exit /b 1
echo.
echo Installing the spectrometer USB driver (downloads it; needs internet).
echo  1. Type y and press Enter.
echo  2. Click Yes when Windows asks for administrator permission.
echo  3. A second window opens: type y, press Enter, then Enter again to close it.
echo.
.venv\Scripts\seabreeze_os_setup
echo.
echo When the second window says Success, unplug and replug the spectrometer,
echo then double-click start.bat.
pause
