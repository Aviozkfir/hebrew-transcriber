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

rem ---- 1. Find Python 3.10+ (installed automatically if missing) ------------
call :find_python
if not defined PY (
    echo  Python 3.10 or newer was not found. Installing Python 3.12 automatically...
    echo  This happens only once and takes a few minutes. No administrator rights are needed.
    echo.
    call :install_python
    call :find_python
)
if not defined PY (
    echo  [ERROR] Python could not be installed automatically.
    echo          Install it from https://www.python.org/downloads/
    echo          and tick "Add python.exe to PATH" during installation.
    goto :fail
)

rem ---- 2. Virtual environment + dependencies (installed once / when changed)
rem Some package files have very long names. Windows limits paths to 260 characters
rem unless "long paths" are enabled, so enable them, or else keep the environment
rem in a short folder (C:\htenv) instead of .venv inside this folder.
call :check_long_paths
if not defined LONGPATHS (
    echo  Windows long file paths are not enabled. They are needed to install the dependencies.
    echo  Windows will ask for permission to enable them. Click "Yes".
    echo.
    powershell -NoProfile -Command "try { Start-Process reg -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList 'add','HKLM\SYSTEM\CurrentControlSet\Control\FileSystem','/v','LongPathsEnabled','/t','REG_DWORD','/d','1','/f' } catch { exit 1 }"
    call :check_long_paths
)
set "VENV=.venv"
if not defined LONGPATHS (
    set "VENV=%SystemDrive%\htenv"
    echo  Long paths are still disabled, so the Python environment will be kept in %SystemDrive%\htenv instead.
)
if not exist "%VENV%\Scripts\python.exe" (
    echo  Creating Python environment...
    %PY% -m venv "%VENV%" || goto :fail
)
fc /b "backend\requirements.txt" "%VENV%\installed-requirements.txt" >nul 2>nul
if errorlevel 1 (
    echo  Installing dependencies - first run only, this may take a minute...
    "%VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check -q --upgrade pip
    "%VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r backend\requirements.txt || goto :fail
    copy /y "backend\requirements.txt" "%VENV%\installed-requirements.txt" >nul
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
"%VENV%\Scripts\python.exe" backend\run.py
goto :eof

:fail
echo.
echo  [ERROR] Startup failed. See the messages above.
pause
exit /b 1

rem ---- Helpers ---------------------------------------------------------------

:check_long_paths
set "LONGPATHS="
reg query "HKLM\SYSTEM\CurrentControlSet\Control\FileSystem" /v LongPathsEnabled 2>nul | find "0x1" >nul && set "LONGPATHS=1"
exit /b 0

:find_python
rem Sets PY to a Python 3.10+ command, or leaves it empty if none is found.
set "PY="
set "PYCHECK=import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"
where py >nul 2>nul && py -3 -c "%PYCHECK%" >nul 2>nul && set "PY=py -3"
if not defined PY (
    where python >nul 2>nul && python -c "%PYCHECK%" >nul 2>nul && set "PY=python"
)
rem A Python installed moments ago is not on this window's PATH yet, so look in the usual folders.
if not defined PY (
    for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*" "%ProgramFiles%\Python3*") do (
        if not defined PY if exist "%%~D\python.exe" "%%~D\python.exe" -c "%PYCHECK%" >nul 2>nul && set PY="%%~D\python.exe"
    )
)
exit /b 0

:install_python
rem First try winget (built into Windows 10/11), installing for the current user only.
where winget >nul 2>nul && (
    echo  Installing Python with winget...
    winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
)
call :find_python
if defined PY exit /b 0

rem Fallback: download the official installer from python.org and run it silently.
set "PYINST=%TEMP%\python-3.12.10-amd64.exe"
set "PYURL=https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"
echo  Downloading Python from python.org...
curl.exe -L --fail -s -o "%PYINST%" "%PYURL%" || powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri '%PYURL%' -OutFile '%PYINST%'"
if not exist "%PYINST%" (
    echo  [ERROR] Could not download Python. Check your internet connection.
    exit /b 1
)
echo  Running the Python installer...
"%PYINST%" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 InstallLauncherAllUsers=0 Include_test=0
del "%PYINST%" >nul 2>nul
exit /b 0
