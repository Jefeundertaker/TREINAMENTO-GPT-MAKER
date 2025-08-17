@echo off
setlocal ENABLEDELAYEDEXPANSION

REM ========= CONFIG =========
set "LOCAL_REPO=C:\Projetos\TREINAMENTO-GPT-MAKER"
set "GH_OWNER=Jefeundertaker"
set "GH_REPO=TREINAMENTO-GPT-MAKER"
REM A branch sera detectada automaticamente; se quiser fixar, defina GH_BRANCH=main
set "GH_BRANCH="
set "GPT_MAKER_AGENT_ID=3E486BB7311B50C738D06AFD7E53B630"
set "GPT_MAKER_TOKEN=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJncHRtYWtlciIsImlkIjoiM0U0ODZBREVGQzIzNjA4NUZEMDg2RTM0QjJBM0E0QzciLCJ0ZW5hbnQiOiIzRTQ4NkFERUZDMjM2MDg1RkQwODZFMzRCMkEzQTRDNyIsInV1aWQiOiI3ODc3MmVlOS0xYjM1LTQwODktOTZjZC1kN2VjODYxZDA2NjcifQ.JZCvmkHo4q1j8MLZsdILHZPYTWIU1k7k9TsRjqzoV4g"
REM ==========================

echo.
where python >nul 2>nul || (echo ❌ Python nao encontrado. Instale o Python 3.x. & pause & exit /b 1)
where git >nul 2>nul || (echo ❌ Git nao encontrado. Instale o Git for Windows. & pause & exit /b 1)
if not exist "%LOCAL_REPO%" (echo ❌ Pasta do repo nao encontrada: %LOCAL_REPO% & pause & exit /b 1)

pushd "%LOCAL_REPO%"
REM Detecta branch atual se nao definida
if "%GH_BRANCH%"=="" (
  for /f "usebackq delims=" %%b in (`git rev-parse --abbrev-ref HEAD`) do set "GH_BRANCH=%%b"
)
echo Repo: https://github.com/%GH_OWNER%/%GH_REPO%  |  Branch: %GH_BRANCH%
popd

REM Conta PDFs
for /f "usebackq delims=" %%c in (`powershell -NoProfile -Command "(Get-ChildItem -Recurse -Filter *.pdf -Path '%LOCAL_REPO%' | Measure-Object).Count"`) do set "PDFCOUNT=%%c"
if "%PDFCOUNT%"=="" set "PDFCOUNT=0"
echo Encontrados %PDFCOUNT% PDFs em %LOCAL_REPO%
if "%PDFCOUNT%"=="0" (
  echo ⚠️  Nao ha PDFs. Verifique o caminho e se os arquivos estao no repo local.
  pause & exit /b 0
)

REM Cria venv e instala requests
if not exist "%LOCAL_REPO%\.venv" (
  echo Criando ambiente virtual...
  python -m venv "%LOCAL_REPO%\.venv"
)
call "%LOCAL_REPO%\.venv\Scripts\activate.bat" || (echo ❌ Falha ao ativar venv. & pause & exit /b 1)
python -m pip install --upgrade pip >nul
pip install -U requests >nul

REM Gera script Python com logs e checagem de URL
set "PYFILE=%LOCAL_REPO%\enviar_pdfs_gptmaker.py"
powershell -NoProfile -Command ^
  "$code = @'
# -*- coding: utf-8 -*-
import requests, time, sys
from pathlib import Path

AGENT_ID = \"{aid}\"
TOKEN    = \"{tok}\"
OWNER    = \"{own}\"
REPO     = \"{rep}\"
BRANCH   = \"{br}\"
LOCAL_REPO = Path(r\"{lr}\")

API_URL = f\"https://api.gptmaker.ai/v2/agent/{'{'}AGENT_ID{'}'}/trainings\"

def raw_url(local_path: Path) -> str:
    rel = local_path.relative_to(LOCAL_REPO).as_posix()
    return f\"https://raw.githubusercontent.com/{'{'}OWNER{'}'}/{'{'}REPO{'}'}/{'{'}BRANCH{'}'}/{'{'}rel{'}'}\"

def head_ok(url: str) -> bool:
    try:
        r = requests.head(url, timeout=20, allow_redirects=True)
        return r.status_code == 200
    except Exception:
        return False

def enviar(url: str, nome: str):
    payload = {{
        \"type\": \"DOCUMENT\",
        \"documentUrl\": url,
        \"documentName\": nome,
        \"documentMimetype\": \"application/pdf\"
    }}
    headers = {{\"Authorization\": f\"Bearer { '{' }TOKEN{ '}' }\", \"Content-Type\": \"application/json\"}}
    r = requests.post(API_URL, json=payload, headers=headers, timeout=60)
    ok = 200 <= r.status_code < 300
    try:
        msg = r.json().get(\"message\") or r.json().get(\"status\") or \"\"
    except Exception:
        msg = r.text[:200]
    return ok, r.status_code, msg

def main():
    pdfs = sorted(LOCAL_REPO.rglob(\"*.pdf\"))
    print(f\"Detectado {len(pdfs)} PDFs. Repo local: {LOCAL_REPO}\")
    print(\"Exibindo ate 10 primeiros:\")
    for p in pdfs[:10]:
        print(\" -\", p)

    okc, errc = 0, 0
    for p in pdfs:
        url = raw_url(p)
        if not head_ok(url):
            print(f\"⚠️  SKIP (URL inacessivel): {url}\")
            errc += 1
            continue
        ok, status, msg = enviar(url, p.name)
        if ok:
            print(f\"✅ {p}  status={status} {msg}\")
            okc += 1
        else:
            print(f\"❌ {p}  status={status} {msg}\")
            errc += 1
        time.sleep(0.25)

    print(\"\\n===== RESUMO =====\")
    print(\"Sucesso:\", okc)
    print(\"Erros:  \", errc)

if __name__ == \"__main__\":
    main()
'@; $code = $code.Replace('{aid}', '%GPT_MAKER_AGENT_ID%').Replace('{tok}','%GPT_MAKER_TOKEN%').Replace('{own}','%GH_OWNER%').Replace('{rep}','%GH_REPO%').Replace('{br}','%GH_BRANCH%').Replace('{lr}','%LOCAL_REPO%'); Set-Content -Path '%PYFILE%' -Value $code -Encoding UTF8"

echo.
echo ===== INICIANDO ENVIO =====
python "%PYFILE%"

echo.
echo (Se nao apareceu nada ou deu muitos SKIP, verifique:)
echo  1) Branch correta: %GH_BRANCH%  (no GitHub o arquivo esta na mesma branch?)
echo  2) O caminho relativo do arquivo no repo coincide com o caminho local?
echo  3) O repo no GitHub e PUBLICO (necessario para URL raw)?
echo  4) Teste um link raw no navegador: https://raw.githubusercontent.com/%GH_OWNER%/%GH_REPO%/%GH_BRANCH%/README.md
echo.
pause
