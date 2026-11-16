@echo off
rem Desktop launcher: start the GUI server, then open the browser.
rem If the server is already up, just open the page.
chcp 65001 >nul
cd /d "%~dp0"

python -c "import socket,sys;sys.exit(socket.socket().connect_ex(('127.0.0.1',8765)))"
if %errorlevel%==0 (
    start "" http://127.0.0.1:8765/
    exit /b
)

rem Server lives in its own minimized window; closing that window stops the server and the agent.
start "Auto Dev Crew server" /min python -m auto_dev_crew.gui

