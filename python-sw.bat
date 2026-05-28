@echo off
setlocal enabledelayedexpansion
title Python Version Switcher

echo.
echo  ==========================================
echo    Python Version Switcher
echo  ==========================================
echo.

set count=0

rem --- Busca em C:\PythonXX ---
for /d %%D in (C:\Python*) do (
    if exist "%%D\python.exe" (
        set /a count+=1
        for /f "tokens=*" %%V in ('"%%D\python.exe" --version 2^>^&1') do set "pyver[!count!]=%%V"
        set "pypath[!count!]=%%D"
    )
)

rem --- Busca em %LOCALAPPDATA%\Programs\Python\PythonXX ---
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python*") do (
    if exist "%%D\python.exe" (
        set /a count+=1
        for /f "tokens=*" %%V in ('"%%D\python.exe" --version 2^>^&1') do set "pyver[!count!]=%%V"
        set "pypath[!count!]=%%D"
    )
)

if %count%==0 (
    echo  Nenhuma instalacao do Python encontrada.
    echo.
    pause
    exit /b 1
)

rem --- Mostra versoes encontradas ---
echo  Versoes instaladas:
echo.
for /l %%i in (1,1,%count%) do (
    echo    [%%i] !pyver[%%i]!
    echo        !pypath[%%i]!
    echo.
)

rem --- Pergunta qual versao ---
:ask_choice
set "choice="
set /p "choice= Escolha o numero da versao (1-%count%): "
if "!choice!"=="" goto ask_choice
set /a valid=!choice! 2>nul
if !valid! lss 1 goto choice_invalid
if !valid! gtr %count% goto choice_invalid

set "sel_path=!pypath[%valid%]!"
set "sel_ver=!pyver[%valid%]!"

echo.
echo  Versao selecionada : !sel_ver!
echo  Caminho            : !sel_path!
echo.
echo    [1] Somente para esta sessao do CMD  (temporario)
echo    [2] Permanente - atualiza PATH do usuario
echo.

:ask_mode
set "mode="
set /p "mode= Escolha [1 ou 2]: "
if "!mode!"=="1" goto session_only
if "!mode!"=="2" goto permanent
goto ask_mode

rem -------------------------------------------------------
:session_only
rem Monta o novo PATH com a versao escolhida na frente
set "new_path=!sel_path!;!sel_path!\Scripts;%PATH%"
rem
rem TRUQUE: endlocal encerra o escopo local, mas %new_path% ja foi
rem         expandido antes da execucao — entao o valor e preservado
rem         e atribuido ao CMD pai com o segundo comando apos o &
rem
endlocal & set "PATH=%new_path%"
echo.
echo  Pronto! Versao ativa nesta sessao:
python --version
echo.
echo  (Configuracao temporaria - se perde ao fechar o CMD)
echo  (Associacao de arquivo .py nao e alterada no modo temporario)
echo.
pause
exit /b 0

rem -------------------------------------------------------
:permanent
echo.

rem --- Passo 1: Atualiza PATH do usuario no registro ---
set "ps_tmp=%TEMP%\pyswitcher_%RANDOM%.ps1"
> "!ps_tmp!" echo $newPython = "!sel_path!"
>> "!ps_tmp!" echo $newScripts = "!sel_path!\Scripts"
>> "!ps_tmp!" echo $curPath = [Environment]::GetEnvironmentVariable("PATH", "User")
>> "!ps_tmp!" echo $parts = ($curPath -split ";") ^| Where-Object { $_ -notmatch "\\Python[0-9]" -and $_ -notmatch "WindowsApps" -and $_ -ne "" }
>> "!ps_tmp!" echo $newPath = $newPython + ";" + $newScripts + ";" + ($parts -join ";")
>> "!ps_tmp!" echo [Environment]::SetEnvironmentVariable("PATH", $newPath, "User")
>> "!ps_tmp!" echo Write-Host "  [OK] PATH do usuario atualizado."
powershell -NoProfile -ExecutionPolicy Bypass -File "!ps_tmp!"
del "!ps_tmp!" 2>nul

rem --- Passo 2: AutoRun do CMD ---
rem    Executa automaticamente em todo novo terminal CMD.
rem    Garante prioridade mesmo que C:\PythonXX esteja no PATH do sistema.
rem    %%PATH%% vira %PATH% na string gravada — expandido pelo CMD ao abrir.
reg add "HKCU\Software\Microsoft\Command Processor" /v AutoRun /t REG_SZ /d "set PATH=!sel_path!;!sel_path!\Scripts;%%PATH%%" /f >nul
echo   [OK] AutoRun do CMD configurado.

rem --- Passo 3: Atualiza associacao de arquivo .py ---
rem    Grava em HKCU\Software\Classes, que tem prioridade sobre HKCR
rem    (onde o Python 3.4 registrou a associacao de sistema).
rem    Resultado: digitar "script.py" no CMD usa a versao escolhida.
rem
rem    %%1 vira %1 na string gravada (primeiro argumento = nome do arquivo)
rem    %%* vira %* (todos os argumentos extras passados ao script)
set "ps_assoc=%TEMP%\pyassoc_%RANDOM%.ps1"
>  "!ps_assoc!" echo $py = "!sel_path!\python.exe"
>> "!ps_assoc!" echo $q  = [char]34
>> "!ps_assoc!" echo $cmd = $q + $py + $q + " " + $q + "%%1" + $q + " %%*"
>> "!ps_assoc!" echo New-Item -Path "HKCU:\Software\Classes\Python.File\shell\open\command" -Force ^| Out-Null
>> "!ps_assoc!" echo Set-ItemProperty -Path "HKCU:\Software\Classes\Python.File\shell\open\command" -Name "(Default)" -Value $cmd
>> "!ps_assoc!" echo New-Item -Path "HKCU:\Software\Classes\.py" -Force ^| Out-Null
>> "!ps_assoc!" echo Set-ItemProperty -Path "HKCU:\Software\Classes\.py" -Name "(Default)" -Value "Python.File"
>> "!ps_assoc!" echo Write-Host "  [OK] Associacao .py atualizada."
>> "!ps_assoc!" echo Write-Host "       $cmd"
powershell -NoProfile -ExecutionPolicy Bypass -File "!ps_assoc!"
del "!ps_assoc!" 2>nul

rem --- Passo 4: Aplica na sessao atual ---
set "new_path=!sel_path!;!sel_path!\Scripts;%PATH%"
endlocal & set "PATH=%new_path%"
echo   [OK] Sessao atual atualizada.
echo.
echo  Versao ativa agora:
python --version
echo.
echo  Todo novo terminal CMD ja usara esta versao automaticamente.
echo  Arquivos .py serao executados diretamente com esta versao.
echo.
pause
exit /b 0

rem -------------------------------------------------------
:choice_invalid
echo  Opcao invalida! Digite um numero entre 1 e %count%.
goto ask_choice
