@echo off
setlocal
cd /d "%~dp0"
py -m pip install --upgrade pip
py -m pip install -r requirements.txt
py -m pip install pyinstaller
py -m PyInstaller --noconfirm --clean --onefile --windowed --name PCAppLockerV3 --collect-all customtkinter --hidden-import=pystray app_locker_v3.py
echo.
echo Build complete: dist\PCAppLockerV3.exe
pause
