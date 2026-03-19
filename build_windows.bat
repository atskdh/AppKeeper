@echo off
setlocal
chcp 65001 > nul

echo ==========================================
echo AppKeeper - Windows Build Script
echo ==========================================

echo [1/3] Installing required libraries...
python -m pip install --quiet customtkinter psutil pystray pillow pyinstaller

echo [2/3] Generating icon data...
if exist "assets/gen_icon_data.py" (
    python "assets/gen_icon_data.py"
)

echo [3/3] Building executable using AppKeeper.spec...
python -m PyInstaller --clean --noconfirm "AppKeeper.spec"

echo.
if exist "dist\AppKeeper.exe" (
    echo --- Build Succeeded ---
    echo Output: dist\AppKeeper.exe
) else (
    echo --- Build Failed ---
    echo Please check the error messages above.
)

pause
