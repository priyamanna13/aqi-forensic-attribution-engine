@echo off
cd /d "%~dp0"
title Air Quality Intelligence Setup
echo ===================================================
echo Starting Air Quality Intelligence Platform (Task 1 & 2)
echo ===================================================
echo.

echo 1. Starting PostgreSQL Database (Docker)...
docker compose up -d
echo Database started!
echo.

echo 2. Starting FastAPI Backend Server on port 8000...
:: Opens a new terminal window for the Python server
start "FastAPI Server" cmd /k "uvicorn app.api:app --reload --port 8000"

:: Wait 3 seconds for the server to spin up
timeout /t 3 /nobreak > nul

echo.
echo 3. Starting Ngrok Tunnel...
:: Opens a new terminal window for Ngrok
start "Ngrok Tunnel" cmd /k "ngrok http 127.0.0.1:8000"

echo.
echo ===================================================
echo DONE! All services are starting up.
echo - Keep the two new black windows open.
echo - Look at the 'Ngrok Tunnel' window to find your 'Forwarding' URL.
echo - Give that URL to your team!
echo ===================================================
pause
