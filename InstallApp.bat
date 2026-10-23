@echo off
setlocal
pushd "%~dp0"
where py >nul 2>nul && (py -3 packaging\install_desktop_app.py %* & goto :done)
python packaging\install_desktop_app.py %*
:done
popd
