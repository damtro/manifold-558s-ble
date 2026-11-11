@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
echo Testo 115i Windows test
echo Extract the entire ZIP before running this file.
echo.
if exist ".venv\Scripts\python.exe" goto run
echo Creating a local Python environment...
where py >nul 2>&1
if errorlevel 1 goto python_fallback
py -3 -m venv .venv
if errorlevel 1 goto setup_failed
goto run
:python_fallback
where python >nul 2>&1
if errorlevel 1 goto missing_python
python -m venv .venv
if errorlevel 1 goto setup_failed
:run
".venv\Scripts\python.exe" -u windows_test.py
set "TEST_RESULT=%ERRORLEVEL%"
echo.
echo Test launcher exit code: %TEST_RESULT%
echo Press any key to close this window.
pause >nul
exit /b %TEST_RESULT%
:missing_python
echo Python was not found. Install Python 3.11 or newer from python.org.
echo Then double-click this file again.
pause
exit /b 1
:setup_failed
echo Could not create the Python environment. Check the error above.
echo Use Python 3.11 or newer and extract the ZIP into a writable folder.
pause
exit /b 1
