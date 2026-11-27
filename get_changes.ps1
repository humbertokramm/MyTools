<#
    .SYNOPSIS
        Baixa changes do Gerrit e os aplica numa branch de teste.

    .DESCRIPTION
        Alinha o repositorio com origin/develop (descartando qualquer alteracao
        local), baixa cada change informado e aplica um por um com cherry-pick.
        Chamado pelo makelua.bat; tambem pode ser usado direto.

    .EXAMPLE
        .\get_changes.ps1 -Repo C:\Projetos\platf-scripts-lua
        .\get_changes.ps1 -Repo C:\Projetos\platf-scripts-lua -Changes 189292
        .\get_changes.ps1 -Repo C:\Projetos\platf-scripts-lua -Changes 187463,188076/3
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]  [string]   $Repo,
                                    [string[]] $Changes = @(),
                                    [string]   $Branch
)

$ErrorActionPreference = 'Stop'

# Sem change: fica no develop limpo. Com change: usa uma branch de teste, para
# nao deixar commits de change em cima do develop
if (-not $Branch) {
    if ($Changes.Count -gt 0) { $Branch = 'teste-changes' } else { $Branch = 'develop' }
}

# Roda um comando git e guarda o codigo de saida em $script:GitRc.
# Por padrao aborta o script se o comando falhar; com -AllowFail apenas
# registra o codigo para o chamador decidir.
# A saida vai direto para o console (Out-Host) e nao para o pipeline, senao
# ela se misturaria ao valor de retorno da funcao.
function Invoke-Git {
    param([string[]] $GitArgs, [switch] $AllowFail)

    & git @GitArgs | Out-Host
    $script:GitRc = $LASTEXITCODE
    if ($script:GitRc -ne 0 -and -not $AllowFail) {
        throw ('git ' + ($GitArgs -join ' ') + " falhou (codigo $script:GitRc)")
    }
}

try {
    if (-not (Test-Path -LiteralPath $Repo)) { throw "repositorio nao encontrado: $Repo" }
    Set-Location -LiteralPath $Repo

    # As flags skip-worktree/assume-unchanged impedem o reset --hard de rodar.
    # O lfs_tar.txt e gerado pelo lua_tar_gen.py e costuma estar travado assim.
    foreach ($line in (& git ls-files -v)) {
        if ($line -cmatch '^[a-zS] ') {
            $f = $line.Substring(2)
            Write-Host "Liberando arquivo travado no indice: $f"
            & git update-index --no-skip-worktree    -- $f 2>$null
            & git update-index --no-assume-unchanged -- $f 2>$null
        }
    }

    Write-Host ''
    Write-Host ("Alinhando {0} com origin/develop..." -f $Branch) -ForegroundColor Cyan
    Invoke-Git @('fetch', '--quiet', 'origin', 'develop')
    # Limpa a worktree primeiro: com arquivo sujo o checkout abaixo falharia e
    # a branch atual e que acabaria apontando para o origin/develop
    Invoke-Git @('reset', '--hard', '--quiet', 'HEAD')
    Invoke-Git @('clean', '-fdq')
    Invoke-Git @('checkout', '-q', '-B', $Branch, 'origin/develop')

    if ($Changes.Count -eq 0) {
        Write-Host ''
        Write-Host ('Branch {0} em {1}:' -f $Branch, (& git rev-parse --short HEAD)) -ForegroundColor Green
        & git log --oneline -1
        exit 0
    }

    # Resolve cada "NNNNNN" ou "NNNNNN/P" para o ref refs/changes/<shard>/<num>/<ps>
    $alvos = @()
    foreach ($c in $Changes) {
        $num, $ps = $c -split '/', 2

        $shard = $num.PadLeft(2, '0')
        $shard = $shard.Substring($shard.Length - 2)

        if (-not $ps) {
            $remoto = & git ls-remote origin "refs/changes/$shard/$num/*"
            if ($LASTEXITCODE -ne 0) { throw "git ls-remote falhou para o change $num" }

            $todos = $remoto | ForEach-Object {
                if ($_ -match "refs/changes/$shard/$num/(\d+)$") { [int]$Matches[1] }
            }
            if (-not $todos) { throw "change $num nao encontrado no Gerrit" }

            $ps = ($todos | Measure-Object -Maximum).Maximum
        }

        $alvos += [pscustomobject]@{
            Change   = $num
            Patchset = $ps
            Local    = "change-$num"
            Ref      = "refs/changes/$shard/$num/$ps"
        }
    }

    Write-Host ''
    foreach ($a in $alvos) {
        Write-Host ('Baixando change {0} patchset {1}...' -f $a.Change, $a.Patchset) -ForegroundColor Cyan
        Invoke-Git @('fetch', '--quiet', '--force', 'origin', ('{0}:{1}' -f $a.Ref, $a.Local))

        $assunto = & git log -1 --format=%s $a.Local
        $autor   = & git log -1 --format=%an $a.Local
        Write-Host ('   {0}  ({1})' -f $assunto, $autor)
    }

    Write-Host ''
    foreach ($a in $alvos) {
        Write-Host ('Aplicando change {0}...' -f $a.Change) -ForegroundColor Cyan
        Invoke-Git @('cherry-pick', $a.Local) -AllowFail
        if ($script:GitRc -ne 0) {
            # Desfaz so o cherry-pick que parou no meio; os anteriores ficam
            if (Test-Path -LiteralPath (Join-Path $Repo '.git\CHERRY_PICK_HEAD')) {
                & git cherry-pick --abort | Out-Host
            }
            throw ('conflito ao aplicar o change {0} patchset {1}. Os changes anteriores da lista continuam aplicados na branch {2}' -f $a.Change, $a.Patchset, $Branch)
        }
    }

    Write-Host ''
    Write-Host ('Branch {0} pronta (sobre origin/develop {1}):' -f $Branch, (& git rev-parse --short origin/develop)) -ForegroundColor Green
    & git log --oneline origin/develop..HEAD
    exit 0
}
catch {
    Write-Host ''
    Write-Host ('ERRO: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
