@echo off
chcp 65001 >nul
title Radiada Plot - Todas as pastas

:: Abre o radiada_plot.exe para cada pasta polarizacao\tensao de uma data.
:: Uso:
::   radiada_plot_all.bat "C:\...\Medidas\Radiada\2026-07-07"
::   (ou arraste a pasta da data sobre este .bat, ou rode e informe o caminho)

set "ROOT=%~1"
if "%ROOT%"=="" set /p ROOT="Pasta da data (ex: C:\Testes\VHW\LIEM\Fusco\Medidas\Radiada\2026-07-07): "

if not exist "%ROOT%" (
    echo Pasta nao encontrada: %ROOT%
    pause
    exit /b 1
)

set "EXE=%~dp0\radiada_plot.exe"
if not exist "%EXE%" (
    echo Executavel nao encontrado: %EXE%
    echo Rode o build_exe.bat primeiro.
    pause
    exit /b 1
)

set /a COUNT=0
for /d %%P in ("%ROOT%\*") do (
    for /d %%T in ("%%P\*") do (
        if /i not "%%~nxT"=="full_band" (
            echo Abrindo: %%T
            start "radiada_plot" /min "%EXE%" "%%T"
            set /a COUNT+=1
        )
    )
)

echo.
echo %COUNT% janelas lancadas.
timeout /t 5 >nul
