# -*- coding: utf-8 -*-
import sys
import time
import requests
from pathlib import Path
from urllib.parse import quote

# ===== SEUS DADOS GPT MAKER =====
GPT_MAKER_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJncHRtYWtlciIsImlkIjoiM0U0ODZBREVGQzIzNjA4NUZEMDg2RTM0QjJBM0E0QzciLCJ0ZW5hbnQiOiIzRTQ4NkFERUZDMjM2MDg1RkQwODZFMzRCMkEzQTRDNyIsInV1aWQiOiI3ODc3MmVlOS0xYjM1LTQwODktOTZjZC1kN2VjODYxZDA2NjcifQ.JZCvmkHo4q1j8MLZsdILHZPYTWIU1k7k9TsRjqzoV4g"
GPT_MAKER_AGENT_ID = "3E486BB7311B50C738D06AFD7E53B630"
API_URL = f"https://api.gptmaker.ai/v2/agent/{GPT_MAKER_AGENT_ID}/trainings"

# ===== DADOS DO SEU REPO GITHUB =====
OWNER  = "Jefeundertaker"
REPO   = "TREINAMENTO-GPT-MAKER"
BRANCH = "main"

# ===== CAMINHO RELATIVO DO PDF NO REPO (da imagem) =====
REL_PATH = "PDFs_TDN/Desmontagem de Itens - MCP/Desmontagem de Itens - CP0318 - Linha Datasul - TDN.pdf"

def build_raw_url(rel_path: str) -> str:
    """Monta URL RAW correta (com percent-encoding)."""
    rel_posix = Path(rel_path).as_posix()
    return f"https://raw.githubusercontent.com/{OWNER}/{REPO}/{BRANCH}/{quote(rel_posix)}"

def head_ok(url: str, timeout=25) -> bool:
    try:
        r = requests.head(url, timeout=timeout, allow_redirects=True)
        return 200 <= r.status_code < 400
    except Exception:
        return False

def enviar_pdf(pdf_url: str, pdf_name: str) -> bool:
    print(f"→ Enviando: {pdf_name}")
    if not head_ok(pdf_url):
        print(f"❌ URL inacessível (verifique se o arquivo existe e o repo é público):\n   {pdf_url}")
        return False

    payload = {
        "type": "DOCUMENT",
        "documentUrl": pdf_url,
        "documentName": pdf_name,
        "documentMimetype": "application/pdf",
    }
    headers = {
        "Authorization": f"Bearer {GPT_MAKER_TOKEN}",
        "Content-Type": "application/json",
    }

    # retries simples
    last_exc = None
    for i in range(3):
        try:
            resp = requests.post(API_URL, json=payload, headers=headers, timeout=60)
            ok = 200 <= resp.status_code < 300
            try:
                msg = resp.json().get("message") or resp.json().get("status") or ""
            except Exception:
                msg = resp.text[:300]

            if ok:
                print(f"✅ OK [{resp.status_code}] {pdf_name} {('- ' + msg) if msg else ''}")
                return True
            else:
                print(f"❌ ERRO [{resp.status_code}] {pdf_name} {('- ' + msg) if msg else ''}")
                return False
        except Exception as e:
            last_exc = e
            time.sleep(0.8 * (2 ** i))

    print(f"❌ Falha inesperada ao enviar: {last_exc}")
    return False

if __name__ == "__main__":
    url = build_raw_url(REL_PATH)
    name = Path(REL_PATH).name
    ok = enviar_pdf(url, name)
    sys.exit(0 if ok else 1)
