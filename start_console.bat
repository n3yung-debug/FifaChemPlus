@echo off
rem Same as start.bat but keeps a console window open, so error messages stay visible.
cd /d "%~dp0"
echo Starting Chem Builder... this window shows its messages. The app stops when you close its browser tab.
where python >/dev/null 2>/dev/null && (python chem_builder.py) || (py chem_builder.py)
echo.
echo The server stopped. If there is an error above, send it to Claude.
pause
