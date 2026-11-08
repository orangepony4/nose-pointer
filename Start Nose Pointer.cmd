@echo off
setlocal
pushd "%~dp0" || exit /b 1

where uv >nul 2>&1
if errorlevel 1 (
    echo Install uv first: https://docs.astral.sh/uv/getting-started/installation/
    goto failed
)
if exist ".venv\Scripts\python.exe" (
    uv sync --locked --offline --python 3.12 >nul 2>&1
    if not errorlevel 1 goto model
)
uv sync --locked --python 3.12
if errorlevel 1 goto failed

:model
".venv\Scripts\python.exe" nose_pointer.py --download-model
if errorlevel 1 goto failed

".venv\Scripts\python.exe" nose_pointer.py %*
if errorlevel 1 goto failed
popd
exit /b 0

:failed
echo Nose Pointer could not start. See README.md for setup instructions.
popd
pause
exit /b 1
