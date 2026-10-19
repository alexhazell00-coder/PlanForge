@echo off
rem Compatibility wrapper. The canonical Windows launcher is
rem PlanForgeLauncher.bat; this file is kept so older instructions keep working.
call "%~dp0PlanForgeLauncher.bat" %*
exit /b %ERRORLEVEL%
