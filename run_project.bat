@echo off
setlocal
title IRS One-Click Launcher

echo.
echo ==========================================
echo IRS One-Click Launcher
echo Dashboard + Publication Package
echo ==========================================
echo.

cd /d "%~dp0"

if not exist backend\app.py (
    echo ERROR: backend\app.py not found
    pause
    exit /b 1
)

if not exist frontend\index.html (
    echo ERROR: frontend\index.html not found
    pause
    exit /b 1
)

REM Force correct Python (system Python, not MySQL)
set "PYTHON_CMD=%LocalAppData%\Programs\Python\Python312\python.exe"

REM Fallback if not found
if not exist "%PYTHON_CMD%" (
    set "PYTHON_CMD=python"
)
echo Checking Python environment...
"%PYTHON_CMD%" -c "import flask, flask_cors, numpy, matplotlib" >nul 2>&1

if errorlevel 1 (
    echo Installing backend requirements...

    REM Ensure pip exists (fix for MySQL Python issue)
    "%PYTHON_CMD%" -m ensurepip --upgrade >nul 2>&1

    REM Force upgrade pip using correct interpreter
    "%PYTHON_CMD%" -m pip install --upgrade pip

    REM Install requirements safely
    "%PYTHON_CMD%" -m pip install -r "%~dp0backend\requirements.txt"

    if errorlevel 1 (
        echo.
        echo Dependency installation failed.
        echo Try running manually:
        echo python -m pip install -r backend\requirements.txt
        pause
        exit /b 1
    )
)
echo Starting backend on http://localhost:5000 ...
start "IRS Backend" cmd /k "cd /d "%~dp0backend" && "%PYTHON_CMD%" app.py"

timeout /t 4 >nul

echo Starting frontend server on http://localhost:8080 ...
start "IRS Frontend" cmd /k "cd /d "%~dp0frontend" && "%PYTHON_CMD%" -m http.server 8080"

timeout /t 2 >nul

echo Opening browser...
start http://localhost:8080

echo.
echo Starting background verification and publication build...
start "IRS Validation + Publication" cmd /k "cd /d "%~dp0backend" && "%PYTHON_CMD%" -m unittest test_smoke.py && "%PYTHON_CMD%" generate_publication_package.py --mode full --mc 180 --seed 2026"

echo.
echo Dashboard is ready now:
echo   http://localhost:8080
echo.
echo Publication assets will be generated in the background window:
echo   %~dp0results\publication_package
echo   %~dp0paper
echo.
pause
