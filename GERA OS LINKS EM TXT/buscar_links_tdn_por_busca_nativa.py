import argparse
import re
import time
import html
import unicodedata
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup
from rapidfuzz import fuzz, process

TDN_ROOT = "https://tdn.totvs.com.br"

HDRS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

CODE_RE = re.compile(r"\b([A-Z]{2,4}\d{3,4}[A-Z]?)\b", re.I)

def strip_accents(s: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))

def clean_title(s: str) -> str:
    s = s.strip()
    s = s.replace("–", "-").replace("—", "-")
    s = re.sub(r"\s+", " ", s)
    return s

def build_queries(title: str):
    """
    Retorna uma lista de queries (prioridade alta -> baixa)
    """
    t = clean_title(title)
    code = None
    m = CODE_RE.search(t)
    if m:
        code = m.group(1).upper()

    queries = []
    # 1) Se possui código, prioriza buscas só pelo código:
    if code:
        queries.append(code)
        queries.append(f"\"{code}\"")

    # 2) Título completo entre aspas (mais preciso)
    queries.append(f"\"{t}\"")

    # 3) Título sem acento/com pontuação reduzida
    t_na = strip_accents(t)
    if t_na.lower() != t.lower():
        queries.append(f"\"{t_na}\"")

    # 4) Heurística: se contém ' - CODE', montar "parte antes do código" + código
    if code:
        before = t.split(code)[0].strip(" -–—:;")
        if before:
            queries.append(f"\"{before}\" {code}")

    # 5) Versão enxuta (tira códigos, html.*, BO-, API-, etc.)
    t_nocode = CODE_RE.sub("", t).strip()
    t_nocode = re.sub(r"\b(html\.[\w.-]+|BO\s*-\s*|API\s*-\s*)", "", t_nocode, flags=re.I).strip("-–—: ")
    if t_nocode and t_nocode.lower() != t.lower():
        queries.append(f"\"{t_nocode}\"")

    # Mantém únicos na ordem
    seen = set()
    uniq = []
    for q in queries:
        if q not in seen:
            uniq.append(q)
            seen.add(q)
    return uniq, code

def confluence_site_search(query: str, session: requests.Session, max_results: int = 10):
    """
    Usa a busca pública do Confluence (TDN) para retornar resultados (título, url).
    """
    url = f"{TDN_ROOT}/dosearchsite.action?queryString={quote_plus(query)}"
    r = session.get(url, headers=HDRS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    results = []
    # Resultados em Confluence geralmente em .search-results .search-result
    for a in soup.select(".search-results .search-result a"):
        href = a.get("href", "")
        if not href:
            continue
        # Normaliza href relativo
        full = urljoin(TDN_ROOT, href)
        # Filtra áreas públicas mais comuns
        if not ("/pages/viewpage.action" in full or "/display/public/" in full or "/pages/releaseview.action" in full):
            continue
        title = a.get_text(strip=True)
        if title:
            results.append((title, full))
        if len(results) >= max_results:
            break
    return results

def score_result(title: str, code: str, cand_title: str) -> int:
    """
    Calcula um score pelo título e código (se tiver).
    """
    base = fuzz.WRatio(clean_title(title), clean_title(cand_title))
    if code and re.search(rf"\b{re.escape(code)}\b", cand_title, re.I):
        base += 10  # pequeno bônus por conter o código no título do resultado
    return base

def find_best_link_for_title(title: str, session: requests.Session):
    queries, code = build_queries(title)

    best = None  # (score, url, cand_title, used_query)
    for q in queries:
        try:
            results = confluence_site_search(q, session, max_results=12)
        except Exception as e:
            print(f"   ↳ erro busca [{q}]: {e}")
            continue

        # Rankeia localmente
        for cand_title, url in results:
            sc = score_result(title, code, cand_title)
            # Prioriza domínios/paths mais “oficiais”
            if "/display/public/" in url:
                sc += 3
            elif "/pages/viewpage.action" in url:
                sc += 2
            elif "/pages/releaseview.action" in url:
                sc += 1

            if (best is None) or (sc > best[0]):
                best = (sc, url, cand_title, q)

        # Se já achou algo muito alto, pode parar cedo
        if best and best[0] >= 90:
            break

        # Respiro curto para não chamar atenção (e não tomar 403)
        time.sleep(0.3)

    return best  # ou None

def main():
    ap = argparse.ArgumentParser(description="Busca links no TDN pela busca nativa do Confluence, priorizando TOTVS/Datasul/TDN.")
    ap.add_argument("--input", "-i", required=True, help="Arquivo de títulos (um por linha).")
    ap.add_argument("--out-found", default="links_restantes_encontrados.txt", help="Saída dos encontrados.")
    ap.add_argument("--out-missing", default="nao_encontrados_restantes.txt", help="Saída dos que ainda faltam.")
    ap.add_argument("--sleep", type=float, default=0.35, help="Intervalo entre buscas.")
    args = ap.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        titulos = [ln.strip() for ln in f if ln.strip()]

    print(f"📄 Títulos a buscar: {len(titulos)}")

    sess = requests.Session()
    encontrados = []
    faltando = []

    for idx, t in enumerate(titulos, 1):
        print(f"[{idx}/{len(titulos)}] 🔎 {t}")
        try:
            best = find_best_link_for_title(t, sess)
        except Exception as e:
            print(f"   ❌ erro inesperado: {e}")
            best = None

        if best:
            score, url, cand_title, used_q = best
            print(f"   ✅ {cand_title}  ->  {url}  (score {score}, query {used_q})")
            encontrados.append(f"{t} :: {url}")
        else:
            print(f"   ⚠️ não encontrado")
            faltando.append(t)

        time.sleep(args.sleep)

    with open(args.out_found, "w", encoding="utf-8") as f:
        f.write("\n".join(encontrados))

    with open(args.out_missing, "w", encoding="utf-8") as f:
        f.write("\n".join(faltando))

    print(f"\n🎯 Resultado: encontrados {len(encontrados)} | faltando {len(faltando)}")
    print(f"   → Salvo em: {args.out_found}")
    print(f"   → Restantes em: {args.out_missing}")

if __name__ == "__main__":
    main()
