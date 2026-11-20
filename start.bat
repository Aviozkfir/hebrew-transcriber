@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title Hebrew Transcription

echo.
echo  ==============================================
echo    Hebrew Telephone Transcription
echo  ==============================================
echo.

rem ---- 1. Find Python 3.10+ -------------------------------------------------
set "PY="
where py >nul 2>nul && py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul && set "PY=py -3"
if not defined PY (
    where python >nul 2>nul && python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo  [ERROR] Python 3.10 or newer was not found.
    echo          Install it from https://www.python.org/downloads/
    echo          and tick "Add python.exe to PATH" during installation.
    pause
    exit /b 1
)

rem ---- 2. Virtual environment + dependencies (installed once / when changed)
if not exist ".venv\Scripts\python.exe" (
    echo  Creating Python environment...
    %PY% -m venv .venv || goto :fail
)
fc /b "backend\requirements.txt" ".venv\installed-requirements.txt" >nul 2>nul
if errorlevel 1 (
    echo  Installing dependencies - first run only, this may take a minute...
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q --upgrade pip
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r backend\requirements.txt || goto :fail
    copy /y "backend\requirements.txt" ".venv\installed-requirements.txt" >nul
)

rem ---- 3. API key ------------------------------------------------------------
if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo.
    echo  A settings file was created: .env
    echo  Paste your ElevenLabs API key into it, save, and close Notepad.
    echo.
    start /wait notepad ".env"
)

rem ---- 4. Frontend (prebuilt; rebuilt only if missing and Node.js exists) -----
if not exist "frontend\dist\index.html" (
    where npm >nul 2>nul || (
        echo  [ERROR] frontend\dist is missing and Node.js is not installed.
        echo          Install Node.js from https://nodejs.org/ or restore frontend\dist.
        goto :fail
    )
    echo  Building the interface...
    pushd frontend
    call npm install || (popd & goto :fail)
    call npm run build || (popd & goto :fail)
    popd
)

rem ---- 5. Run ----------------------------------------------------------------
".venv\Scripts\python.exe" backend\run.py
goto :eof

:fail
echo.
echo  [ERROR] Startup failed. See the messages above.
pause
exit /b 1
