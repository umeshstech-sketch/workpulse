@echo off
rem Shortcut so `.\workpulse <command>` works from the project folder without activating the venv.
"%~dp0.venv\Scripts\workpulse.exe" %*
