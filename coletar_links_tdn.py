import re
import csv
import time
import html
import urllib.parse as up
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# >>> COLOQUE AQUI O LINK DA PÁGINA DO PRINT (página-índice) <<<
SEED_URL = "https://tdn.totvs.com.br/display/public/LDT/MCF+-+Configurador+de+Produtos"

DOMINIO = "tdn.totvs.com.br"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# Padrões de links que queremos (Confluence/TDN)
PADROES_OK = [
    re.compile(r"^/pages/releaseview\.action\?pageId=\d+$"),
    re.compile(r"^/display/[^/].+"),   # páginas (índices, how-to, etc.)
]

# Padrões a ignorar
PADROES_SKIP = [
    re.compile(r"^#"),
    re.compile(r"^mailto:", re.I),
    re.compile(r"\.(png|jpe?g|gif|svg|zip|pdf)(\?.*)?$", re.I),
    re.compile(r"/download/"),  # anexos diretos
]

def absoluto(url_base: str, href: str) -> str:
    return up.urljoin(url_base, href)

def normalizar(url: str) -> str:
    # Remove fragmentos (#...) e decodifica html entities
    u = up.urlsplit(html.unescape(url))
    # limpa tracking comum
    qs = up.parse_qsl(u.query, keep_blank_values=True)
    qs_limpos = [(k, v) for (k, v) in qs if k.lower() not in {"utm_source","utm_medium","utm_campaign","utm_term","utm_content"}]
    query = up.urlencode(qs_limpos)
    return up.urlunsplit((u.scheme, u.netloc, u.path, query, ""))

def eh_do_tdn(url: str) -> bool:
    try:
        return up.urlsplit(url).netloc.endswith(DOMINIO)
    except Exception:
        return False

def passa_filtro(path: str) -> bool:
    if any(p.search(path) for p in PADROES_SKIP):
        return False
    return any(p.search(path) for p in PADROES_OK)

def coletar_links(seed: str):
    print(f"Coletando links em: {seed}")
    headers = {"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9"}
    r = requests.get(seed, headers=headers, timeout=60)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    soup = BeautifulSoup(r.text, "html.parser")

    links = []
    for a in soup.find_all("a", href=True):
        href = a.get("href").strip()
        url_abs = absoluto(seed, href)
        url_norm = normalizar(url_abs)

        if not eh_do_tdn(url_norm):
            continue

        path = up.urlsplit(url_norm).path
        if passa_filtro(path):
            text = a.get_text(strip=True)
            links.append((url_norm, text))

    # dedupe preservando ordem
    seen = set()
    uniq = []
    for url, txt in links:
        if url not in seen:
            uniq.append((url, txt))
            seen.add(url)

    print(f"Encontrados {len(uniq)} links após filtros.")
    return uniq

def salvar_saidas(pares, pasta_out: Path):
    pasta_out.mkdir(parents=True, exist_ok=True)

    # links.txt
    txt_path = pasta_out / "links.txt"
    with txt_path.open("w", encoding="utf-8") as f:
        for url, _ in pares:
            f.write(url + "\n")

    # links.csv (url, text)
    csv_path = pasta_out / "links.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["url", "texto_ancora"])
        for url, txt in pares:
            w.writerow([url, txt])

    print(f"✅ Gerados:\n - {txt_path}\n - {csv_path}")
    return txt_path, csv_path

def main():
    pares = coletar_links(SEED_URL)
    salvar_saidas(pares, Path("."))

if __name__ == "__main__":
    main()
