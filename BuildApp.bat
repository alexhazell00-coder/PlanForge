@echo off
setlocal
pushd "%~dp0"
where py >nul 2>nul && (py -3 packaging\build_app.py --install-pyinstaller %* & goto :done)
python packaging\build_app.py --install-pyinstaller %*
:done
popd
