@echo off
cd /d "%~dp0"
title Air Quality Intelligence Setup
cls

echo =====================================================================
echo    AIR QUALITY FORENSIC ATTRIBUTION ENGINE - LOCAL SYSTEM SETUP
echo =====================================================================
echo.

echo [1/5] Starting PostgreSQL + PostGIS Database Container...
docker compose up -d db
if %ERRORLEVEL% neq 0 (
    echo.
    echo ❌ ERROR: Failed to start database container. Make sure Docker is running!
    pause
    exit /b %ERRORLEVEL%
)
echo DB started successfully!
echo.

:: Wait 3 seconds for the DB health check to settle
echo Waiting for database to accept connections...
timeout /t 3 /nobreak > nul
echo.

echo [2/5] Running Database Migrations and Seeding Initial Pune Data...
python db/seed_data.py
if %ERRORLEVEL% neq 0 (
    echo.
    echo ⚠️ WARNING: Database seeding failed.
    echo Make sure your PostgreSQL credentials in .env are correct and python dependencies are installed.
    echo.
) else (
    echo DB seeding completed successfully!
)
echo.

echo [3/5] Starting FastAPI Backend Server on port 8000...
:: Opens a new terminal window for the Python FastAPI server
start "FastAPI Backend Server" cmd /k "title FastAPI Backend && python -m uvicorn api.main:app --reload --port 8000"

:: Wait 2 seconds for backend to start up
timeout /t 2 /nobreak > nul
echo Backend server spawned in a new window!
echo.

echo [4/5] Starting Background Scheduler (CPCB / OWM / Overpass)...
:: Opens a new terminal window for the APScheduler background tasks
start "APScheduler background runner" cmd /k "title Background Scheduler && python scheduler/scheduler.py"
echo Scheduler spawned in a new window!
echo.

echo [5/5] Launching Frontend Development Server...
cd frontend
if not exist node_modules (
    echo Node modules not found. Installing package dependencies...
    call npm install
)
:: Opens a new terminal window for the Vite dev server
start "Vite React Frontend" cmd /k "title React Frontend (Vite) && npm run dev"
echo Frontend spawned in a new window!
echo.

echo =====================================================================
echo 🎉 SUCCESS! All services are active.
echo.
echo - Keep all terminal windows open.
echo - Frontend is running at: http://localhost:5173
echo - Backend API is running at: http://localhost:8000
echo - API docs are available at: http://localhost:8000/docs
echo =====================================================================
echo.
pause
