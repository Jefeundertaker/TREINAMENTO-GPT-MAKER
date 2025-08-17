
# -*- coding: utf-8 -*-
"""
resolver_links_tdn_mcs.py
- Lê titulos_mcs.txt (ou titulos.txt)
- Mantém a hierarquia (cada linha de seção permanece)
- Para cada item, resolve -> URL e escreve " - <Título> :: <URL>"
- Mostra progresso, faz retries, timeout, salva parcial.
- Tenta Confluence REST primeiro; se falhar, usa busca HTML do TDN.
"""

from pathlib import Path
import re, time, sys, datetime, traceback
import requests
from urllib.parse import quote, urlencode
from bs4 import BeautifulSoup

TDN_ROOT = "https://tdn.totvs.com.br"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
S = requests.Session()
S.headers.update({"User-Agent": UA})

SPACES_TRY = [None, "LDT", "LDS", "LFW", "LDP"]
CONNECT_TIMEOUT = 10
READ_TIMEOUT = 25
RETRIES = 3
SLEEP_BETWEEN = 0.15

LOG = Path("debug_resolver_mcs.log")

def log(msg: str):
    line = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def is_section(line: str) -> bool:
    # Se tem código típico (CS, CSR, CDR, rp*, etc.), é item
    if re.search(r"\b(?:CSR?\d{3,4}[A-Z]?|CS0?\d{3,4}[A-Z]?|CDR\d+[A-Z]?|rp[A-Za-z0-9]+|sv[A-Za-z0-9]+|html\.[\w\.]+|costscockpit|comparativeRealStandard|ggfByCostCenter)\b", line, re.I):
        return False
    # Senão, tratamos como seção
    return True

def cql_escape(s: str) -> str:
    return s.replace('"','\\"')

def api_get(url: str):
    last_exc = None
    for t in range(1, RETRIES+1):
        try:
            r = S.get(url, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT), headers={"Accept": "application/json"})
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
        time.sleep(0.4 * t)
    log(f"Falha em api_get após {RETRIES} tentativas: {url} | {last_exc}")
    return None

def rest_by_title_exact(title: str):
    title_q = quote(title)
    for sk in SPACES_TRY:
        url = f"{TDN_ROOT}/rest/api/content?title={title_q}"
        if sk: url += f"&spaceKey={quote(sk)}"
        j = api_get(url)
        if j and j.get("results"):
            for it in j["results"]:
                if it.get("type") == "page":
                    return f"{TDN_ROOT}/pages/releaseview.action?pageId={it['id']}"
    return ""

def rest_by_code_or_title(title: str):
    # tenta por código (mais preciso)
    m = re.search(r"\b(CS(?:R)?\d{3,4}[A-Z]?|CDR\d+[A-Z]?|rp[A-Za-z0-9]+|sv[A-Za-z0-9]+|html\.[\w\.]+|costscockpit|comparativeRealStandard|ggfByCostCenter)\b", title, re.I)
    code = m.group(1) if m else None
    queries = []
    if code:
        queries.append(code)
    # pedaços relevantes do título (sem sinais)
    key = re.sub(r"[^A-Za-z0-9À-ÿ ]+", " ", title)
    key = re.sub(r"\s+", " ", key).strip()
    if key:
        queries.append(key)

    for q in queries:
        for sk in SPACES_TRY:
            cql = f'type=page and (title ~ "{cql_escape(q)}" or text ~ "{cql_escape(q)}")'
            if sk: cql = f"space = {sk} and " + cql
            url = f"{TDN_ROOT}/rest/api/search?cql={quote(cql)}&limit=10"
            j = api_get(url)
            if not j: 
                continue
            for res in j.get("results", []):
                c = res.get("content", {})
                if c.get("type") != "page": 
                    continue
                cid = c.get("id")
                if cid:
                    return f"{TDN_ROOT}/pages/releaseview.action?pageId={cid}"
    return ""

def html_search(title: str):
    # Busca HTML no "dosearchsite.action" do Confluence
    try:
        r = S.get(f"{TDN_ROOT}/dosearchsite.action", params={"queryString": title}, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT))
        if r.status_code != 200:
            return ""
        soup = BeautifulSoup(r.text, "html.parser")
        # pega primeiro resultado cujo texto se pareça com o título
        for a in soup.select("a[href]"):
            txt = (a.get_text() or "").strip()
            href = a.get("href") or ""
            if not href or not href.startswith("/"):
                continue
            if len(txt) < 3:
                continue
            # prioriza onde aparece código ou boa sobreposição
            if re.search(r"\b(CS(?:R)?\d{3,4}[A-Z]?|CDR\d+[A-Z]?|rp[A-Za-z0-9]+|sv[A-Za-z0-9]+)\b", txt, re.I) or title.lower() in txt.lower():
                return f"{TDN_ROOT}{href}"
    except Exception:
        return ""
    return ""

def resolver_link(title: str) -> str:
    # ordem: exato -> code/title via REST -> HTML search
    url = rest_by_title_exact(title)
    if url:
        return url
    url = rest_by_code_or_title(title)
    if url:
        return url
    url = html_search(title)
    return url or ""

def main():
    # entrada: titulos_mcs.txt (se não tiver, usa titulos.txt)
    in_path = Path("titulos_mcs.txt")
    if not in_path.exists():
        in_path = Path("titulos.txt")
    if not in_path.exists():
        print("Não encontrei 'titulos_mcs.txt' nem 'titulos.txt' na pasta atual.")
        sys.exit(1)

    lines = [ln.strip() for ln in in_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    out_path = Path("links_organizados.txt")
    out_lines = []
    total = len(lines)

    log(f"Iniciando resolução de {total} linhas a partir de {in_path.name}")
    try:
        for idx, ln in enumerate(lines, start=1):
            if is_section(ln):
                out_lines.append(ln)
                log(f"[{idx}/{total}] Seção: {ln}")
            else:
                log(f"[{idx}/{total}] Buscando: {ln}")
                url = resolver_link(ln)
                if url:
                    out_lines.append(f" - {ln} :: {url}")
                    log(f"[{idx}/{total}] OK -> {url}")
                else:
                    out_lines.append(f" - {ln} :: (NÃO ENCONTRADO)")
                    log(f"[{idx}/{total}] NÃO ENCONTRADO")
            # salva parcial a cada 5 linhas
            if idx % 5 == 0:
                out_path.write_text("\n".join(out_lines), encoding="utf-8")
    except KeyboardInterrupt:
        log("Interrompido pelo usuário. Salvando parcial...")
    except Exception as e:
        log("Erro inesperado: " + repr(e))
        log(traceback.format_exc())

    out_path.write_text("\n".join(out_lines), encoding="utf-8")
    log(f"✅ Finalizado. Arquivo gerado: {out_path}")

if __name__ == "__main__":
    main()
