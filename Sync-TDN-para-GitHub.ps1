# === COLAR TUDO DE UMA VEZ NO POWERSHELL ===

# CONFIG
$SrcDir    = "C:\TDN TOTVS"
$LocalRepo = "C:\Projetos\TREINAMENTO-GPT-MAKER"
$RemoteUrl = "https://github.com/Jefeundertaker/TREINAMENTO-GPT-MAKER.git"
$Branch    = "main"
$UserName  = "Jefeundertaker"
$UserEmail = "seu_email@exemplo.com"
$CommitMsg = "snapshot: estado atual de C:\TDN TOTVS (histórico substituído)"

# Não pedir senha interativa
$env:GIT_TERMINAL_PROMPT = "0"
$env:GCM_INTERACTIVE     = "Never"

# 1) Recria o repo local LIMPO
if (Test-Path $LocalRepo) { Try{ [GC]::Collect(); [GC]::WaitForPendingFinalizers() }Catch{}; Remove-Item -Recurse -Force $LocalRepo }
$parent = Split-Path $LocalRepo -Parent
if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
git clone --depth 1 $RemoteUrl $LocalRepo

# 2) Cria branch órfã e limpa working tree
$orphan = "snapshot-{0:yyyyMMdd-HHmmss}" -f (Get-Date)
git -C $LocalRepo config user.name  $UserName
git -C $LocalRepo config user.email $UserEmail
git -C $LocalRepo checkout --orphan $orphan

# Remove tudo MENOS .git
Get-ChildItem -LiteralPath $LocalRepo -Force -Recurse |
  Where-Object { $_.FullName -notmatch "\\\.git(\\|$)" } |
  Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

# 3) Copia a origem pro repo (sem tocar .git)
robocopy "$SrcDir" "$LocalRepo" /E /R:1 /W:1 /NFL /NDL /NJH /NJS /NP /MT:16 /XD ".git" "node_modules" ".venv" "dist" "build" "_runner" "ChromeProfile" ".pw-profile"
if ($LASTEXITCODE -ge 8) { throw "robocopy falhou (exit $LASTEXITCODE)" }

# 4) Commit único
git -C $LocalRepo add -A
$changes = git -C $LocalRepo status --porcelain
if (-not $changes) {
  git -C $LocalRepo commit --allow-empty -m $CommitMsg
} else {
  git -C $LocalRepo commit -m $CommitMsg
}

# 5) Push FORÇADO para main
$refspec = "+$($orphan):$Branch"
git -C $LocalRepo -c http.lowSpeedLimit=1 -c http.lowSpeedTime=30 push origin $refspec

# 6) Ajusta branch local
git -C $LocalRepo checkout -B $Branch
git -C $LocalRepo reset --hard "origin/$Branch"

Write-Host "✅ Pronto: main substituída pelo snapshot de '$SrcDir'." -ForegroundColor Green
