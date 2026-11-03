@echo off
rem Double-click to rebuild the app and installer into dist\.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build.ps1" %*
if errorlevel 1 echo. & echo BUILD FAILED. See the messages above.
pause
