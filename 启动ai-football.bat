@echo off
setlocal
cd /d "%~dp0backend"

set "MYSQL_HOME=G:\mysql-local\mysql-8.0.29-winx64"
set "MYSQL_DATA=G:\mysql-local\data"

if not exist ".venv\Scripts\python.exe" goto no_venv

echo ============================================
echo    ai-football dashboard
echo ============================================
echo.

REM ---- step 1: make sure MySQL is listening on 3306 ----
powershell -NoProfile -Command "try{$c=New-Object Net.Sockets.TcpClient;$c.Connect('127.0.0.1',3306);$c.Close();exit 0}catch{exit 1}" >nul 2>&1
if errorlevel 1 goto start_mysql
goto mysql_ok

:start_mysql
echo MySQL is not running. Starting it...
if not exist "%MYSQL_HOME%\bin\mysqld.exe" goto no_mysqld
start "mysql" /min "%MYSQL_HOME%\bin\mysqld.exe" --datadir=%MYSQL_DATA%
echo Waiting for MySQL to become ready...
powershell -NoProfile -Command "for($i=0;$i -lt 40;$i++){ try{$c=New-Object Net.Sockets.TcpClient;$c.Connect('127.0.0.1',3306);$c.Close();exit 0}catch{Start-Sleep -Seconds 1} }; exit 1"
if errorlevel 1 goto mysql_timeout
echo MySQL is up.

:mysql_ok
REM ---- step 2: reuse a running server, otherwise start one ----
powershell -NoProfile -Command "try{(Invoke-WebRequest 'http://127.0.0.1:8000/api/health' -UseBasicParsing -TimeoutSec 2)|Out-Null;exit 0}catch{exit 1}" >nul 2>&1
if errorlevel 1 goto start_app
echo Server already running. Opening dashboard...
start "" "http://127.0.0.1:8000/"
exit /b 0

:start_app
echo Starting backend server in a new window...
echo (close that window to stop the service)
start "ai-football server" ".venv\Scripts\python.exe" -m uvicorn main:app --host 127.0.0.1 --port 8000
echo Waiting for the server to become ready...
powershell -NoProfile -Command "$ok=$false; for($i=0;$i -lt 45;$i++){ try{ (Invoke-WebRequest 'http://127.0.0.1:8000/api/health' -UseBasicParsing -TimeoutSec 2) | Out-Null; $ok=$true; break } catch { Start-Sleep -Seconds 1 } }; if($ok){ Start-Process 'http://127.0.0.1:8000/'; Write-Host 'Dashboard opened: http://127.0.0.1:8000/'; exit 0 } else { Write-Host 'Timeout. Please open http://127.0.0.1:8000/ manually.'; exit 1 }"
if errorlevel 1 pause
exit /b 0

:no_venv
echo [ERROR] venv not found: backend\.venv\Scripts\python.exe
echo Please create the venv and install dependencies first.
pause
exit /b 1

:no_mysqld
echo [ERROR] mysqld.exe not found: %MYSQL_HOME%\bin\mysqld.exe
pause
exit /b 1

:mysql_timeout
echo [ERROR] MySQL failed to start within 40 seconds.
pause
exit /b 1