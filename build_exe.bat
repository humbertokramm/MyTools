@echo off
:: Gera radiada_plot.exe usando PyInstaller
:: Requer: pip install pyinstaller
::
:: O .exe resultante fica em dist\radiada_plot.exe
:: Pode ser copiado para qualquer maquina sem Python instalado.

set PY=C:\Users\humberto.kramm\AppData\Local\Programs\Python\Python314\python.exe

%PY% -m PyInstaller ^
    --onefile ^
    --name radiada_plot ^
    --console ^
    radiada_plot.py

echo.
echo Pronto: dist\radiada_plot.exe
pause
