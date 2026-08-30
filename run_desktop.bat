@echo off
setlocal
cd /d "%~dp0"
title RTSP Stream Desktop App

echo ===================================================
echo           RTSP CAMERA DESKTOP STREAMER
echo ===================================================
echo.

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

echo Starting Native Desktop Streamer GUI with %PY_CMD%...
echo.

%PY_CMD% desktop_app.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Application exited with error code %ERRORLEVEL%.
)

pause
