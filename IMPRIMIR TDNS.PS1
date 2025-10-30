<# =====================================================================
  TDN -> PDF via API (PowerShell 5+)
  - Lê:  C:\TDN TOTVS\links tdns.txt
  - Salva: C:\TDN TOTVS\PDFs
  - Para cada URL do TDN:
      * Extrai o ID do artigo
      * Baixa o JSON do Zendesk (título + corpo HTML)
      * Gera HTML local e imprime em PDF com Edge/Chrome headless
  - Fallback: se a API negar, baixa o HTML da página e imprime mesmo assim
===================================================================== #>

$ErrorActionPreference = 'Stop'

# Caminhos
$LinksPath = "C:\TDN TOTVS\links tdns.txt"
$OutDir    = "C:\TDN TOTVS\PDFs"
$TmpDir    = Join-Path $env:TEMP "tdn_html_tmp"

# Ajustes
$MinPdfSizeBytes = 2048
$BaseHost = "https://centraldeatendimento.totvs.com"

function Say($t,$c='Cyan'){ Write-Host $t -ForegroundColor $c }
function Warn($t){ Write-Host "[AVISO] $t" -ForegroundColor Yellow }
function Fail($t){ Write-Host "[ERRO]  $t" -ForegroundColor Red }

# Checagens
if(!(Test-Path $LinksPath)){ Fail "Arquivo não encontrado: $LinksPath"; exit 1 }
$links = Get-Content $LinksPath | Where-Object { $_ -and $_.Trim() } | ForEach-Object { $_.Trim() }
if($links.Count -eq 0){ Fail "Nenhum link válido em $LinksPath"; exit 1 }
if(!(Test-Path $OutDir)){ New-Item -ItemType Directory -Path $OutDir | Out-Null }
if(!(Test-Path $TmpDir)){ New-Item -ItemType Directory -Path $TmpDir | Out-Null }

# Localizar Edge/Chrome
function Get-ChromePath {
  $c=@("$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
       "$env:ProgramFiles(x86)\Google\Chrome\Application\chrome.exe",
       "$env:LocalAppData\Google\Chrome\Application\chrome.exe")
  foreach($p in $c){ if(Test-Path $p){ return $p } }
  return $null
}
function Get-EdgePath {
  $c=@("$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
       "$env:ProgramFiles(x86)\Microsoft\Edge\Application\msedge.exe",
       "$env:LocalAppData\Microsoft\Edge\Application\msedge.exe")
  foreach($p in $c){ if(Test-Path $p){ return $p } }
  return $null
}
$BrowserExe = Get-ChromePath
if(-not $BrowserExe){ $BrowserExe = Get-EdgePath }
if(-not $BrowserExe){ Fail "Instale Chrome ou Edge."; exit 1 }

function Sanitize([string]$s){
  if([string]::IsNullOrWhiteSpace($s)){ $s="sem-titulo" }
  $s = ($s -replace '[\u0000-\u001F"*/:<>?\\|]+',' ') -replace '\s+',' '
  $s = $s.Trim('. ').Trim()
  if($s.Length -gt 150){ $s = $s.Substring(0,150).Trim() }
  if([string]::IsNullOrWhiteSpace($s)){ $s="sem-titulo" }
  return $s
}
function UniquePath([string]$p){
  $x=$p;$i=2
  while(Test-Path $x){
    $dir=Split-Path $p -Parent; $f=[IO.Path]::GetFileNameWithoutExtension($p); $e=[IO.Path]::GetExtension($p)
    $x=Join-Path $dir ("{0} ({1}){2}" -f $f,$i,$e); $i++
  }
  return $x
}

# Imprimir HTML local em PDF
function HtmlToPdf([string]$htmlPath,[string]$pdfPath){
  try{
    & $BrowserExe --headless=new --disable-gpu --no-sandbox `
      --run-all-compositor-stages-before-draw `
      --print-to-pdf="$pdfPath" "file:///$($htmlPath -replace '\\','/')" | Out-Null
    Start-Sleep -Milliseconds 400
    return (Test-Path $pdfPath) -and ((Get-Item $pdfPath).Length -ge $MinPdfSizeBytes)
  } catch { return $false }
}

# Montar HTML a partir do título/corpo (já vindo do Zendesk)
function Build-ArticleHtml([string]$title,[string]$body,[string]$dstHtmlPath){
  $tpl = @"
<!doctype html>
<html lang="pt-br">
<head>
<meta charset="utf-8">
<base href="$BaseHost/">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>$([System.Web.HttpUtility]::HtmlEncode($title))</title>
<style>
  @page { margin: 12mm; }
  body { font-family: Arial, Helvetica, sans-serif; font-size: 12pt; color: #111; }
  h1 { font-size: 20pt; margin: 0 0 14px 0; }
  .article { line-height: 1.45; }
  .article img { max-width: 100%; height: auto; }
  .meta { color:#666; font-size:10pt; margin-bottom:10px; }
  pre, code { font-family: Consolas, monospace; font-size: 10pt; }
  table { border-collapse: collapse; }
  table td, table th { border: 1px solid #ddd; padding: 4px 6px; }
</style>
</head>
<body>
  <h1>$([System.Web.HttpUtility]::HtmlEncode($title))</h1>
  <div class="article">
    $body
  </div>
</body>
</html>
"@
  Set-Content -LiteralPath $dstHtmlPath -Value $tpl -Encoding UTF8
}

# Tenta pegar JSON do artigo (pt-br; fallback global)
function Get-ArticleJson([string]$id){
  $urls = @(
    "$BaseHost/api/v2/help_center/pt-br/articles/$id.json",
    "$BaseHost/api/v2/help_center/articles/$id.json"
  )
  foreach($u in $urls){
    try{
      $r = Invoke-RestMethod -Method GET -Uri $u -Headers @{ 'Accept'='application/json' }
      if($r -and $r.article){ return $r.article }
    } catch { }
  }
  return $null
}

# Se API bloqueou, baixa o HTML da página e usa como fallback
function Get-PageHtml([string]$url){
  try{
    $r = Invoke-WebRequest -Uri $url -UseBasicParsing -Headers @{ 'Accept'='text/html' }
    return $r.Content
  } catch { return $null }
}

# ===== Loop principal =====
$pad = ($links.Count).ToString().Length
$idx = 0
$sw  = [Diagnostics.Stopwatch]::StartNew()

Say "Navegador: $BrowserExe" 'Green'
Say "Links    : $($links.Count)" 'Green'
Say "Saída    : $OutDir" 'Green'

foreach($url in $links){
  $idx++
  Write-Progress -Activity "Gerando PDFs do TDN (via API)" -Status "[$idx/$($links.Count)]" -PercentComplete ([int](($idx/$links.Count)*100))

  # extrai ID
  $m = [regex]::Match($url, 'articles/(\d+)')
  if(-not $m.Success){
    Warn "Não encontrei ID no link — pulando: $url"
    continue
  }
  $id = $m.Groups[1].Value

  Say "[$idx/$($links.Count)] ID=$id" 'DarkCyan'

  # tenta API primeiro
  $article = Get-ArticleJson $id
  $title   = $null
  $body    = $null

  if($article){
    $title = $article.title
    # corpo vem em HTML; garantir que existe
    $body  = if($article.body){ $article.body } else { "" }
  }

  $htmlPath = Join-Path $TmpDir ("art_{0}.html" -f $idx.ToString("D$pad"))

  if($title -and ($body -ne $null)){
    # Monta HTML local a partir do JSON
    Build-ArticleHtml -title $title -body $body -dstHtmlPath $htmlPath
  } else {
    # Fallback: baixa a página HTML e imprime assim mesmo
    $pageHtml = Get-PageHtml $url
    if(-not $pageHtml){
      Warn "Falha ao obter artigo (API e página). Pulando: $url"
      continue
    }
    # tenta extrair um <title>
    $m2 = [regex]::Match($pageHtml,'<title>(.*?)</title>', 'Singleline,IgnoreCase')
    $title = if($m2.Success){ ($m2.Groups[1].Value -replace '\s+',' ').Trim() } else { "pagina" }
    Build-ArticleHtml -title $title -body $pageHtml -dstHtmlPath $htmlPath
  }

  $safeTitle = Sanitize $title
  $pdfPath   = UniquePath (Join-Path $OutDir ("{0}_{1}.pdf" -f $idx.ToString("D$pad"), $safeTitle))

  # Imprime local -> PDF (robusto, sem bloqueios)
  $ok = HtmlToPdf -htmlPath $htmlPath -pdfPath $pdfPath
  if($ok){
    Say "OK -> $pdfPath" 'Green'
  } else {
    Warn "Falhou gerar PDF para ID=$id. Arquivo: $pdfPath"
  }
}

$sw.Stop()
Say ("Concluído em {0:mm\:ss}. PDFs salvos em: {1}" -f $sw.Elapsed, $OutDir) 'Cyan'
