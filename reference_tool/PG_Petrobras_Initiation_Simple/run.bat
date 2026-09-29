@echo off
SETLOCAL
REM Usage: run.bat <command> [files...]   e.g.  run.bat build   /   run.bat full   /   run.bat results
REM First run creates a virtual environment in .\venv and installs requirements.
cd /d "%~dp0"

IF NOT EXIST venv\Scripts\python.exe (
    ECHO Creating Python virtual environment in 'venv'...
    py -m venv venv
    CALL venv\Scripts\activate.bat
    pip install -r requirements.txt
) ELSE (
    CALL venv\Scripts\activate.bat
)

python run.py %*
ENDLOCAL
