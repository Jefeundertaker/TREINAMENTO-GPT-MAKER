# -*- coding: utf-8 -*-
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
import requests, re, csv, time, sys, json
from urllib.parse import urlsplit, parse_qs, urlunsplit, urlencode

# ============= CONFIG =============
SEED_URL   = "https://tdn.totvs.com.br/pages/releaseview.action?pageId=224116750"
OUT_BASE   = Path("PDFs_TDN")
HEADLESS   = True
PRINT_BG   = True          # imprimir com fundos (igual ao site)
RATE_SLEEP = 0.15          # pausa leve entre chamadas à API
SCROLL_STEPS = 80          # para páginas muito longas, aumente
SCROLL_WAIT  = 200
# =================================

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA, "Accept": "application/json"})

def limpar(txt: str) -> str:
    if not txt: return ""
    txt = re.sub(r"\s+", " ", txt.strip()).replace("\u00A0"," ")
    return txt[:150] or "Sem Título"

def base_url(seed: str) -> str:
    u = urlsplit(seed)
    return f"{u.scheme}://{u.netloc}"

def get_page_id(seed: str) -> str:
    u = urlsplit(seed); qs = dict(parse_qs(u.query))
    pid = qs.get("pageId") or qs.get("pagedId")
    if pid: return pid[0]
    m = re.search(r"pageId=(\d+)", seed)
    if m: return m.group(1)
    raise ValueError("Não consegui identificar pageId/pagedId no link fornecido.")

def norm_url(u: str) -> str:
    p = urlsplit(u)
    qs = [(k,v) for (k,v) in parse_qs(p.query, keep_blank_values=True).items()
          if k.lower() not in {"utm_source","utm_medium","utm_campaign","utm_term","utm_content"}]
    # parse_qs devolve listas; achata
    qs_flat = []
    for k,vals in qs: 
        for v in vals: qs_flat.append((k,v))
    return urlunsplit((p.scheme,p.netloc,p.path, urlencode(qs_flat), ""))

def api_get(url: str):
    r = SESSION.get(url, timeout=60)
    if r.status_code in (401,403):
        raise PermissionError(f"Sem acesso à API pública do TDN nesta área. HTTP {r.status_code} - {url}")
    r.raise_for_status()
    time.sleep(RATE_SLEEP)
    return r.json()

def get_root_info(root_id: str, root: str):
    url = f"{root}/rest/api/content/{root_id}?expand=ancestors,space"
    j = api_get(url)
    title = j.get("title","")
    anc   = j.get("ancestors",[]) or []
    ancestors = [{"id": a["id"], "title": a.get("title","")} for a in anc]
    return title, ancestors

def list_descendants(root_id: str, root: str):
    # paginação
    results = []
    url = f"{root}/rest/api/content/{root_id}/descendant/page?limit=200&expand="
    while url:
        j = api_get(url)
        for it in j.get("results", []):
            results.append({"id": it["id"], "title": it.get("title","")})
        # link next
        next_rel = j.get("_links", {}).get("next")
        if next_rel:
            if next_rel.startswith("http"):
                url = next_rel
            else:
                url = root + next_rel
        else:
            url = None
    return results

def get_ancestors_for(page_id: str, root: str):
    url = f"{root}/rest/api/content/{page_id}?expand=ancestors"
    j = api_get(url)
    anc = j.get("ancestors",[]) or []
    return [{"id": a["id"], "title": a.get("title","")} for a in anc]

def build_path_for(page_id: str, root_id: str, root: str):
    # monta caminho relativo ao root_id
    anc = get_ancestors_for(page_id, root)
    # corta tudo antes do root_id
    path = []
    found = False
    for a in anc:
        if a["id"] == root_id:
            found = True
            break
    if found:
        # pega somente os que vêm DEPOIS do root_id
        take = False
        for a in anc:
            if take:
                path.append(limpar(a["title"]))
            if a["id"] == root_id:
                take = True
    else:
        # se o root não estiver nos ancestrais (raro), usa todos
        path = [limpar(a["title"]) for a in anc]
    return path

def rolar_ate_fim(page):
    last = 0
    for _ in range(SCROLL_STEPS):
        try:
            page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
            page.wait_for_timeout(SCROLL_WAIT)
            h = page.evaluate("document.body.scrollHeight")
            if h == last: break
            last = h
        except: break

def titulo_real(page) -> str:
    try:
        t = page.title()
        t = re.sub(r"^(TOTVS\s*[\|\-]\s*)", "", t, flags=re.I)
        return limpar(t) or "pagina"
    except: return "pagina"

def salvar_pdf(page, url, destino: Path):
    page.goto(url, wait_until="domcontentloaded", timeout=120_000)
    page.wait_for_timeout(600)
    rolar_ate_fim(page)
    page.pdf(path=str(destino), format="A4", print_background=PRINT_BG)

def main():
    seed = SEED_URL if len(sys.argv)==1 else sys.argv[1]
    root  = base_url(seed)
    root_id = get_page_id(seed)

    OUT_BASE.mkdir(parents=True, exist_ok=True)
    log_path    = OUT_BASE / "log.csv"
    status_path = OUT_BASE / "status.json"
    links_csv   = OUT_BASE / "links_tree.csv"
    novo_log = not log_path.exists()
    flog = log_path.open("a", encoding="utf-8", newline="")
    wlog = csv.writer(flog)
    if novo_log:
        wlog.writerow(["path","title_hint","url","pdf","status","erro"])

    # 1) informações do nó raiz
    root_title, root_anc = get_root_info(root_id, root)
    print(f"Raiz: {root_title} (id={root_id})")

    # 2) lista todos os descendentes (recursivo) via REST
    desc = list_descendants(root_id, root)
    print(f"Descendentes encontrados via REST: {len(desc)}")

    # 3) constrói path completo relativo ao root e monta tabela
    rows = []
    for i, d in enumerate(desc, start=1):
        pid = d["id"]
        path = build_path_for(pid, root_id, root)  # tudo acima do nó (até root)
        title = limpar(d["title"])
        url = f"{root}/pages/releaseview.action?pageId={pid}"
        full_path = path + [title]  # path completo
        rows.append({"path": full_path, "title": title, "url": norm_url(url)})
        if i % 50 == 0:
            print(f"… {i}/{len(desc)} estruturados")

    # 4) salva links_tree.csv
    with links_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f); w.writerow(["path","title","url"])
        for r in rows:
            w.writerow([" / ".join(r["path"]), r["title"], r["url"]])
    print(f"Mapa salvo em: {links_csv}")

    # 5) baixa PDFs mantendo a mesma árvore de pastas
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=HEADLESS)
        ctx = browser.new_context(locale="pt-BR", viewport={"width":1400,"height":900})
        page = ctx.new_page(); page.set_default_timeout(90_000)

        total = len(rows); start = time.time()
        for i, r in enumerate(rows, start=1):
            segs = [s for s in r["path"][:-1]] or ["Outros"]
            pasta = OUT_BASE.joinpath(*segs); pasta.mkdir(parents=True, exist_ok=True)

            # tenta pegar título real da página (às vezes difere do title da API por prefixos)
            try:
                page.goto(r["url"], wait_until="domcontentloaded", timeout=120_000)
                page.wait_for_timeout(600); rolar_ate_fim(page)
                tit = titulo_real(page)
            except PWTimeout:
                tit = r["title"] or "pagina"

            nome = re.sub(r'[\\/*?:"<>|]+', " ", f"{tit}.pdf").strip() or "pagina.pdf"
            destino = pasta / nome

            if destino.exists():
                wlog.writerow([" / ".join(r["path"]), r["title"], r["url"], str(destino), "SKIP", ""]); flog.flush()
            else:
                ok=False; err=""
                for tent in range(3):
                    try:
                        salvar_pdf(page, r["url"], destino)
                        ok=True; break
                    except Exception as e:
                        err=str(e); time.sleep(0.8*(tent+1))
                if ok:
                    wlog.writerow([" / ".join(r["path"]), r["title"], r["url"], str(destino), "OK", ""])
                else:
                    wlog.writerow([" / ".join(r["path"]), r["title"], r["url"], "", "ERRO", err])
                flog.flush()

            elapsed = time.time()-start
            rate = (i/elapsed*60) if elapsed>0 else 0.0
            rem  = int((total-i)/rate*60) if rate>0 else 0
            eta  = f"{rem//60:02d}:{rem%60:02d}"
            status_path.write_text(json.dumps({
                "total": total, "done": i, "last": str(destino),
                "rate_pages_per_min": round(rate,1), "eta": eta
            }, ensure_ascii=False), encoding="utf-8")
            print(f"[{i}/{total}] -> {destino.name} | {rate:.1f} pág/min | ETA {eta}", flush=True)

        ctx.close(); browser.close()

    flog.close()
    print(f"\n✅ PDFs salvos em: {OUT_BASE.resolve()}\n   - log: {log_path}\n   - mapa: {links_csv}")

if __name__ == "__main__":
    main()
