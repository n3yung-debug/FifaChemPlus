@echo off
rem Starts Chem Builder with no console window and opens it in your browser.
rem It stops by itself about 30 seconds after you close its browser tab (or press "Stop app" in the page).
rem If the app is already running, this just opens the page again.
rem Problems? Run start_console.bat instead to see error messages, or read chem_builder.log.
cd /d "%~dp0"
where pythonw >/dev/null 2>/dev/null && (start "" pythonw chem_builder.py & exit /b 0)
where pyw >/dev/null 2>/dev/null && (start "" pyw chem_builder.py & exit /b 0)
rem No windowless Python found: fall back to a console window.
call "%~dp0start_console.bat"
