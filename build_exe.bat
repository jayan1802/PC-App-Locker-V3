@echo off
setlocal
cd /d "%~dp0"
py -m pip install --upgrade pip
py -m pip install -r requirements.txt
py -m PyInstaller --noconfirm --clean --windowed --onefile --name PCAppLockerV4_2_TEST app_locker_v4.py
echo.
echo Build complete. EXE: dist\PCAppLockerV4_2_TEST.exe
pause
