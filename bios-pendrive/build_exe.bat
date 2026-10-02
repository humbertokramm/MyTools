@echo off
:: Gera dist\BiosPendrive.exe (arquivo unico, sem precisar de Python na maquina).
:: Requer: pip install -r requirements.txt
cd /d "%~dp0"
set PY=C:\Users\humberto.kramm\AppData\Local\Programs\Python\Python314\python.exe

%PY% -m PyInstaller ^
    --onefile ^
    --windowed ^
    --noconfirm ^
    --name BiosPendrive ^
    bios_pendrive.py

echo.
echo Pronto: dist\BiosPendrive.exe
pause
