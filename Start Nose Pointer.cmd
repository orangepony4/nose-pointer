@echo off
setlocal DisableDelayedExpansion
pushd "%~dp0" || exit /b 1

rem Only use an installed uv from PATH or the verified app-local copy.
set "NoDefaultCurrentDirectoryInExePath=1"
set "UV_COMMAND=uv.exe"
"%SystemRoot%\System32\where.exe" $PATH:uv.exe >nul 2>&1
if errorlevel 1 (
    call :prepare_local_uv
    if errorlevel 1 goto failed
)
if exist ".venv\Scripts\python.exe" (
    "%UV_COMMAND%" sync --locked --offline --python 3.12 >nul 2>&1
    if not errorlevel 1 goto model
)
"%UV_COMMAND%" sync --locked --python 3.12
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

:prepare_local_uv
if /i not "%PROCESSOR_ARCHITECTURE%"=="AMD64" if /i not "%PROCESSOR_ARCHITEW6432%"=="AMD64" (
    echo Automatic setup requires Windows x64.
    exit /b 1
)
for %%T in (curl.exe tar.exe certutil.exe findstr.exe) do if not exist "%SystemRoot%\System32\%%T" (
    echo Automatic setup needs %%T. Install uv and run the launcher again.
    echo https://docs.astral.sh/uv/getting-started/installation/
    exit /b 1
)
set "UV_BOOTSTRAP=%CD%\.uv-bootstrap"
set "UV_COMMAND=%UV_BOOTSTRAP%\uv.exe"
set "UV_CACHE_DIR=%UV_BOOTSTRAP%\cache"
set "UV_PYTHON_INSTALL_DIR=%UV_BOOTSTRAP%\python"
rem Hashes of the official x64 release archive and its uv.exe.
set "UV_VERSION=0.13.1"
set "UV_ZIP_SHA=3b2661a463a5baea7f5076ea2b25ab71d77f36a6c0d809e5350651792f80a672"
set "UV_EXE_SHA=4075a09490327d2bedfacc807fa48252fb93647c5bd7ef28f00e579160ea3fb5"
set "VERIFY_FILE=%UV_COMMAND%"
set "VERIFY_HASH=%UV_EXE_SHA%"
if exist "%VERIFY_FILE%" (
    call :verify_sha256
    if not errorlevel 1 exit /b 0
)
if not exist "%UV_BOOTSTRAP%\." md "%UV_BOOTSTRAP%" 2>nul
if not exist "%UV_BOOTSTRAP%\." exit /b 1
set "UV_STAGE=%UV_BOOTSTRAP%\setup-%RANDOM%-%RANDOM%"
md "%UV_STAGE%" || exit /b 1

echo Downloading and verifying uv %UV_VERSION% for this folder...
set "VERIFY_FILE=%UV_STAGE%\uv.zip"
set "VERIFY_HASH=%UV_ZIP_SHA%"
"%SystemRoot%\System32\curl.exe" --disable --fail --silent --show-error --location --proto "=https" --proto-redir "=https" --connect-timeout 15 --max-time 90 --retry 2 --output "%VERIFY_FILE%" "https://github.com/astral-sh/uv/releases/download/%UV_VERSION%/uv-x86_64-pc-windows-msvc.zip"
if errorlevel 1 goto bootstrap_failed
call :verify_sha256
if errorlevel 1 goto bootstrap_failed
"%SystemRoot%\System32\tar.exe" -xOf - uv.exe < "%VERIFY_FILE%" > "%UV_STAGE%\uv.exe"
if errorlevel 1 goto bootstrap_failed
set "VERIFY_FILE=%UV_STAGE%\uv.exe"
set "VERIFY_HASH=%UV_EXE_SHA%"
call :verify_sha256
if errorlevel 1 goto bootstrap_failed

move /y "%VERIFY_FILE%" "%UV_COMMAND%" >nul 2>&1
rem A concurrent launcher may already have placed a verified copy.
set "VERIFY_FILE=%UV_COMMAND%"
call :verify_sha256
if errorlevel 1 goto bootstrap_failed
call :clean_uv_stage
exit /b 0

:bootstrap_failed
call :clean_uv_stage
echo Could not prepare a verified copy of uv. Check your connection and try again.
exit /b 1

:clean_uv_stage
if exist "%UV_STAGE%\uv.exe" del /q "%UV_STAGE%\uv.exe"
if exist "%UV_STAGE%\uv.zip" del /q "%UV_STAGE%\uv.zip"
rd "%UV_STAGE%" 2>nul
exit /b 0

:verify_sha256
"%SystemRoot%\System32\certutil.exe" -hashfile "%VERIFY_FILE%" SHA256 2>nul | "%SystemRoot%\System32\findstr.exe" /i /x /c:"%VERIFY_HASH%" >nul
exit /b %errorlevel%
