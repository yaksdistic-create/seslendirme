@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM ============================================================
REM  Video Birlestirme ve Seslendirme Studyosu - Baslatici
REM  - venv yoksa veya eksikse Python 3.11 ile olusturur + kurar
REM  - kurulum tamamsa dogrudan uygulamayi acar
REM
REM  NOT: Ses klonlama (Coqui TTS + torch) yalnizca Python 3.9-3.11
REM       ile calisir. Python 3.12+ (ornegin 3.14) ile kurulamaz.
REM ============================================================

set "VENV_DIR=venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "MARKER=%VENV_DIR%\.install_complete"

REM Hizli yol: venv ve kurulum tamamsa dogrudan calistir
if exist "%VENV_PY%" if exist "%MARKER%" goto run

echo ============================================================
echo  Kurulum gerekiyor. Uygun Python (3.9-3.11) araniyor...
echo ============================================================

REM Coqui TTS yalnizca 3.9-3.11 destekler; once 3.11, sonra 3.10, 3.9
set "PYLAUNCH="
py -3.11 --version >nul 2>nul && set "PYLAUNCH=py -3.11"
if not defined PYLAUNCH (
    py -3.10 --version >nul 2>nul && set "PYLAUNCH=py -3.10"
)
if not defined PYLAUNCH (
    py -3.9 --version >nul 2>nul && set "PYLAUNCH=py -3.9"
)

if not defined PYLAUNCH (
    echo.
    echo [HATA] Uygun Python bulunamadi ^(3.9 - 3.11 gerekli^).
    echo.
    echo  Ses klonlama paketleri ^(Coqui TTS, torch^) yalnizca
    echo  Python 3.9 - 3.11 ile kurulabilir. Mevcut Python 3.14 desteklenmiyor.
    echo.
    echo  Lutfen Python 3.11'i kurun ^(kurulumda "Add python.exe to PATH" secili olsun^):
    echo  https://www.python.org/downloads/release/python-3119/
    echo.
    echo  Kurulumdan sonra bu dosyayi tekrar calistirin.
    pause
    exit /b 1
)

echo Kullanilacak Python:
%PYLAUNCH% --version

REM Eksik / yanlis surumle olusturulmus eski venv'i temizle
if exist "%VENV_DIR%" (
    echo --- Mevcut eksik sanal ortam temizleniyor ---
    rmdir /s /q "%VENV_DIR%"
)

echo --- Sanal ortam olusturuluyor ---
%PYLAUNCH% -m venv "%VENV_DIR%"
if not exist "%VENV_PY%" (
    echo [HATA] Sanal ortam olusturulamadi.
    pause
    exit /b 1
)

echo --- pip guncelleniyor ---
"%VENV_PY%" -m pip install --upgrade pip

echo --- Bagimliliklar kuruluyor (requirements.txt) ---
echo  (torch ve Coqui TTS buyuk oldugu icin ilk kurulum uzun surebilir)
"%VENV_PY%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [HATA] Bagimliliklar kurulamadi. Yukaridaki mesajlari kontrol edin.
    pause
    exit /b 1
)

REM Kurulumu "tamamlandi" olarak isaretle
type nul > "%MARKER%"
echo.
echo --- Kurulum tamamlandi! ---
echo.

:run
echo Uygulama aciliyor...
"%VENV_PY%" main.py
if errorlevel 1 (
    echo.
    echo [HATA] Uygulama beklenmedik sekilde kapandi. Detaylar yukarida olabilir.
    pause
)
