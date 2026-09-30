@echo off
cd /d "%~dp0"
rem Pin to the interpreter that has the full dependency set (Python 3.11).
rem Falls back to PATH python if that install is ever removed.
set "PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if exist "%PY%" (
    "%PY%" 启动器.py
) else (
    python 启动器.py
)
