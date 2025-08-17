
# -*- coding: utf-8 -*-
"""
resolver_links_tdn_v2.py
- Mostra progresso em tempo real (1 linha por item)
- Timeout + retries nas chamadas
- Log em arquivo: debug_resolver.log
- Salva parcial mesmo se interromper (CTRL+C)
"""

from pathlib import Path
import re, time, sys, json, datetime, traceback
import requests
from urllib.parse import quote, urlencode, urlsplit, parse_qs

TDN_ROOT = "https://tdn.totvs.com.br"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept": "application/json"})

# Tenta global (None) e em alguns espaços comuns; ajuste se souber a sigla certa
SPACES_TRY = [None, "LDT", "LDS", "LFW", "LDP"]

CONNECT_TIMEOUT = 10
READ_TIMEOUT = 25
RETRIES = 3
SLEEP_BETWEEN = 0.15

LOG = Path("debug_resolver.log")

def log(msg: str):
    line = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def limpar(s: str) -> str:
    if not s: return ""
    return re.sub(r"\s+", " ", s.strip())

def is_section(line: str) -> bool:
    if re.search(r"\b(?:CPR?\d{3,4}|CPAPI\d+[A-Z]?|BOIN\d+|DMCP0*\d+|FF_[A-Za-z0-9_]+)\b", line, re.I):
        return False
    return True

def cql_escape(s: str) -> str:
    return s.replace('"','\\"')

def api_get(url: str):
    last_exc = None
    for t in range(1, RETRIES+1):
        try:
            r = S.get(url, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT))
            if r.status_code in (401,403):
                log(f"HTTP {r.status_code} para {url}")
                return None
            if r.status_code >= 400:
                log(f"HTTP {r.status_code} para {url}")
                last_exc = Exception(f"HTTP {r.status_code}")
            else:
                try:
                    j = r.json()
                except Exception as e:
                    last_exc = e
                else:
                    time.sleep(SLEEP_BETWEEN)
                    return j
        except Exception as e:
            last_exc = e
        time.sleep(0.5 * t)
    log(f"Falha em api_get após {RETRIES} tentativas: {url} | {last_exc}")
    return None

def busca_por_titulo(title: str):
    title_q = quote(title)
    # 1) match exato por /content?title=...
    for sk in SPACES_TRY:
        url = f"{TDN_ROOT}/rest/api/content?title={title_q}"
        if sk: url += f"&spaceKey={quote(sk)}"
        j = api_get(url)
        if j and j.get("results"):
            for it in j["results"]:
                if it.get("type") == "page":
                    return f"{TDN_ROOT}/pages/releaseview.action?pageId={it['id']}"
    # 2) busca por código se existir na string (melhor precisão)
    m = re.search(r"\b(CP(?:R)?\d{3,4}|CPAPI\d+[A-Z]?|BOIN\d+|DMCP0*\d+|FF_[A-Za-z0-9_]+)\b", title, re.I)
    code = m.group(1) if m else None
    if code:
        for sk in SPACES_TRY:
            cql = f'type=page and (title ~ "{cql_escape(code)}" or text ~ "{cql_escape(code)}")'
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
    # 3) busca CQL por título aproximado
    for sk in SPACES_TRY:
        cql = f'type=page and (title ~ "{cql_escape(title)}")'
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
    out_lines = []
    current_section = ""
    total = len(lines)
    log(f"Iniciando. Linhas: {total}")
    try:
        for idx, ln in enumerate(lines, start=1):
            if is_section(ln):
                current_section = ln
                out_lines.append(current_section)
                log(f"[{idx}/{total}] Seção: {ln}")
            else:
                log(f"[{idx}/{total}] Buscando: {ln}")
                url = busca_por_titulo(ln)
                if url:
                    out_lines.append(f" - {ln} :: {url}")
                    log(f"[{idx}/{total}] OK -> {url}")
                else:
                    out_lines.append(f" - {ln} :: (NÃO ENCONTRADO)")
                    log(f"[{idx}/{total}] NÃO ENCONTRADO")
    except KeyboardInterrupt:
        log("Interrompido pelo usuário. Salvando parcial...")
    except Exception as e:
        log("Erro inesperado: " + repr(e))
        log(traceback.format_exc())

    Path("links_organizados.txt").write_text("\n".join(out_lines), encoding="utf-8")
    log("✅ Gerado links_organizados.txt")
    print("\nConcluído. Veja links_organizados.txt e debug_resolver.log")

if __name__ == "__main__":
    main()
