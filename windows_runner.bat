@echo off
setlocal

:: Change this to your folder path
set FOLDER_PATH=C:\path\to\your\folder
:: Change this to your script name
set SCRIPT_NAME=your_script.py

:: Check if folder exists
if not exist "%FOLDER_PATH%" (
    echo Error: Folder '%FOLDER_PATH%' does not exist
    pause
    exit /b 1
)

:: Check if .venv directory exists
if not exist "%FOLDER_PATH%\.venv" (
    echo Error: Virtual environment directory '.venv' not found in %FOLDER_PATH%
    pause
    exit /b 1
)

:: Check if Python script exists
if not exist "%FOLDER_PATH%\%SCRIPT_NAME%" (
    echo Error: Python script '%SCRIPT_NAME%' not found in %FOLDER_PATH%
    pause
    exit /b 1
)

:: Change to the specified directory
cd /d "%FOLDER_PATH%"

:: Activate virtual environment and run script
call .venv\Scripts\activate.bat
python "%SCRIPT_NAME%"
call .venv\Scripts\deactivate.bat

echo Script execution completed
pause
