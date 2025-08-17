# -*- coding: utf-8 -*-
"""
Envio de PDFs ao GPT Maker:
- Modo 1 (único):   python enviar_pdfs_gptmaker.py --url "<raw_url>" --name "Arquivo.pdf"
- Modo 2 (em lote): python enviar_pdfs_gptmaker.py --bulk

No modo em lote, o script varre LOCAL_REPO e envia todos os .pdf,
gerando a URL "raw.githubusercontent.com" com base em OWNER/REPO/BRANCH.
"""

import argparse
import sys
import time
from pathlib import Path
import requests

# ====== CONFIG GPT MAKER (SEUS DADOS) ======
GPT_MAKER_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJncHRtYWtlciIsImlkIjoiM0U0ODZBREVGQzIzNjA4NUZEMDg2RTM0QjJBM0E0QzciLCJ0ZW5hbnQiOiIzRTQ4NkFERUZDMjM2MDg1RkQwODZFMzRCMkEzQTRDNyIsInV1aWQiOiI3ODc3MmVlOS0xYjM1LTQwODktOTZjZC1kN2VjODYxZDA2NjcifQ.JZCvmkHo4q1j8MLZsdILHZPYTWIU1k7k9TsRjqzoV4g"
GPT_MAKER_AGENT_ID = "3E486BB7311B50C738D06AFD7E53B630"
API_URL = f"https://api.gptmaker.ai/v2/agent/{GPT_MAKER_AGENT_ID}/trainings"

# ====== CONFIG GITHUB (SEU REPO) ======
OWNER   = "Jefeundertaker"
REPO    = "TREINAMENTO-GPT-MAKER"
BRANCH  = "main"
# Caminho local onde você clonou o repositório
LOCAL_REPO = Path(r"C:\Projetos\TREINAMENTO-GPT-MAKER")

PDF_MIMETYPE = "application/pdf"

# ---------- utilidades ----------
def head_ok(url: str, timeout=25) -> bool:
    try:
        r = requests.head(url, timeout=timeout, allow_redirects=True)
        return 200 <= r.status_code < 400
    except Exception:
        return False

def post_with_retries(url, json, headers, tries=3, base_delay=0.8, timeout=60):
    last_exc = None
    for i in range(1, tries + 1):
        try:
            return requests.post(url, json=json, headers=headers, timeout=timeout)
        except Exception as e:
            last_exc = e
            if i < tries:
                time.sleep(base_delay * (2 ** (i - 1)))
    raise last_exc if last_exc else RuntimeError("Falha desconhecida no POST")

def raw_url_for(local_path: Path) -> str:
    rel = local_path.relative_to(LOCAL_REPO).as_posix()
    return f"https://raw.githubusercontent.com/{OWNER}/{REPO}/{BRANCH}/{rel}"

def enviar_um(pdf_url: str, pdf_name: str) -> bool:
    print(f"→ Enviando: {pdf_name}")
    if not head_ok(pdf_url):
        print(f"❌ URL inacessível: {pdf_url}")
        return False

    payload = {
        "type": "DOCUMENT",
        "documentUrl": pdf_url,
        "documentName": pdf_name,
        "documentMimetype": PDF_MIMETYPE
    }
    headers = {
        "Authorization": f"Bearer {GPT_MAKER_TOKEN}",
        "Content-Type": "application/json"
    }

    resp = post_with_retries(API_URL, payload, headers, tries=3, base_delay=0.8, timeout=60)
    ok = 200 <= resp.status_code < 300

    try:
        data = resp.json()
        msg = data.get("message") or data.get("status") or ""
    except Exception:
        msg = resp.text[:300]

    if ok:
        print(f"✅ OK [{resp.status_code}] {pdf_name} {('- ' + msg) if msg else ''}")
        return True
    else:
        print(f"❌ ERRO [{resp.status_code}] {pdf_name} {('- ' + msg) if msg else ''}")
        return False

# ---------- CLI ----------
def parse_args():
    ap = argparse.ArgumentParser(description="Enviar PDF(s) do GitHub (raw) para o GPT Maker.")
    ap.add_argument("--url", help="URL pública (raw) do PDF para envio único.")
    ap.add_argument("--name", help="Nome do documento (envio único).")
    ap.add_argument("--bulk", action="store_true", help="Enviar TODOS os PDFs do repositório local (LOCAL_REPO).")
    return ap.parse_args()

def main():
    args = parse_args()

    if args.bulk:
        if not LOCAL_REPO.exists():
            print(f"❌ LOCAL_REPO não encontrado: {LOCAL_REPO}")
            return 2

        pdfs = sorted(LOCAL_REPO.rglob("*.pdf"))
        if not pdfs:
            print(f"⚠️ Nenhum PDF em {LOCAL_REPO}")
            return 0

        print(f"Encontrados {len(pdfs)} PDFs em {LOCAL_REPO}. Iniciando...")
        okc, errc = 0, 0
        for p in pdfs:
            url = raw_url_for(p)
            ok = enviar_um(url, p.name)
            if ok: okc += 1
            else:  errc += 1
            time.sleep(0.25)  # respiro
        print("\n===== RESUMO =====")
        print("Sucesso:", okc)
        print("Erros:  ", errc)
        return 0 if errc == 0 else 1

    # envio único
    if not args.url or not args.name:
        print("Uso (envio único): python enviar_pdfs_gptmaker.py --url <raw_url> --name \"Arquivo.pdf\"")
        print("Ou (em lote):      python enviar_pdfs_gptmaker.py --bulk")
        return 2

    ok = enviar_um(args.url, args.name)
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
