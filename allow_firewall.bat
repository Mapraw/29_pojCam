@echo off
title Unblock Flask & Python in Windows Firewall

:: Self-elevation to Administrator
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Requesting Administrator privileges to unblock firewall...
    powershell -Command "Start-Process cmd -ArgumentList '/c \"%~fn0\"' -Verb RunAs"
    exit /b
)

echo =========================================================
echo   UNBLOCKING PYTHON & PORTS IN WINDOWS FIREWALL
echo =========================================================
echo.

:: Allow Python.exe directly
set PYTHON_PATH=C:\Users\Jarup\AppData\Local\Programs\Python\Python312\python.exe
echo 1. Allowing Python executable: %PYTHON_PATH%
netsh advfirewall firewall add rule name="Python 3.12 App" dir=in action=allow program="%PYTHON_PATH%" enable=yes profile=any

:: Allow Port 5000
echo 2. Allowing TCP Port 5000...
netsh advfirewall firewall add rule name="RTSP Camera Web Server Port 5000" dir=in action=allow protocol=TCP localport=5000 enable=yes profile=any

:: Allow Port 8080 (fallback)
echo 3. Allowing TCP Port 8080...
netsh advfirewall firewall add rule name="RTSP Camera Web Server Port 8080" dir=in action=allow protocol=TCP localport=8080 enable=yes profile=any

echo.
echo =========================================================
echo   [SUCCESS] Firewall rules added successfully!
echo.
echo   Try opening on your smartphone:
echo   - Main Wi-Fi: http://192.168.1.54:5000
echo   - If on PC Hotspot: http://192.168.137.1:5000
echo =========================================================
echo.
pause
