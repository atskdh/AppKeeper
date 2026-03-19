@echo off
REM ==========================================
REM AppKeeper - Windows Build Script
REM Requires Python 3.10 or later
REM ==========================================

echo [AppKeeper] Installing required libraries...
python -m pip install customtkinter psutil pystray pillow pyinstaller

echo.
echo [AppKeeper] Generating embedded icon data...
:: assets フォルダ内の gen_icon_data.py を実行
python assets/gen_icon_data.py
if errorlevel 1 (
    echo [AppKeeper] WARNING: icon_data.py generation failed. Icons may not display correctly.
)

echo.
echo [AppKeeper] Building exe using AppKeeper.spec...
:: AppKeeper.spec を使用してビルド
python -m PyInstaller --clean AppKeeper.spec

echo.
if exist dist\AppKeeper.exe (
    echo [AppKeeper] Build succeeded!
    echo [AppKeeper] AppKeeper.exe contains all icons - no extra files needed.
    echo [AppKeeper] Output: dist\AppKeeper.exe
) else (
    echo [AppKeeper] Build failed. Please check the error messages above.
)
pause
