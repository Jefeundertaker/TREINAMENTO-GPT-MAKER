
# -*- coding: utf-8 -*-
from pathlib import Path
import re, time, sys, json
import requests
from urllib.parse import quote, urlsplit, parse_qs

TDN_ROOT = "https://tdn.totvs.com.br"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept": "application/json"})

SPACES_TRY = [None, "LDT"]  # tente outros se necessário, ex.: "LDS"

def limpar(s: str) -> str:
    if not s: return ""
    return re.sub(r"\s+", " ", s.strip())

def is_section(line: str) -> bool:
    # seção = linha sem código tipo CPxxxx/CPAPIxxx/BOINxxx/DMCPxxxx
    if re.search(r"\b(?:CPR?\d{3,4}|CPAPI\d+[A-Z]?|BOIN\d+|DMCP0*\d+|FF_[A-Za-z0-9_]+)\b", line, re.I):
        return False
    return True

def cql_escape(s: str) -> str:
    return s.replace('"','\\"')

def api_get(url: str):
    r = S.get(url, timeout=60)
    if r.status_code in (401,403):
        return None
    if r.status_code >= 400:
        return None
    try:
        j = r.json()
    except Exception:
        return None
    time.sleep(0.12)
    return j

def busca_por_titulo(title: str):
    # 1) match exato por /content?title=...
    for sk in SPACES_TRY:
        url = f"{TDN_ROOT}/rest/api/content?title={quote(title)}"
        if sk: url += f"&spaceKey={quote(sk)}"
        j = api_get(url)
        if j and j.get("results"):
            for it in j["results"]:
                if it.get("type") == "page":
                    return f"{TDN_ROOT}/pages/releaseview.action?pageId={it['id']}"
    # 2) busca CQL por título aproximado
    clauses = [f'type=page', f'(title ~ "{cql_escape(title)}")']
    for sk in SPACES_TRY:
        cql = " and ".join(clauses)
        if sk: cql = f"space = {sk} and " + cql
        url = f"{TDN_ROOT}/rest/api/search?cql={quote(cql)}&limit=10"
        j = api_get(url)
        if not j: continue
        for res in j.get("results", []):
            c = res.get("content", {})
            if c.get("type") != "page": continue
            cid = c.get("id")
            if cid:
                return f"{TDN_ROOT}/pages/releaseview.action?pageId={cid}"
    return ""

def main():
    tit_path = Path("titulos.txt")
    if not tit_path.exists():
        print("titulos.txt não encontrado")
        sys.exit(1)
    lines = [ln.strip() for ln in tit_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    out = []
    current_section = ""
    for ln in lines:
        if is_section(ln):
            current_section = ln
            out.append(current_section)
        else:
            url = busca_por_titulo(ln)
            if url:
                out.append(f" - {ln} :: {url}")
            else:
                out.append(f" - {ln} :: (NÃO ENCONTRADO)")
    Path("links_organizados.txt").write_text("\n".join(out), encoding="utf-8")
    print("✅ Gerado links_organizados.txt")

if __name__ == "__main__":
    main()
