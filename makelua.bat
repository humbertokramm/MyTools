@echo off
chcp 65001 >nul
title Build Lua

echo =========================================
echo           BUILD LUA - DATACOM
echo =========================================
echo.

:: Pergunta se limpa ou mantém alterações
echo Deseja limpar as alterações locais e atualizar o repositório?
echo [1] Sim - limpar tudo e fazer pull (git reset --hard + pull)
echo [2] Não - manter minhas alterações e seguir para compilar
echo.
set /p OPCAO_GIT="Escolha (1 ou 2): "

if "%OPCAO_GIT%"=="1" (
    echo.
    echo Limpando alterações e atualizando repositório...
    cd /d C:\Projetos\platf-scripts-lua
    git checkout develop
    git reset --hard
    git pull
    echo.
    echo Repositório atualizado!
) else if "%OPCAO_GIT%"=="2" (
    echo.
    echo Mantendo alterações locais...
) else (
    echo Opção inválida. Encerrando.
    pause
    exit /b 1
)

echo.
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

echo.
echo Rodando o script e compilando "%PROJETO%"...
echo.

::ssh humberto.kramm@172.26.27.37 "bash -l -c 'lua ~/makelua.lua %PROJETO%'"

python C:\Projetos\platf-scripts-lua\.claude\scripts\lua_tar_gen.py -p %PROJETO%

echo.
echo Organizando arquivos gerados...

cd /d C:\Projetos\platf-scripts-lua

:: Deleta arquivos desnecessários
del /f /q lua_tar.txt
del /f /q lua.tar.gz

:: Move lua.tar.gz para pasta TFTP substituindo
move /y lua_%PROJETO%_*.tar.gz C:\Testes\TFTP\lua_%PROJETO%.tar.gz

echo Arquivos organizados!


echo.
echo =========================================
echo Processo finalizado!
echo =========================================
pause