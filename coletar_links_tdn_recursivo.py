# -*- coding: utf-8 -*-
from pathlib import Path
from collections import deque
from playwright.sync_api import sync_playwright
import urllib.parse as up
import csv, re, html, time, sys, json

# >>> COLOQUE AQUI A PÁGINA-ÍNDICE (a do print)
SEED_URL = "https://tdn.totvs.com.br/display/public/LDT/MCF+-+Configurador+de+Produtos"

HEADLESS = True           # Coloque False para ver a janela
DOMINIO = "tdn.totvs.com.br"
MAX_DEPTH = 3             # Níveis de recursão em /display/... (aumente se precisar)
WAIT_MS = 600             # pausas entre ações
SCROLL_STEPS = 60
SCROLL_WAIT_MS = 250

PADROES_OK = [
    re.compile(r"^/pages/releaseview\.action\?pageId=\d+$"),  # páginas de conteúdo
    re.compile(r"^/display/[^/].+"),                          # páginas índice/secões
]
PADROES_SKIP = [
    re.compile(r"^#"),
    re.compile(r"^mailto:", re.I),
    re.compile(r"\.(png|jpe?g|gif|svg|zip|pdf|mp4|webm)(\?.*)?$", re.I),
    re.compile(r"/download/"),
]

def normalizar(url: str) -> str:
    u = up.urlsplit(html.unescape(url))
    qs = up.parse_qsl(u.query, keep_blank_values=True)
    # remove utms e afins
    qs = [(k, v) for (k, v) in qs if k.lower() not in {
        "utm_source","utm_medium","utm_campaign","utm_term","utm_content"}]
    return up.urlunsplit((u.scheme, u.netloc, u.path, up.urlencode(qs), ""))

def eh_do_tdn(url: str) -> bool:
    try:
        return up.urlsplit(url).netloc.endswith(DOMINIO)
    except Exception:
        return False

def passa_filtro(path: str) -> bool:
    if any(p.search(path) for p in PADROES_SKIP):
        return False
    return any(p.search(path) for p in PADROES_OK)

def limpar_nome(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r'[\\/*?:"<>|]+', " ", s)
    s = re.sub(r"\s{2,}", " ", s)
    return s[:120] or "Sem Título"

def expandir_tudo_context(ctx):
    # abre <details>
    try:
        ctx.evaluate("""() => { for (const d of document.querySelectorAll('details')) d.open = true; }""")
    except: pass
    seletores = [
        'button[aria-expanded="false"]',
        '[role="button"][aria-expanded="false"]',
        'a[aria-expanded="false"]',
        'button:has-text("Expandir")',
        'a:has-text("Expandir")',
        '.plugin_pagetree_expand_all',
        '.expand-control',
        '.aui-button[aria-expanded="false"]',
        '.pagetree-toggle',
        '.plugin_pagetree_child_toggle',
    ]
    for _ in range(8):
        clicou = False
        for sel in seletores:
            try:
                loc = ctx.locator(sel)
                n = loc.count()
            except:
                n = 0
            for i in range(n):
                try:
                    loc.nth(i).click(force=True, timeout=500)
                    clicou = True
                except:
                    pass
        ctx.wait_for_timeout(WAIT_MS)
        if not clicou: break

def rolar_ate_fim(ctx):
    last_h = 0
    for _ in range(SCROLL_STEPS):
        try:
            ctx.evaluate("window.scrollBy(0, document.body.scrollHeight);")
            ctx.wait_for_timeout(SCROLL_WAIT_MS)
            h = ctx.evaluate("document.body.scrollHeight")
            if h == last_h:
                break
            last_h = h
        except:
            break

def coletar_anchors_ctx(ctx):
    pares = []
    try:
        pares = ctx.eval_on_selector_all(
            "a[href]",
            "els => els.map(a => [a.href, (a.textContent||'').trim()])"
        )
    except: pass
    out = []
    vistos = set()
    for href, txt in pares:
        url = normalizar(href)
        if not eh_do_tdn(url): 
            continue
        path = up.urlsplit(url).path
        if not passa_filtro(path):
            continue
        if url in vistos: 
            continue
        vistos.add(url)
        out.append((url, txt))
    return out

def breadcrumbs_ctx(ctx):
    # tenta vários seletores comuns do Confluence
    sels = [
        'nav[aria-label="breadcrumbs"]',
        '.breadcrumbs',
        '.aui-nav-breadcrumbs',
    ]
    for sel in sels:
        try:
            arr = ctx.eval_on_selector_all(sel + " a, " + sel + " span", 
                "els => els.map(e => (e.textContent||'').trim()).filter(Boolean)")
            if arr:
                # remove genéricos
                arr = [x for x in arr if x not in ("Páginas", "Pages", "…", "...")]
                return arr
        except:
            pass
    return []

def coletar_em_pagina(page, url):
    """Coleta (links, seção) na página atual + iframes"""
    expandir_tudo_context(page)
    rolar_ate_fim(page)
    expandir_tudo_context(page)

    # breadcrumbs -> seção
    bc = breadcrumbs_ctx(page)
    if len(bc) >= 1:
        # use últimos 1-2 níveis como “seção”
        sec = " / ".join(bc[-2:]) if len(bc) >= 2 else bc[-1]
    else:
        try:
            h1 = page.text_content("h1")
            sec = limpar_nome(h1) if h1 else "Outros"
        except:
            sec = "Outros"
    sec = limpar_nome(sec)

    links = coletar_anchors_ctx(page)

    # também coleta de iframes
    try:
        for fr in page.frames:
            if fr == page.main_frame: 
                continue
            try:
                expandir_tudo_context(fr)
                rolar_ate_fim(fr)
                links += coletar_anchors_ctx(fr)
            except:
                pass
    except:
        pass

    return sec, links

def main():
    out_txt  = Path("links.txt")
    out_csv  = Path("links.csv")
    cache    = Path(".visited.json")

    seed = SEED_URL
    if len(sys.argv) > 1:
        seed = sys.argv[1]

    # cache de visitados para retomar
    visited = set()
    if cache.exists():
        try:
            visited = set(json.loads(cache.read_text(encoding="utf-8")))
        except:
            visited = set()

    fila = deque([(seed, 0)])
    resultados = []  # dicts: {section, title_hint, url}
    vistos_links = set()  # para dedupe de saída

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        ctx = browser.new_context(locale="pt-BR")
        page = ctx.new_page()
        page.set_default_timeout(90_000)

        while fila:
            url, depth = fila.popleft()
            if url in visited:
                continue
            visited.add(url)
            cache.write_text(json.dumps(list(visited)), encoding="utf-8")

            try:
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(WAIT_MS)
            except Exception as e:
                print(f"[ERRO] não abriu: {url} | {e}")
                continue

            sec, links = coletar_em_pagina(page, url)
            # registra links desta página
            for u, txt in links:
                if u in vistos_links:
                    continue
                vistos_links.add(u)
                title_hint = limpar_nome(txt) or "Sem Título"
                resultados.append({"section": sec, "title_hint": title_hint, "url": u})

                # se for página índice /display/... e ainda dentro do limite, enfileira pra visitar
                path = up.urlsplit(u).path
                if depth < MAX_DEPTH and path.startswith("/display/"):
                    fila.append((u, depth + 1))

        ctx.close()
        browser.close()

    # salva saídas
    with out_txt.open("w", encoding="utf-8") as f:
        for r in resultados:
            f.write(r["url"] + "\n")

    with out_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["section","title_hint","url"])
        w.writeheader()
        for r in resultados:
            w.writerow(r)

    print(f"✅ Coletados {len(resultados)} links.")
    print(f"   - {out_txt}")
    print(f"   - {out_csv}")
    print("Dica: se achar que ainda faltou algo, aumente MAX_DEPTH ou rode com HEADLESS=False para inspecionar a página.")
    
if __name__ == "__main__":
    main()
