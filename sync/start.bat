@echo off
cd /d "%~dp0"
where pythonw >nul 2>&1 && start "" pythonw "%~dp0sync.py" || start "" python "%~dp0sync.py"
