# Remove-GFE-Prefix.ps1
# Renomeia PDFs removendo prefixos do tipo "GFE - ", "GFE_", "GFE –", etc.
# Gera um log CSV com os renomes aplicados.

[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Low')]
param(
    [Parameter(Position=0)]
    [ValidateScript({ Test-Path $_ })]
    [string]$Path = "C:\TDN TOTVS\PDFs CONTROLADORIA 3",

    # Procura também em subpastas
    [switch]$Recurse
)

$pattern = '^(?:\s*GFE\s*[-_–—]?\s*)+'   # início de nome com GFE + hífen/underscore/dash + espaços
$renamed = @()
$skipped = 0
$errors  = 0

try {
    $files = Get-ChildItem -LiteralPath $Path -File -Filter *.pdf -Recurse:$Recurse -ErrorAction Stop
} catch {
    Write-Error "Não foi possível listar arquivos em '$Path': $($_.Exception.Message)"
    exit 1
}

foreach ($f in $files) {
    # remove prefixo "GFE ..." no começo do nome (case-insensitive)
    $newName = $f.Name -ireplace $pattern, ''

    if ($newName -eq $f.Name -or [string]::IsNullOrWhiteSpace($newName)) {
        $skipped++
        continue
    }

    $target = Join-Path -Path $f.DirectoryName -ChildPath $newName
    if (Test-Path -LiteralPath $target) {
        Write-Warning "Pulado (já existe): $newName"
        $skipped++
        continue
    }

    try {
        if ($PSCmdlet.ShouldProcess($f.FullName, "Renomear para '$newName'")) {
            Rename-Item -LiteralPath $f.FullName -NewName $newName -ErrorAction Stop
            $renamed += [pscustomobject]@{
                Old  = $f.Name
                New  = $newName
                When = (Get-Date)
            }
            Write-Host "Renomeado: $($f.Name) -> $newName"
        }
    } catch {
        Write-Warning "Erro ao renomear '$($f.Name)': $($_.Exception.Message)"
        $errors++
    }
}

# Se foi simulação (-WhatIf), não grava log
if (-not $WhatIfPreference) {
    $total = $renamed.Count
    Write-Host "`nTotal renomeados: $total | Pulados: $skipped | Erros: $errors"
    if ($total -gt 0) {
        $log = Join-Path -Path $Path -ChildPath ("_rename_gfe_log_{0}.csv" -f (Get-Date -Format 'yyyyMMdd_HHmmss'))
        $renamed | Export-Csv -NoTypeInformation -Encoding UTF8 -LiteralPath $log
        Write-Host "Log salvo em: $log"
    }
} else {
    Write-Host "`nSimulação concluída. Pulados: $skipped | Erros: $errors"
    Write-Host "Para aplicar de verdade, remova o parâmetro -WhatIf."
}
