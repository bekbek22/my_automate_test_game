@echo off
REM ============================================================
REM  update.bat  --  pull the latest version of the automation
REM  from the git remote (origin/main). Safe to re-run anytime.
REM ============================================================
setlocal EnableExtensions

REM Always run from the folder this script lives in.
cd /d "%~dp0"

echo ============================================================
echo   CookieRun Automation - Update
echo ============================================================
echo.

REM --- 1. git must be installed ---------------------------------
where git >nul 2>nul
if errorlevel 1 (
    echo [ERROR] git is not installed or not on PATH.
    echo         Install Git for Windows: https://git-scm.com/download/win
    goto :end
)

REM --- 2. must be inside a git clone ----------------------------
git rev-parse --is-inside-work-tree >nul 2>nul
if errorlevel 1 (
    echo [ERROR] This folder is not a git clone -- nothing to update.
    echo         Clone the repo instead of copying the files.
    goto :end
)

echo Current version:
git log -1 --oneline
echo.

REM --- 3. warn if there are un-committed local edits -----------
git diff --quiet
set DIRTY=%errorlevel%
git diff --cached --quiet
if errorlevel 1 set DIRTY=1
if "%DIRTY%"=="1" (
    echo [WARN] You have local, un-committed changes.
    echo        The update will only run if it can fast-forward cleanly.
    echo.
)

REM --- 4. fetch + fast-forward ---------------------------------
echo Fetching latest from origin...
git fetch --prune origin
if errorlevel 1 (
    echo [ERROR] Fetch failed -- check your internet / GitHub access.
    goto :end
)
echo.

echo Updating (fast-forward only)...
git pull --ff-only
if errorlevel 1 (
    echo.
    echo [WARN] Could not fast-forward automatically.
    echo        Your local copy has diverged from origin/main.
    echo        Commit or discard your local changes, then re-run update.bat.
    goto :end
)

echo.
echo Now at:
git log -1 --oneline
echo.

REM --- 5. refresh Python deps if a requirements file exists -----
if exist requirements.txt (
    echo Updating Python dependencies...
    python -m pip install -r requirements.txt
    echo.
)

echo [OK] Update complete.

:end
echo.
pause
endlocal
