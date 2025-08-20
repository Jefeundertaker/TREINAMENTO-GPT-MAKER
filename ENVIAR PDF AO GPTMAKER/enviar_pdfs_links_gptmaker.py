# -*- coding: utf-8 -*-
"""
Envia TODOS os PDFs localizados em <LOCAL_REPO>/pdfs_links para o GPT Maker.
- Monta URL RAW do GitHub p/ cada PDF
- HEAD de validação
- Detecção de ponteiro Git LFS (pula)
- Retries com backoff
- CSV de relatório p/ reprocessar só erros

Uso:
    python enviar_pdfs_links_gptmaker.py
    python enviar_pdfs_links_gptmaker.py --dry-run
    python enviar_pdfs_links_gptmaker.py --resume errors
"""

import csv
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import requests
import argparse

# ====== SEUS DADOS GPT MAKER ======
GPT_MAKER_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJncHRtYWtlciIsImlkIjoiM0U0ODZBREVGQzIzNjA4NUZEMDg2RTM0QjJBM0E0QzciLCJ0ZW5hbnQiOiIzRTQ4NkFERUZDMjM2MDg1RkQwODZFMzRCMkEzQTRDNyIsInV1aWQiOiI3ODc3MmVlOS0xYjM1LTQwODktOTZjZC1kN2VjODYxZDA2NjcifQ.JZCvmkHo4q1j8MLZsdILHZPYTWIU1k7k9TsRjqzoV4g"
GPT_MAKER_AGENT_ID = "3E486BB7311B50C738D06AFD7E53B630"
API_URL = f"https://api.gptmaker.ai/v2/agent/{GPT_MAKER_AGENT_ID}/trainings"

# ====== REPOSITÓRIO (LOCAL E REMOTO) ======
OWNER   = "Jefeundertaker"
REPO    = "TREINAMENTO-GPT-MAKER"
BRANCH  = "main"
LOCAL_REPO = Path(r"C:\Projetos\TREINAMENTO-GPT-MAKER")  # ajuste se seu clone estiver em outro lugar
ROOT_SUBFOLDER = "pdfs_links"                             # <--- conforme seu pedido

# ====== AJUSTES ======
PDF_MIMETYPE  = "application/pdf"
SLEEP_BETWEEN = 0.35
RETRIES       = 3
TIMEOUT       = 60
HEAD_TIMEOUT  = 20
SNIFF_BYTES   = 512
REPORT_PATH   = LOCAL_REPO / "gptmaker_envio_report.csv"

ap = argparse.ArgumentParser(description="Enviar PDFs da pasta 'pdfs_links' ao GPT Maker.")
ap.add_argument("--dry-run", action="store_true", help="Não envia; apenas valida e registra no CSV.")
ap.add_argument("--resume", choices=["errors"], help="Reprocessar somente os erros do CSV anterior.")
args = ap.parse_args()


def posix(p: Path) -> str:
    return p.as_posix()


def build_raw_url(local_pdf: Path) -> str:
    rel = local_pdf.relative_to(LOCAL_REPO).as_posix()
    return f"https://raw.githubusercontent.com/{OWNER}/{REPO}/{BRANCH}/{quote(rel)}"


def head_ok(url: str):
    try:
        r = requests.head(url, allow_redirects=True, timeout=HEAD_TIMEOUT)
        return (200 <= r.status_code < 400), r.status_code
    except Exception:
        return False, 0


def is_lfs_pointer(url: str):
    try:
        r = requests.get(url, stream=True, timeout=HEAD_TIMEOUT, allow_redirects=True)
        r.raise_for_status()
        chunk = next(r.iter_content(SNIFF_BYTES), b"")
        text = chunk.decode("utf-8", errors="ignore")
        ptr = ("git-lfs.github.com/spec/v1" in text) or text.startswith("version https://git-lfs")
        size = int(r.headers.get("Content-Length", "0")) if r.headers.get("Content-Length") else 0
        return ptr, size
    except Exception:
        return False, 0


def post_with_retries(payload: dict, headers: dict):
    last = None
    for i in range(1, RETRIES + 1):
        try:
            return requests.post(API_URL, json=payload, headers=headers, timeout=TIMEOUT)
        except Exception as e:
            last = e
            if i < RETRIES:
                time.sleep(0.8 * (2 ** (i - 1)))
    raise last if last else RuntimeError("Falha desconhecida no POST")


def send_one(url: str, name: str):
    headers = {
        "Authorization": f"Bearer {GPT_MAKER_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "type": "DOCUMENT",
        "documentUrl": url,
        "documentName": name,
        "documentMimetype": PDF_MIMETYPE,
    }
    resp = post_with_retries(payload, headers)
    ok = 200 <= resp.status_code < 300
    try:
        data = resp.json()
        msg = data.get("message") or data.get("status") or ""
    except Exception:
        msg = resp.text[:300]
    return ok, resp.status_code, msg


def list_pdfs_in_pdfs_links() -> list[Path]:
    base = LOCAL_REPO / ROOT_SUBFOLDER
    if not base.exists():
        print(f"⚠️ A subpasta '{ROOT_SUBFOLDER}' não existe em {LOCAL_REPO}.")
        return []
    return sorted(p for p in base.rglob("*.pdf") if p.is_file())


def load_previous_errors(report_file: Path) -> set:
    if not report_file.exists():
        return set()
    errs = set()
    with report_file.open(encoding="utf-8") as f:
        rdr = csv.DictReader(f)
        for row in rdr:
            ok = row.get("status_ok", "")
            code = row.get("status_code", "")
            if ok == "False" or (code.startswith("4") or code.startswith("5")) or code in ("HEAD:0", "HEAD:404", "LFS"):
                lp = row.get("local_path", "")
                if lp:
                    errs.add(lp.replace("\\", "/"))
    return errs


def main():
    # montar lista
    if args.resume == "errors":
        prev_errs = load_previous_errors(REPORT_PATH)
        all_pdfs = list_pdfs_in_pdfs_links()
        if not prev_errs:
            pdfs = all_pdfs
        else:
            pdfs = [p for p in all_pdfs if posix(p.relative_to(LOCAL_REPO)) in prev_errs]
            if not pdfs:
                pdfs = [LOCAL_REPO / e for e in prev_errs if (LOCAL_REPO / e).exists()]
    else:
        pdfs = list_pdfs_in_pdfs_links()

    if not pdfs:
        print("⚠️ Nenhum PDF encontrado em 'pdfs_links'.")
        return 0

    print(f"Encontrados {len(pdfs)} PDFs em '{ROOT_SUBFOLDER}'. {'(dry-run)' if args.dry_run else ''}")

    new_file = not REPORT_PATH.exists()
    with REPORT_PATH.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["ts", "local_path", "raw_url", "size_bytes", "is_lfs_pointer", "status_ok", "status_code", "message"])

        okc = errc = 0
        for p in pdfs:
            rel_local = posix(p.relative_to(LOCAL_REPO))
            raw = build_raw_url(p)

            ok_head, code_head = head_ok(raw)
            if not ok_head:
                w.writerow([datetime.utcnow().isoformat(), rel_local, raw, 0, "", False, f"HEAD:{code_head}", "HEAD fail"])
                print(f"❌ HEAD {code_head}  {rel_local}")
                errc += 1
                time.sleep(SLEEP_BETWEEN)
                continue

            is_ptr, size = is_lfs_pointer(raw)
            if is_ptr:
                w.writerow([datetime.utcnow().isoformat(), rel_local, raw, size, True, False, "LFS", "LFS pointer detected"])
                print(f"⏭️  PULADO (LFS) {rel_local}")
                errc += 1
                time.sleep(SLEEP_BETWEEN)
                continue

            if args.dry_run:
                w.writerow([datetime.utcnow().isoformat(), rel_local, raw, size, False, True, "DRY", "validated"])
                print(f"📝 DRY  {rel_local}")
                okc += 1
                time.sleep(SLEEP_BETWEEN)
                continue

            ok, st, msg = send_one(raw, p.name)
            w.writerow([datetime.utcnow().isoformat(), rel_local, raw, size, False, ok, st, msg])

            if ok:
                print(f"✅ {st}  {rel_local}  {('- ' + msg) if msg else ''}")
                okc += 1
            else:
                print(f"❌ {st}  {rel_local}  {('- ' + msg) if msg else ''}")
                errc += 1

            time.sleep(SLEEP_BETWEEN)

    print("\n===== RESUMO =====")
    print("Sucesso:", okc)
    print("Erros:  ", errc)
    print(f"Relatório: {REPORT_PATH}")
    return 0 if errc == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
