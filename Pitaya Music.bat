@echo off
cd /d "%~dp0"
rem Pin to the interpreter that has the full dependency set (Python 3.11).
rem Falls back to PATH pythonw if that install is ever removed.
set "PYW=%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe"
if exist "%PYW%" (
    start "" /B "%PYW%" gui.py
) else (
    start "" /B pythonw gui.py
)
