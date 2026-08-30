@echo off
setlocal
cd /d "%~dp0"
title RTSP Stream Web App

echo ===================================================
echo            RTSP CAMERA WEB STREAMER
echo ===================================================
echo.
echo Current directory: %CD%

:: Check Python availability
where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    where py >nul 2>&1
    if %ERRORLEVEL% NEQ 0 (
        echo [ERROR] Python is not found in your PATH.
        echo Please ensure Python is installed and added to PATH.
        echo.
        pause
        exit /b 1
    ) else (
        set PY_CMD=py
    )
) else (
    set PY_CMD=python
)

echo Starting Web Streamer App with %PY_CMD%...
echo Target RTSP URL will be read from high_qual.txt
echo.

%PY_CMD% app.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Application exited with error code %ERRORLEVEL%.
)

pause
