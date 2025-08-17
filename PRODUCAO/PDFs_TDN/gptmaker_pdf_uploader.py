#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Lê PDFs de uma pasta local (recursivo), preserva a estrutura relativa de pastas,
faz upload para GitHub (Contents API), gera URL raw pública e envia para GPT Maker.

Requisitos:
  pip install requests

Se quiser S3/Dropbox/Drive, dá pra adicionar depois, mas aqui focamos GitHub.
"""

import argparse
import base64
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import requests

API_TRAIN_URL_TEMPLATE = "https://api.gptmaker.ai/v2/agent/{agentId}/trainings"
RAW_URL_TEMPLATE = "https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"

MAX_GITHUB_FILE_MB = 100      # limite prático por arquivo sem LFS
MAX_GITHUB_BYTES = MAX_GITHUB_FILE_MB * 1024 * 1024
SLEEP_BETWEEN_CALLS = 0.3     # evitar rate limit

# ---------------------------- Util ----------------------------

def is_pdf(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() == ".pdf"

def list_pdfs_recursive(base: Path) -> List[Path]:
    if not base.exists():
        raise FileNotFoundError(f"Pasta não encontrada: {base}")
    return [p for p in base.rglob("*.pdf") if p.is_file()]

def to_posix_path(p: str) -> str:
    return p.replace("\\", "/").lstrip("/")

def human(ok: bool, msg: str) -> str:
    return f"{'✅' if ok else '❌'} {msg}"

def backoff_retry(tries=3, base=0.8):
    def deco(fn):
        def wrapper(*args, **kwargs):
            last_exc = None
            for i in range(1, tries + 1):
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    last_exc = e
                    if i < tries:
                        time.sleep(base * (2 ** (i - 1)))
                    else:
                        raise
            if last_exc:
                raise last_exc
        return wrapper
    return deco

# ----------------------- GitHub Uploader -----------------------

@dataclass
class GithubCfg:
    token: str
    owner: str
    repo: str
    branch: str
    folder_prefix: str  # prefixo dentro do repo (pode ser vazio)

class GitHubUpload:
    """
    Sobe arquivo via Contents API:
      PUT /repos/{owner}/{repo}/contents/{path}
    Preserva estrutura relativa a partir de pdf_dir.
    """
    def __init__(self, cfg: GithubCfg):
        if not cfg.token or not cfg.owner or not cfg.repo:
            raise ValueError("Faltam parâmetros do GitHub: token/owner/repo.")
        self.api = "https://api.github.com"
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {cfg.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"
        })
        self.cfg = cfg

    @backoff_retry(tries=3)
    def upload_bytes(self, content: bytes, repo_rel_path: str, message: str) -> None:
        url = f"{self.api}/repos/{self.cfg.owner}/{self.cfg.repo}/contents/{repo_rel_path}"
        payload = {
            "message": message,
            "content": base64.b64encode(content).decode("utf-8"),
            "branch": self.cfg.branch
        }
        r = self.session.put(url, json=payload, timeout=60)
        if r.status_code not in (200, 201):
            raise RuntimeError(f"Falha upload GitHub: {r.status_code} {r.text[:300]}")

    def dest_path(self, relative_posix: str) -> str:
        # prefixo opcional dentro do repo + caminho relativo POSIX
        prefix = to_posix_path(self.cfg.folder_prefix or "")
        return to_posix_path(f"{prefix}/{relative_posix}") if prefix else relative_posix

    def raw_url(self, repo_rel_path: str) -> str:
        return RAW_URL_TEMPLATE.format(
            owner=self.cfg.owner,
            repo=self.cfg.repo,
            branch=self.cfg.branch,
            path=repo_rel_path
        )

# ------------------ GPT Maker Client ------------------

class GPTMakerClient:
    def __init__(self, agent_id: str, token: str):
        self.train_url = API_TRAIN_URL_TEMPLATE.format(agentId=agent_id)
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        })

    @backoff_retry(tries=3)
    def send_document(self, url: str, name: str) -> Tuple[bool, int, str]:
        payload = {
            "type": "DOCUMENT",
            "documentUrl": url,
            "documentName": name,
            "documentMimetype": "application/pdf"
        }
        r = self.session.post(self.train_url, data=json.dumps(payload), timeout=60)
        ok = 200 <= r.status_code < 300
        msg = ""
        try:
            data = r.json()
            msg = data.get("message") or data.get("status") or ""
        except Exception:
            msg = r.text[:300]
        return ok, r.status_code, msg

# ---------------------------- Main ----------------------------

def main():
    parser = argparse.ArgumentParser(description="Upload de PDFs p/ GitHub (preservando pastas) e envio p/ GPT Maker.")
    # GPT Maker
    parser.add_argument("--agent-id", required=True, help="ID do agente GPT Maker.")
    parser.add_argument("--token", required=True, help="Bearer token do GPT Maker.")
    # Origem local
    parser.add_argument("--pdf-dir", type=Path, required=True, help="Pasta raiz local (será percorrida recursivamente).")
    # GitHub
    parser.add_argument("--gh-token", required=True, help="GitHub Personal Access Token.")
    parser.add_argument("--gh-owner", required=True, help="Ex.: Jefeundertaker")
    parser.add_argument("--gh-repo",  required=True, help="Ex.: pdfs-tdn (precisa existir e ser público).")
    parser.add_argument("--gh-branch", default="main")
    parser.add_argument("--gh-folder", default="", help="Pasta base dentro do repo (opcional).")
    # Execução
    parser.add_argument("--dry-run", action="store_true", help="Simula sem enviar nada para GPT Maker.")
    args = parser.parse_args()

    base_dir = args.pdf_dir.resolve()
    pdfs = list_pdfs_recursive(base_dir)
    if not pdfs:
        print("Nenhum PDF encontrado.")
        sys.exit(0)

    gh = GitHubUpload(GithubCfg(
        token=args.gh_token,
        owner=args.gh_owner,
        repo=args.gh_repo,
        branch=args.gh_branch,
        folder_prefix=args.gh_folder
    ))
    gpt = GPTMakerClient(agent_id=args.agent_id, token=args.token)

    print(f"Encontrados {len(pdfs)} PDFs em {base_dir}")
    ok_count = 0
    err_count = 0
    failures = []

    for path in pdfs:
        try:
            size = path.stat().st_size
            if size > MAX_GITHUB_BYTES:
                msg = f"{path.name} excede {MAX_GITHUB_FILE_MB}MB ({size/1024/1024:.1f}MB) — pulei"
                print(human(False, msg))
                err_count += 1
                failures.append((path, "grande demais"))
                continue

            # caminho relativo (preserva estrutura)
            rel = path.relative_to(base_dir)
            rel_posix = to_posix_path(str(rel))
            repo_rel_path = gh.dest_path(rel_posix)

            # upload para GitHub
            with path.open("rb") as f:
                content = f.read()
            gh.upload_bytes(content, repo_rel_path, message=f"Add {rel_posix} (upload automático)")

            raw_url = gh.raw_url(repo_rel_path)

            if args.dry_run:
                print(human(True, f"[DRY-RUN] Subido e gerado URL: {rel_posix} -> {raw_url}"))
                ok_count += 1
                time.sleep(SLEEP_BETWEEN_CALLS)
                continue

            # envia para GPT Maker
            ok, status, msg = gpt.send_document(url=raw_url, name=rel.name)
            if ok:
                print(human(True, f"{rel_posix} | status={status} {msg}".strip()))
                ok_count += 1
            else:
                print(human(False, f"{rel_posix} | status={status} {msg}".strip()))
                err_count += 1
                failures.append((path, f"status={status} {msg}"))

            time.sleep(SLEEP_BETWEEN_CALLS)

        except Exception as e:
            print(human(False, f"{path} | exceção: {e}"))
            err_count += 1
            failures.append((path, str(e)))

    print("\n===== RELATÓRIO FINAL =====")
    print(f"Sucesso: {ok_count}")
    print(f"Erros:   {err_count}")
    if failures:
        print("\nFalhas:")
        for p, m in failures:
            print(f" - {p} -> {m}")
    print("===========================")

if __name__ == "__main__":
    main()
