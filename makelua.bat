@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title Build Lua

rem %~dp0 tem de ser lido ANTES do parse: o "shift" desloca %0 junto com os
rem demais argumentos, e depois dele %~dp0 passa a resolver no diretorio atual
set "MYDIR=%~dp0"

set "REPO=C:\Projetos\platf-scripts-lua"
set "TFTP=C:\Testes\TFTP"
set "CHANGES="
set "PROJETO="

rem ---------------------------------------------------------------------
rem Argumentos (em qualquer ordem, todos opcionais):
rem   NNNNNN     numero de change do Gerrit (ultimo patchset)
rem   NNNNNN/P   numero de change travado no patchset P
rem   pdXXXX     projeto a compilar
rem Exemplos:  makelua 189292
rem            makelua 189292 pd4302
rem            makelua 187463 188076/3 188509 pd4302
rem ---------------------------------------------------------------------
:parse_args
if "%~1"=="" goto args_prontos
if "%~1"=="/?" goto ajuda
if /i "%~1"=="-h" goto ajuda
echo.%~1| findstr /r /c:"^[0-9][0-9]*$" /c:"^[0-9][0-9]*/[0-9][0-9]*$" >nul
if not errorlevel 1 (
    set "CHANGES=!CHANGES! %~1"
) else (
    set "PROJETO=%~1"
)
shift
goto parse_args
:args_prontos

echo =========================================
echo           BUILD LUA - DATACOM
echo =========================================
echo.

if defined CHANGES goto baixa_changes

:: Sem change na linha de comando: pergunta o que fazer com o repositorio
echo Deseja limpar as alterações locais e atualizar o repositório?
echo [1] Sim - descartar TUDO e ficar identico ao servidor
echo [2] Não - manter minhas alterações e seguir para compilar
echo.
set /p OPCAO_GIT="Escolha (1 ou 2): "

if "%OPCAO_GIT%"=="1" (
    echo.
    echo Descartando alteracoes locais e alinhando com o servidor...
    call :roda_git
    if errorlevel 1 (
        set "MOTIVO=falha ao alinhar o repositório com o origin/develop"
        goto :falhou
    )
) else if "%OPCAO_GIT%"=="2" (
    echo.
    echo Mantendo alterações locais...
) else (
    echo Opção inválida. Encerrando.
    pause
    exit /b 1
)
goto pede_projeto

:: Com change(s) na linha de comando: alinha com o develop e aplica os changes
:baixa_changes
echo Changes solicitados:!CHANGES!
call :roda_git !CHANGES!
if errorlevel 1 (
    set "MOTIVO=falha ao preparar os changes do Gerrit"
    goto :falhou
)

:pede_projeto
echo.
if defined PROJETO goto tem_projeto

:: Pergunta o projeto
echo Informe o nome do projeto para compilar:
echo Exemplo: pd4202  (letras minúsculas, com o prefixo "pd")
echo.
set /p PROJETO="Projeto: "

if "%PROJETO%"=="" (
    echo Nenhum projeto informado. Encerrando.
    pause
    exit /b 1
)
:tem_projeto

echo.
echo Gerando luaversion.txt...
echo.

if not exist %REPO%\release_info mkdir %REPO%\release_info

powershell -NoProfile -Command ^
    "Set-Location '%REPO%';" ^
    "$log   = git log -n1 --pretty | Select-Object -First 5;" ^
    "$dirty = git status --short;" ^
    "if ($dirty) { $out = $log + @('', '=== Modificados nao commitados ===') + $dirty + @('===================') } else { $out = $log };" ^
    "$utf8  = [System.Text.UTF8Encoding]::new($false);" ^
    "[System.IO.File]::WriteAllLines('%REPO%\release_info\luaversion.txt', $out, $utf8);" ^
    "Write-Host 'luaversion.txt gerado.'"

echo.
echo Rodando o script e compilando "%PROJETO%"...
echo.

::ssh humberto.kramm@172.26.27.37 "bash -l -c 'lua ~/makelua.lua %PROJETO%'"

python %REPO%\util\other\lua_tar_gen.py -p %PROJETO%
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
    set "MOTIVO=o lua_tar_gen.py terminou com erro %RC%"
    goto :falhou
)

echo.
echo Organizando arquivos gerados...

cd /d %REPO%

:: Deleta arquivos desnecessários
del /f /q lua_tar.txt 2>nul
del /f /q lua.tar.gz 2>nul

:: Move lua.tar.gz para pasta TFTP substituindo
move /y lua_%PROJETO%_*.tar.gz %TFTP%\lua_%PROJETO%.tar.gz >nul

:: Confere o pacote no destino: o lua_tar_gen.py pode sair com 0 sem gerar
:: nada, e ai o move falha em silencio -- sem esta checagem o OK sairia
:: verde com o tar.gz antigo (ou nenhum) na pasta TFTP.
if not exist %TFTP%\lua_%PROJETO%.tar.gz (
    set "MOTIVO=o pacote lua_%PROJETO%.tar.gz nao chegou em %TFTP%"
    goto :falhou
)

echo Arquivos organizados!

echo.
echo -----------------------------------------
echo Lua Version
type %REPO%\release_info\luaversion.txt
echo -----------------------------------------
echo.

powershell -NoProfile -Command ^
    "$p = '%TFTP%\lua_%PROJETO%.tar.gz';" ^
    "$f = Get-Item $p -ErrorAction SilentlyContinue;" ^
    "$tam = if ($f) { '{0:N1} KB' -f ($f.Length/1KB) } else { 'tamanho indisponivel' };" ^
    "Write-Host '=========================================' -ForegroundColor Green;" ^
    "Write-Host ('  OK - lua_%PROJETO%.tar.gz  (' + $tam + ')') -ForegroundColor Green;" ^
    "Write-Host '=========================================' -ForegroundColor Green"
pause
exit /b 0

:: Chama o get_changes.ps1. Sem argumento alinha o develop; com argumento(s)
:: monta a branch teste-changes com os changes informados.
:roda_git
if not exist "%MYDIR%get_changes.ps1" (
    echo get_changes.ps1 nao encontrado em %MYDIR%
    exit /b 1
)
if "%~1"=="" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%MYDIR%get_changes.ps1" -Repo "%REPO%"
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%MYDIR%get_changes.ps1" -Repo "%REPO%" -Changes %*
)
exit /b %ERRORLEVEL%

:ajuda
echo Uso: makelua [change ...] [projeto]
echo.
echo   change    numero do change no Gerrit, opcionalmente com o patchset:
echo             189292      ultimo patchset
echo             188076/3    patchset 3
echo   projeto   nome do projeto, com o prefixo "pd" (ex.: pd4302)
echo.
echo Com change(s): descarta as alteracoes locais, alinha com origin/develop
echo e aplica os changes na branch teste-changes, na ordem informada.
echo Sem change: pergunta se deve limpar o repositorio, como antes.
echo.
echo Exemplos:
echo   makelua
echo   makelua 189292
echo   makelua 189292 pd4302
echo   makelua 187463 188076/3 188509 pd4302
exit /b 0

:falhou
if not defined PROJETO set "PROJETO=o pacote"
echo.
powershell -NoProfile -Command ^
    "Write-Host '=========================================' -ForegroundColor Red;" ^
    "Write-Host '  FAIL - %PROJETO% nao foi compilado' -ForegroundColor Red;" ^
    "Write-Host '  %MOTIVO%' -ForegroundColor Red;" ^
    "Write-Host '=========================================' -ForegroundColor Red"
pause
exit /b 1
