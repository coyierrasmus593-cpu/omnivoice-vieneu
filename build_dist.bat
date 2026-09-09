@echo off
echo ==================================================
echo Bat dau qua trinh dong goi (Build) 89Media TTS Pro
echo ==================================================

:: Kiem tra thu muc venv
if not exist "venv\Scripts\python.exe" (
    echo [LOI] Khong tim thay moi truong venv! Vui long tao venv va cai dat thu vien truoc.
    pause
    exit /b 1
)

:: Chay script build_omnivoice.py
call .\venv\Scripts\python.exe build_omnivoice.py

echo.
echo ==================================================
echo Qua trinh dong goi da hoan tat.
echo Kiem tra thu muc "dist" de lay file exe thanh pham.
echo ==================================================
pause
