# -*- coding: utf-8 -*-
"""
Envia TUDO que estiver na pasta TEXTO do seu repositório GitHub para o GPT Maker,
**sempre como TEXT (aba Texto) por padrão**.  (Atende ao pedido: "levar para aba text").

Se quiser reativar o envio para Documento baseado em extensão/nome, use --allow-document.

✅ Usa os MESMOS dados (TOKEN e AGENT) do "programa modelo" (o de PDFs):
   - Procura automaticamente por um script contendo:
       GPT_MAKER_TOKEN = "...."
       GPT_MAKER_AGENT_ID = "...."
   - Ordem de busca:
       1) --token e --agent-id (CLI)
       2) Variáveis de ambiente: GPT_MAKER_TOKEN / GPT_MAKER_AGENT_ID
       3) Algum arquivo *.py no diretório atual (ou acima) contendo as variáveis
          (prioriza arquivo chamado enviar_pdfs_links_gptmaker.py)

📦 Como usar (exemplos):
    python enviar_texto_docs_gptmaker.py --dry-run
    python enviar_texto_docs_gptmaker.py
    # (opcional) permitir DOCUMENT novamente:
    python enviar_texto_docs_gptmaker.py --allow-document
"""

import argparse
import csv
import mimetypes
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

import requests

# =========================
# Configurações padrão
# =========================
DEFAULT_OWNER  = "Jefeundertaker"
DEFAULT_REPO   = "TREINAMENTO-GPT-MAKER"
DEFAULT_BRANCH = "main"
DEFAULT_FOLDER = "TEXTO"  # pasta base no GitHub a partir da raiz do repo

SLEEP_BETWEEN = 0.35
TIMEOUT       = 60
RETRIES       = 3

mimetypes.init()
DOC_MIMES = {
    ".pdf":  "application/pdf",
    ".doc":  "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

# =========================
# Utilidades
# =========================
def backoff_sleep(attempt: int):
    time.sleep(0.8 * (2 ** (attempt - 1)))

def http_get_json(url: str, **kwargs):
    for i in range(1, RETRIES + 1):
        try:
            r = requests.get(url, timeout=TIMEOUT, **kwargs)
            r.raise_for_status()
            return r.json()
        except Exception:
            if i == RETRIES:
                raise
            backoff_sleep(i)

def http_get_raw(url: str, **kwargs):
    for i in range(1, RETRIES + 1):
        try:
            r = requests.get(url, timeout=TIMEOUT, **kwargs)
            r.raise_for_status()
            return r.content
        except Exception:
            if i == RETRIES:
                raise
            backoff_sleep(i)

def http_head_ok(url: str) -> Tuple[bool, int]:
    try:
        r = requests.head(url, allow_redirects=True, timeout=20)
        return (200 <= r.status_code < 400), r.status_code
    except Exception:
        return False, 0

def is_lfs_pointer_bytes(b: bytes) -> bool:
    head = b[:512].decode("utf-8", errors="ignore")
    return ("git-lfs.github.com/spec/v1" in head) or head.startswith("version https://git-lfs")

# =========================
# Classificação (só usada se --allow-document)
# =========================
def classify_tipo(filename: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Decide TEXT ou DOCUMENT (APENAS quando --allow-document é usado).
    Regras de NOME (sobrescrevem extensão):
      - prefixo 'texto_'  -> TEXT
      - sufixo '_doc' no stem -> DOCUMENT
    Extensão:
      - .txt -> TEXT
      - .pdf/.doc/.docx -> DOCUMENT
    Retorna: (tipo, mimetype) - mimetype só é usado p/ DOCUMENT.
    """
    p = Path(filename)
    name = p.name.lower()
    stem = p.stem.lower()
    ext  = p.suffix.lower()

    # 1) regras de nome
    if name.startswith("texto_"):
        return "TEXT", None
    if stem.endswith("_doc"):
        return "DOCUMENT", DOC_MIMES.get(ext, mimetypes.types_map.get(ext, "application/octet-stream"))

    # 2) extensão
    if ext == ".txt":
        return "TEXT", None
    if ext in DOC_MIMES:
        return "DOCUMENT", DOC_MIMES[ext]

    return "TEXT", None  # fallback para TEXT

# =========================
# Descoberta de credenciais
# =========================
def extract_credentials_from_text(txt: str) -> Tuple[Optional[str], Optional[str]]:
    tok  = re.search(r'GPT_MAKER_TOKEN\s*=\s*[\'"]([^\'"]+)[\'"]',  txt)
    agid = re.search(r'GPT_MAKER_AGENT_ID\s*=\s*[\'"]([^\'"]+)[\'"]', txt)
    return (tok.group(1) if tok else None, agid.group(1) if agid else None)

def find_model_script(start_dir: Path) -> Optional[Path]:
    # prioriza arquivo com nome "enviar_pdfs_links_gptmaker.py"
    candidates = []
    for root in [start_dir] + list(start_dir.parents):
        for p in root.glob("*.py"):
            if p.name.lower() == "enviar_pdfs_links_gptmaker.py":
                return p
            candidates.append(p)
    return candidates[0] if candidates else None

def load_credentials(cli_token: Optional[str], cli_agent: Optional[str]) -> Tuple[str, str]:
    # 1) CLI
    if cli_token and cli_agent:
        return cli_token, cli_agent

    # 2) ENV
    env_tok  = os.getenv("GPT_MAKER_TOKEN")
    env_agid = os.getenv("GPT_MAKER_AGENT_ID")
    if env_tok and env_agid:
        return env_tok, env_agid

    # 3) Script modelo
    model = find_model_script(Path.cwd())
    if model and model.exists():
        try:
            txt = model.read_text(encoding="utf-8", errors="ignore")
            tok, agid = extract_credentials_from_text(txt)
            if tok and agid:
                return tok, agid
        except Exception:
            pass

    raise RuntimeError("Credenciais não encontradas. "
                       "Use --token e --agent-id, ou defina env GPT_MAKER_TOKEN/GPT_MAKER_AGENT_ID, "
                       "ou mantenha no diretório (ou acima) um script *.py com GPT_MAKER_TOKEN e GPT_MAKER_AGENT_ID.")

# =========================
# GitHub listing recursiva
# =========================
def list_github_folder(owner: str, repo: str, branch: str, folder: str) -> List[Dict]:
    """
    Retorna uma lista de arquivos (recursivo) com:
      - path, name, download_url
    """
    base_api = f"https://api.github.com/repos/{owner}/{repo}/contents/{quote(folder)}?ref={quote(branch)}"
    result = []

    def _walk(url: str):
        items = http_get_json(url)
        for it in items:
            t = it.get("type")
            if t == "file":
                result.append({"path": it.get("path"), "name": it.get("name"), "download_url": it.get("download_url")})
            elif t == "dir":
                sub_url = it.get("url")
                if sub_url:
                    _walk(sub_url)

    _walk(base_api)
    return result

# =========================
# Envio ao GPT Maker
# =========================
def post_gptmaker_trainings(api_url: str, token: str, payload: dict) -> Tuple[bool, int, str]:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    last_exc = None
    for i in range(1, RETRIES + 1):
        try:
            r = requests.post(api_url, json=payload, headers=headers, timeout=TIMEOUT)
            ok = 200 <= r.status_code < 300
            msg = ""
            try:
                data = r.json()
                msg = data.get("message") or data.get("status") or ""
            except Exception:
                msg = r.text[:300]
            return ok, r.status_code, msg
        except Exception as e:
            last_exc = e
            if i == RETRIES:
                return False, 0, f"POST_ERR: {e}"
            backoff_sleep(i)

# =========================
# Main
# =========================
def main():
    parser = argparse.ArgumentParser(description="Enviar arquivos da pasta TEXTO do GitHub ao GPT Maker (sempre TEXT por padrão).")
    parser.add_argument("--owner", default=DEFAULT_OWNER)
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    parser.add_argument("--folder", default=DEFAULT_FOLDER, help="Subpasta na raiz do repo a listar (ex.: TEXTO)")
    parser.add_argument("--dry-run", action="store_true", help="Não envia; apenas valida")
    parser.add_argument("--token", dest="token")
    parser.add_argument("--agent-id", dest="agent_id")
    parser.add_argument("--report", default="gptmaker_envio_texto_report.csv")
    parser.add_argument("--allow-document", action="store_true", help="Permite reclassificar como DOCUMENT por extensão/nome.")
    args = parser.parse_args()

    try:
        token, agent_id = load_credentials(args.token, args.agent_id)
    except Exception as e:
        print(f"❌ {e}")
        return 2

    api_url = f"https://api.gptmaker.ai/v2/agent/{agent_id}/trainings"

    try:
        items = list_github_folder(args.owner, args.repo, args.branch, args.folder)
    except Exception as e:
        print(f"❌ Falha ao listar a pasta '{args.folder}' no GitHub: {e}")
        return 3

    if not items:
        print(f"⚠️ Nenhum arquivo encontrado em '{args.folder}' no repo {args.owner}/{args.repo} ({args.branch}).")
        return 0

    print(f"📂 {len(items)} arquivo(s) localizado(s) em {args.owner}/{args.repo}/{args.folder} ({args.branch}).{' (dry-run)' if args.dry_run else ''}")
    report_path = Path(args.report)
    new_file = not report_path.exists()

    with report_path.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["ts", "path", "download_url", "kind", "size_bytes", "status_ok", "status_code", "message"])

        okc = errc = 0

        for it in items:
            name = it["name"]
            url  = it["download_url"]

            # Força TEXT por padrão. Só permite DOCUMENT se --allow-document.
            if args.allow_document:
                kind, _mtype = classify_tipo(name)
            else:
                kind, _mtype = "TEXT", None

            # HEAD
            ok_head, code_head = http_head_ok(url)
            if not ok_head:
                w.writerow([datetime.utcnow().isoformat(), it["path"], url, kind, 0, False, f"HEAD:{code_head}", "HEAD fail"])
                print(f"❌ HEAD {code_head}  {it['path']}")
                errc += 1
                time.sleep(SLEEP_BETWEEN)
                continue

            # Baixa conteúdo e envia como TEXT
            try:
                raw = http_get_raw(url)
            except Exception as e:
                w.writerow([datetime.utcnow().isoformat(), it["path"], url, "TEXT", 0, False, "TXT_DL_ERR", f"download failed: {e}"])
                print(f"❌ TXT_DL_ERR {it['path']} - {e}")
                errc += 1
                time.sleep(SLEEP_BETWEEN)
                continue

            if is_lfs_pointer_bytes(raw):
                w.writerow([datetime.utcnow().isoformat(), it["path"], url, "TEXT", len(raw), False, "LFS", "LFS pointer detected"])
                print(f"⏭️  PULADO (LFS) {it['path']}")
                errc += 1
                time.sleep(SLEEP_BETWEEN)
                continue

            try:
                text = raw.decode("utf-8-sig", errors="replace")
            except Exception as e:
                w.writerow([datetime.utcnow().isoformat(), it["path"], url, "TEXT", len(raw), False, "DECODE_ERR", f"{e}"])
                print(f"❌ DECODE_ERR {it['path']} - {e}")
                errc += 1
                time.sleep(SLEEP_BETWEEN)
                continue

            if args.dry_run:
                w.writerow([datetime.utcnow().isoformat(), it["path"], url, "TEXT", len(raw), True, "DRY", "validated"])
                print(f"✅ (dry) TEXT  {it['path']}")
            else:
                payload = {"type": "TEXT", "text": text}
                ok, code, msg = post_gptmaker_trainings(api_url, token, payload)
                w.writerow([datetime.utcnow().isoformat(), it["path"], url, "TEXT", len(raw), ok, code, msg])
                if ok:
                    print(f"✅ TEXT  {it['path']}")
                    okc += 1
                else:
                    print(f"❌ {code} TEXT  {it['path']}  {('- ' + msg) if msg else ''}")
                    errc += 1

            time.sleep(SLEEP_BETWEEN)

    print("\n===== RESUMO =====")
    print("Sucesso:", okc)
    print("Erros:  ", errc)
    print(f"Relatório: {report_path.resolve()}")
    return 0 if errc == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
