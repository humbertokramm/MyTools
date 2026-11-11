@echo off
:: Gera o EmissaoGUI.exe (emissao_gui.py) com PyInstaller.
::
:: O PC do N9010A roda Windows 7, e o exe carrega junto o Python que o gerou:
:: por isso o build usa o Python 3.8, o ultimo que roda no Windows 7.
::   build_emissao_exe.bat        -> dist\EmissaoGUI_win7_64.exe
:: O exe precisa da mesma arquitetura do VISA instalado no PC do analisador;
:: num Windows de 64 bits normalmente servem os dois.
::
:: Pacotes do 3.8: numpy 1.24.4, matplotlib 3.7.5, pyvisa 1.13.0,
:: pyinstaller 5.13.2.
setlocal
cd /d "%~dp0"

:: So 64 bits por padrao: o antivirus daqui bloqueia o exe de 32 bits do
:: PyInstaller. Para tentar o de 32:  build_emissao_exe.bat 32
set "ARQS=%*"
if "%ARQS%"=="" set "ARQS=64"
for %%A in (%ARQS%) do call :build %%A
echo.
dir /b dist\EmissaoGUI_win7_*.exe
pause
exit /b

:build
set "PY=%LOCALAPPDATA%\Programs\Python\Python38-%1\python.exe"
if "%1"=="64" if not exist "%PY%" set "PY=%LOCALAPPDATA%\Programs\Python\Python38\python.exe"
if not exist "%PY%" (
    echo Python 3.8 de %1 bits nao encontrado; pulando.
    exit /b
)
echo === EmissaoGUI_win7_%1.exe
:: o .spec troca o MSVCP140.dll pelo compativel com o Windows 7 e confere
:: os binarios; ver os comentarios nele
"%PY%" -m PyInstaller --noconfirm --workpath build\emissao_%1 emissao_gui_win7.spec
exit /b
