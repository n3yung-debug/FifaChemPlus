@echo off
cd /d "%~dp0"
echo Starting Chem Builder... keep this window open while you use the app.
where python >nul 2>nul && (python chem_builder.py) || (py chem_builder.py)
echo.
echo The server stopped. If there is an error above, send it to Claude.
pause
