@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM ============================================================
REM  Bagimliliklari Guncelle / Onar
REM  Mevcut sanal ortami (venv) silmeden requirements.txt'i uygular.
REM  (Ornegin transformers surumunu duzeltmek icin)
REM ============================================================

set "VENV_PY=venv\Scripts\python.exe"

if not exist "%VENV_PY%" (
    echo [HATA] Sanal ortam bulunamadi.
    echo  Once Baslat.bat ile kurulumu tamamlayin.
    pause
    exit /b 1
)

echo Bagimliliklar guncelleniyor (requirements.txt)...
echo  (Model zaten indirildi; bu adim yalnizca paketleri duzeltir)
"%VENV_PY%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [HATA] Guncelleme basarisiz. Yukaridaki mesajlari kontrol edin.
    pause
    exit /b 1
)

echo.
echo --- Guncelleme tamamlandi! Artik Baslat.bat ile uygulamayi acabilirsiniz. ---
pause
