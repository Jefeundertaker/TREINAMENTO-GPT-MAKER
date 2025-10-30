# ================== tdn_to_pdf_fix.ps1 ==================
# Lê os links do arquivo e imprime cada página em PDF (com prefixo "GFE - " + título)
# Uso:
#   .\tdn_to_pdf_fix.ps1 -InputFile "C:\TDN TOTVS\links tdns.txt" -OutputDir "C:\TDN TOTVS\PDFs"

param(
    [string]$InputFile = "C:\TDN TOTVS\links tdns.txt",
    [string]$OutputDir = "C:\TDN TOTVS\PDFs",
    [int]$VirtualTimeMs = 12000  # tempo para carregar imagens antes de imprimir
)

# --- Utilidades ---
function Sanitize-Name([string]$name) {
    $n = $name -replace '[\x00-\x1F]+','' -replace '[<>:"/\\|?*]','_' -replace '\s+',' '
    if ([string]::IsNullOrWhiteSpace($n)) { $n = 'TDN' }
    if ($n.Length -gt 180) { $n = $n.Substring(0,180) }
    return $n.Trim()
}

function Get-PageTitle([string]$url) {
    try {
        # User-Agent moderno para evitar bloqueios simples
        $headers = @{ 'User-Agent' = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36' }
        $resp = Invoke-WebRequest -Uri $url -Headers $headers -TimeoutSec 20 -UseBasicParsing
        if ($resp -and $resp.Content) {
            $m = [regex]::Match($resp.Content, '<title>\s*(.*?)\s*</title>', 'IgnoreCase')
            if ($m.Success) {
                return ($m.Groups[1].Value -replace '\r|\n',' ' -replace '\s+',' ').Trim()
            }
        }
    } catch {
        # Pode falhar em páginas com login/Cloudflare; sem problemas, cairemos no pageId
    }
    return $null
}

function Get-BrowserPath {
    $candidates = @(
        "$Env:ProgramFiles(x86)\Microsoft\Edge\Application\msedge.exe",
        "$Env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
        "$Env:LocalAppData\Microsoft\Edge\Application\msedge.exe",
        "$Env:ProgramFiles\Google\Chrome\Application\chrome.exe",
        "$Env:LocalAppData\Google\Chrome\Application\chrome.exe"
    )
    foreach ($p in $candidates) {
        if (Test-Path $p) { return $p }
    }
    return $null
}

function Print-ToPdf([string]$browserPath, [string]$url, [string]$outPdf, [int]$virtualTime) {
    # MUITO IMPORTANTE: colocar --print-to-pdf="C:\caminho com espaços.pdf"
    $args = @(
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--run-all-compositor-stages-before-draw",
        "--virtual-time-budget=$virtualTime",
        "--print-to-pdf=""$outPdf""",
        "--print-to-pdf-no-header",
        $url
    )

    # Executa e aguarda terminar
    $p = Start-Process -FilePath $browserPath -ArgumentList $args -PassThru -WindowStyle Hidden
    $p.WaitForExit()
    return $p.ExitCode
}

# --- Preparação ---
if (-not (Test-Path $InputFile)) {
    Write-Host "Arquivo não encontrado: $InputFile" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir | Out-Null
}

$links = Get-Content $InputFile | Where-Object { $_ -match '^https?://' }
if (-not $links) {
    Write-Host "Nenhum link válido encontrado em $InputFile" -ForegroundColor Red
    exit 1
}

$browser = Get-BrowserPath
if (-not $browser) {
    Write-Host "Microsoft Edge/Google Chrome não encontrados. Instale um deles." -ForegroundColor Red
    exit 1
}

Write-Host "Usando navegador: $browser" -ForegroundColor Cyan
Write-Host "Saída: $OutputDir" -ForegroundColor Cyan

# --- Loop principal ---
$ok = 0; $fail = 0; $i = 0
foreach ($url in $links) {
    $i++

    # Nome amigável: tenta título; se falhar, usa pageId; se falhar, usa índice
    $title = Get-PageTitle $url
    if (-not $title) {
        $pid = ([regex]::Match($url, 'pageId=(\d+)')).Groups[1].Value
        if ([string]::IsNullOrWhiteSpace($pid)) { $pid = $i }
        $title = "TDN $pid"
    }
    $baseName = "GFE - " + (Sanitize-Name $title) + ".pdf"
    $outPath = Join-Path $OutputDir $baseName

    Write-Host "[$i/$($links.Count)] Gerando PDF: $outPath"

    try {
        $code = Print-ToPdf -browserPath $browser -url $url -outPdf $outPath -virtualTime $VirtualTimeMs

        if ($code -ne 0 -or -not (Test-Path $outPath)) {
            # Tenta de novo com outra flag de headless
            $altArgs = @(
                "--headless",
                "--disable-gpu",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--run-all-compositor-stages-before-draw",
                "--virtual-time-budget=$VirtualTimeMs",
                "--print-to-pdf=""$outPath""",
                "--print-to-pdf-no-header",
                $url
            )
            $p2 = Start-Process -FilePath $browser -ArgumentList $altArgs -PassThru -WindowStyle Hidden
            $p2.WaitForExit()
        }

        if (Test-Path $outPath) {
            Write-Host "   ✓ OK"
            $ok++
        } else {
            Write-Host "   ✗ Falhou para $url" -ForegroundColor Red
            $fail++
        }
    } catch {
        Write-Host "   ✗ Falhou para $url -> $($_.Exception.Message)" -ForegroundColor Red
        $fail++
    }
}

Write-Host ""
Write-Host "Concluído. OK=$ok, Falhas=$fail" -ForegroundColor Green
# ================== fim ==================
