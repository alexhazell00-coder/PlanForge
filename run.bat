@echo off
rem PlanForge launcher for Windows 10 and 11.
rem
rem This file only locates a Python interpreter and delegates to launcher.py.
rem Environment creation, dependency installation, logging and startup logic
rem all live in launcher.py, so fixes there benefit every platform.
rem
rem Double-click this file to start PlanForge.  Pass any arguments to use the
rem console entry point instead, for example:
rem     run.bat --check
rem     run.bat --import-file schedule.xml --export-file schedule.gan

setlocal EnableExtensions
set "PLANFORGE_ROOT=%~dp0"
set "PLANFORGE_LAUNCHER=%PLANFORGE_ROOT%launcher.py"
set "PLANFORGE_VENV_PYTHONW=%PLANFORGE_ROOT%.venv\Scripts\pythonw.exe"

if not exist "%PLANFORGE_LAUNCHER%" (
    echo PlanForge could not find launcher.py next to run.bat.
    echo Keep run.bat in the PlanForge folder and try again.
    pause
    exit /b 1
)

rem Any command-line argument means a console session (--check, --import-file,
rem --help and so on).  Double-clicking with no arguments starts the GUI.
if not "%~1"=="" goto :console

rem GUI launch: find a system Python and use its windowed companion so that no
rem console window appears.  launcher.py shows a small setup window on the
rem first launch.  The prepared .venv is validated and repaired by the
rem launcher itself; the venv interpreter is only a fallback when Python is no
rem longer on PATH.
call :find_python
if not defined PLANFORGE_PYTHON goto :gui_venv_fallback

set "PLANFORGE_PYTHONW=%PLANFORGE_PYTHON%"
for %%I in ("%PLANFORGE_PYTHON%") do set "PLANFORGE_PYTHONW=%%~dpIpythonw.exe"
if not exist "%PLANFORGE_PYTHONW%" set "PLANFORGE_PYTHONW=%PLANFORGE_PYTHON%"

start "" "%PLANFORGE_PYTHONW%" "%PLANFORGE_LAUNCHER%" --gui --hide-console
exit /b 0

:gui_venv_fallback
if exist "%PLANFORGE_VENV_PYTHONW%" (
    start "" "%PLANFORGE_VENV_PYTHONW%" "%PLANFORGE_LAUNCHER%" --gui --hide-console
    exit /b 0
)
goto :no_python

:console
call :find_python
if not defined PLANFORGE_PYTHON (
    if exist "%PLANFORGE_ROOT%.venv\Scripts\python.exe" (
        set "PLANFORGE_PYTHON=%PLANFORGE_ROOT%.venv\Scripts\python.exe"
    )
)
if not defined PLANFORGE_PYTHON goto :no_python
"%PLANFORGE_PYTHON%" "%PLANFORGE_LAUNCHER%" %*
set "PLANFORGE_RC=%ERRORLEVEL%"
exit /b %PLANFORGE_RC%

:find_python
rem Prefer the Python launcher ("py -3"), then python on PATH.  Ask Python
rem itself for the real executable path so spaces in the installation path
rem and Microsoft Store aliases are handled reliably.
set "PLANFORGE_PYTHON="
where py >nul 2>nul
if not errorlevel 1 (
    for /f "delims=" %%P in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do set "PLANFORGE_PYTHON=%%P"
)
if defined PLANFORGE_PYTHON call :check_python
if defined PLANFORGE_PYTHON exit /b 0
where python >nul 2>nul
if not errorlevel 1 (
    for /f "delims=" %%P in ('python -c "import sys;print(sys.executable)" 2^>nul') do set "PLANFORGE_PYTHON=%%P"
)
if defined PLANFORGE_PYTHON call :check_python
exit /b 0

:check_python
rem launcher.py needs Python 3.7+ to explain anything useful.  Older
rem interpreters are discarded so the .venv fallback or the install
rem instructions are used instead.
"%PLANFORGE_PYTHON%" -c "import sys; sys.exit(0 if sys.version_info >= (3, 7) else 1)" >nul 2>nul
if errorlevel 1 set "PLANFORGE_PYTHON="
exit /b 0

:no_python
echo.
echo PlanForge needs Python 3.10 or newer, but Python was not found.
echo.
echo Install Python from https://www.python.org/downloads/windows/
echo During installation, tick "Add python.exe to PATH".
echo If typing python opens the Microsoft Store, install Python from
echo python.org instead, then double-click run.bat again.
echo.
pause
exit /b 9009
