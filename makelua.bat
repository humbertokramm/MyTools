@echo off
chcp 65001 >nul
title Build Lua

echo =========================================
echo           BUILD LUA - DATACOM
echo =========================================
echo.

:: Pergunta se limpa ou mantém alterações
echo Deseja limpar as alterações locais e atualizar o repositório?
echo [1] Sim - descartar TUDO e ficar identico ao servidor
echo [2] Não - manter minhas alterações e seguir para compilar
echo.
set /p OPCAO_GIT="Escolha (1 ou 2): "

if "%OPCAO_GIT%"=="1" (
    echo.
    echo Descartando alteracoes locais e alinhando com o servidor...
    cd /d C:\Projetos\platf-scripts-lua
    git checkout develop
    git fetch origin
    rem Remove flags skip-worktree/assume-unchanged que impedem o reset
    powershell -NoProfile -Command "git ls-files -v | Where-Object { $_ -cmatch '^[a-zS] ' } | ForEach-Object { $f = $_.Substring(2); Write-Host ('Liberando arquivo travado no indice: ' + $f); git update-index --no-skip-worktree -- $f; git update-index --no-assume-unchanged -- $f }"
    git reset --hard origin/develop
    git clean -fd
    echo.
    echo Repositório atualizado!
    git log --oneline -1
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
echo Gerando luaversion.txt...
echo.

if not exist C:\Projetos\platf-scripts-lua\release_info mkdir C:\Projetos\platf-scripts-lua\release_info

powershell -NoProfile -Command ^
    "Set-Location 'C:\Projetos\platf-scripts-lua';" ^
    "$log   = git log -n1 --pretty | Select-Object -First 5;" ^
    "$dirty = git status --short;" ^
    "if ($dirty) { $out = $log + @('', '=== Modificados nao commitados ===') + $dirty + @('===================') } else { $out = $log };" ^
    "$utf8  = [System.Text.UTF8Encoding]::new($false);" ^
    "[System.IO.File]::WriteAllLines('C:\Projetos\platf-scripts-lua\release_info\luaversion.txt', $out, $utf8);" ^
    "Write-Host 'luaversion.txt gerado.'"

echo.
echo Rodando o script e compilando "%PROJETO%"...
echo.

::ssh humberto.kramm@172.26.27.37 "bash -l -c 'lua ~/makelua.lua %PROJETO%'"

python C:\Projetos\platf-scripts-lua\util\other\lua_tar_gen.py -p %PROJETO%
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
    set "MOTIVO=o lua_tar_gen.py terminou com erro %RC%"
    goto :falhou
)

echo.
echo Organizando arquivos gerados...

cd /d C:\Projetos\platf-scripts-lua

:: Deleta arquivos desnecessários
del /f /q lua_tar.txt 2>nul
del /f /q lua.tar.gz 2>nul

:: Move lua.tar.gz para pasta TFTP substituindo
move /y lua_%PROJETO%_*.tar.gz C:\Testes\TFTP\lua_%PROJETO%.tar.gz >nul

:: Confere o pacote no destino: o lua_tar_gen.py pode sair com 0 sem gerar
:: nada, e ai o move falha em silencio -- sem esta checagem o OK sairia
:: verde com o tar.gz antigo (ou nenhum) na pasta TFTP.
if not exist C:\Testes\TFTP\lua_%PROJETO%.tar.gz (
    set "MOTIVO=o pacote lua_%PROJETO%.tar.gz nao chegou em C:\Testes\TFTP"
    goto :falhou
)

echo Arquivos organizados!

echo.
echo -----------------------------------------
echo Lua Version
type C:\Projetos\platf-scripts-lua\release_info\luaversion.txt
echo -----------------------------------------
echo.

powershell -NoProfile -Command ^
    "$p = 'C:\Testes\TFTP\lua_%PROJETO%.tar.gz';" ^
    "$f = Get-Item $p -ErrorAction SilentlyContinue;" ^
    "$tam = if ($f) { '{0:N1} KB' -f ($f.Length/1KB) } else { 'tamanho indisponivel' };" ^
    "Write-Host '=========================================' -ForegroundColor Green;" ^
    "Write-Host ('  OK - lua_%PROJETO%.tar.gz  (' + $tam + ')') -ForegroundColor Green;" ^
    "Write-Host '=========================================' -ForegroundColor Green"
pause
exit /b 0

:falhou
echo.
powershell -NoProfile -Command ^
    "Write-Host '=========================================' -ForegroundColor Red;" ^
    "Write-Host '  FAIL - %PROJETO% nao foi compilado' -ForegroundColor Red;" ^
    "Write-Host '  %MOTIVO%' -ForegroundColor Red;" ^
    "Write-Host '=========================================' -ForegroundColor Red"
pause
exit /b 1