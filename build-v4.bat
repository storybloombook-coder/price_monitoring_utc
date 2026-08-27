@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build-v4.ps1" %*
