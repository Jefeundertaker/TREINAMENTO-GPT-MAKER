# ====================== CONFIGURE AQUI ======================
$SrcDir    = "C:\TDN TOTVS"                           # tudo daqui vai para o GitHub
$LocalRepo = "C:\Projetos\TREINAMENTO-GPT-MAKER"      # pasta onde o repo foi clonado
$RemoteUrl = "https://github.com/Jefeundertaker/TREINAMENTO-GPT-MAKER.git"
$Branch    = "main"
$UserName  = "Jefeundertaker"
$UserEmail = "seu_email@exemplo.com"
$CommitMsg = "sync: espelha C:\TDN TOTVS no repositório (remove antigos e sem LFS)"
# ===========================================================

function Die($m){ Write-Host "❌ $m" -ForegroundColor Red; exit 1 }

# 0) Checagens
$git = Get-Command git -ErrorAction SilentlyContinue
if (-not $git) { Die "Git não encontrado. Instale o Git for Windows." }
if (-not (Test-Path $SrcDir))    { Die "Pasta de origem não encontrada: $SrcDir" }
if (-not (Test-Path $LocalRepo)) { New-Item -ItemType Directory -Path $LocalRepo | Out-Null }

# 1) Preparar repositório
Set-Location $LocalRepo
if (-not (Test-Path ".git")) {
  git init -b $Branch | Out-Null
}
$cur = (git rev-parse --abbrev-ref HEAD).Trim()
if ($cur -ne $Branch) { git checkout -B $Branch | Out-Null }

git config user.name  $UserName  | Out-Null
git config user.email $UserEmail | Out-Null

# remoto origin
$hasOrigin = (git remote 2>$null | Select-String -SimpleMatch "origin").Length -gt 0
if (-not $hasOrigin) { git remote add origin $RemoteUrl | Out-Null }

# 2) Espelhar conteúdo (sem tocar na .git)
Write-Host "→ Espelhando '$SrcDir' -> '$LocalRepo' ..."
# /MIR = mirror (inclui exclusões). Excluímos .git e a própria venv do repo, se houver.
robocopy "$SrcDir" "$LocalRepo" /MIR /R:2 /W:2 /XD "$LocalRepo\.git" "$LocalRepo\.venv" /XF ".git" ".gitattributes.lfsbackup" | Out-Null

# 3) Garantir que PDFs NÃO usem LFS
try { git lfs untrack "*.pdf" | Out-Null } catch {}
$ga = Join-Path $LocalRepo ".gitattributes"
if (Test-Path $ga) {
  $content = Get-Content $ga -Raw
  $lines = $content -split "`r?`n"
  $filtered = $lines | Where-Object { $_ -notmatch '\.pdf\b.*lfs' -and $_ -notmatch '\*\.\s*pdf\b.*lfs' }
  if ($filtered -ne $lines) {
    # backup e grava limpo
    Copy-Item $ga "$ga.lfsbackup" -Force
    ($filtered -join "`r`n") | Set-Content $ga -Encoding UTF8
    git add .gitattributes | Out-Null
  }
}

# Reindexar tudo (garante que PDFs voltem como arquivos comuns se havia LFS)
try { git rm --cached -r . 2>$null | Out-Null } catch {}
git add -A | Out-Null

# 4) Commit e Push
Write-Host "→ Commitando..."
git commit -m $CommitMsg
if ($LASTEXITCODE -ne 0) { Write-Host "(Nada para commitar.)" }

Write-Host "→ Enviando para GitHub ($Branch)..."
git push -u origin $Branch

Write-Host "✅ Concluído! Confira no repositório:"
Write-Host $RemoteUrl -ForegroundColor Green
