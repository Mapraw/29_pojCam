@echo off
setlocal
cd /d "%~dp0"
title RTSP Camera Streamer Launcher
cls

echo ===================================================
echo        RTSP CAMERA STREAMER - SELECT MODE
echo ===================================================
echo.
echo  [1] Web App (Browser Dashboard with Controls)
echo  [2] Desktop App (Native Window GUI)
echo  [3] Exit
echo.
set /p choice="Enter your choice (1, 2, or 3) [Default 1]: "

if "%choice%"=="" set choice=1
if "%choice%"=="1" goto run_web
if "%choice%"=="2" goto run_desktop
if "%choice%"=="3" goto end

:run_web
echo.
call run_web.bat
goto end

:run_desktop
echo.
call run_desktop.bat
goto end

:end
