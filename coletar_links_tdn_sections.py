# -*- coding: utf-8 -*-
from pathlib import Path
import csv
import re
import html
import sys
import urllib.parse as up
from playwright.sync_api import sync_playwright

# >>> COLE AQUI O LINK ÍNDICE
SEED_URL = "https://tdn.totvs.com.br/display/public/LDT/MCF+-+Configurador+de+Produtos"

HEADLESS = True   # coloque False para ver a janela
DOMINIO = "tdn.totvs.com.br"

# filtros
PADROES_OK = [
    re.compile(r"^/pages/releaseview\.action\?pageId=\d+$"),
    re.compile(r"^/display/[^/].+"),
]
PADROES_SKIP = [
    re.compile(r"^#"),
    re.compile(r"^mailto:", re.I),
    re.compile(r"\.(png|jpe?g|gif|svg|zip|pdf)(\?.*)?$", re.I),
    re.compile(r"/download/"),
]

def normalizar(url: str) -> str:
    u = up.urlsplit(html.unescape(url))
    qs = up.parse_qsl(u.query, keep_blank_values=True)
    qs_limpos = [(k, v) for (k, v) in qs if k.lower() not in {
        "utm_source","utm_medium","utm_campaign","utm_term","utm_content"}]
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

def limpar_nome(nome: str) -> str:
    nome = (nome or "").strip()
    nome = re.sub(r'[\\/*?:"<>|]+', " ", nome)
    nome = re.sub(r"\s{2,}", " ", nome)
    return nome[:120].strip() or "Sem Título"

def expandir_tudo(page):
    # abre <details>
    page.evaluate("""() => { for (const d of document.querySelectorAll('details')) d.open = true; }""")
    # tenta clicar em possíveis botões de expandir várias vezes
    seletores = [
        'button[aria-expanded="false"]',
        '[role="button"][aria-expanded="false"]',
        'a[aria-expanded="false"]',
        'button:has-text("Expandir")',
        'a:has-text("Expandir")',
        '.plugin_pagetree_expand_all',
        '.expand-control',
        '.aui-button[aria-expanded="false"]',
    ]
    for _ in range(5):
        clicou = False
        for sel in seletores:
            loc = page.locator(sel)
            try:
                count = loc.count()
            except:
                count = 0
            for i in range(count):
                try:
                    loc.nth(i).click(force=True, timeout=400)
                    clicou = True
                except:
                    pass
        page.wait_for_timeout(500)
        if not clicou:
            break

def rolar_ate_fim(page):
    last_h = 0
    for _ in range(40):
        page.evaluate("window.scrollBy(0, document.body.scrollHeight);")
        page.wait_for_timeout(250)
        h = page.evaluate("document.body.scrollHeight")
        if h == last_h:
            break
        last_h = h

def coletar_por_secao(page):
    """
    Estratégia:
      1) No conteúdo central, cada bloco de links costuma estar abaixo de um heading (h2/h3).
      2) Capturamos (Seção, [ (titulo_link, href) ... ]) percorrendo DOM.
    Se nada disso existir, caímos no 'coletar geral' (tudo em uma seção chamada 'Outros').
    """
    pares = page.eval_on_selector_all(
        "body",
        """(el) => {
            function txt(n){return (n && n.textContent || '').trim();}
            const out = [];
            // Procura headings relevantes e os links até o próximo heading do mesmo nível
            const headings = Array.from(document.querySelectorAll('h1, h2, h3, h4'));
            if (headings.length === 0) return out;

            for (let i=0;i<headings.length;i++){
                const h = headings[i];
                const sec = txt(h);
                let next = null;
                for (let j=i+1;j<headings.length;j++){
                    if (headings[j].tagName === h.tagName){ next = headings[j]; break; }
                }
                const links = [];
                let cur = h.nextElementSibling;
                while (cur && cur !== next){
                    links.push(...Array.from(cur.querySelectorAll('a[href]')).map(a => [txt(a), a.href]));
                    cur = cur.nextElementSibling;
                }
                if (links.length){
                    out.push([sec, links]);
                }
            }
            return out;
        }"""
    )
    # Se não achou seções, coleta geral
    if not pares:
        anchors = page.eval_on_selector_all("a[href]", "els => els.map(a => [ (a.textContent||'').trim(), a.href ])")
        return [("Outros", anchors)]
    return pares

def main():
    out_csv = Path("links.csv")
    out_txt  = Path("links.txt")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        ctx = browser.new_context(locale="pt-BR", user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"))
        page = ctx.new_page()
        page.set_default_timeout(60_000)
        page.goto(SEED_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(1200)

        expandir_tudo(page)
        rolar_ate_fim(page)
        expandir_tudo(page)

        blocos = coletar_por_secao(page)

        vistos = set()
        rows = []
        flat_urls = []

        for sec, links in blocos:
            sec_limpa = limpar_nome(sec)
            for (titulo, href) in links:
                url = normalizar(href)
                if not eh_do_tdn(url):
                    continue
                path = up.urlsplit(url).path
                if not passa_filtro(path):
                    continue
                if url in vistos:
                    continue
                vistos.add(url)
                titulo_limpo = limpar_nome(titulo) or "Sem Título"
                rows.append({"section": sec_limpa, "title_hint": titulo_limpo, "url": url})
                flat_urls.append(url)

        # salva incrementalmente
        with out_csv.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["section","title_hint","url"])
            w.writeheader()
            for r in rows:
                w.writerow(r)
        with out_txt.open("w", encoding="utf-8") as f:
            for u in flat_urls:
                f.write(u + "\n")

        print(f"✅ Coletados {len(rows)} links em seções.")
        print(f"   - {out_csv}")
        print(f"   - {out_txt}")

        ctx.close()
        browser.close()

if __name__ == "__main__":
    # Dica: permitir passar a URL por parâmetro (opcional)
    if len(sys.argv) > 1:
        globals()["SEED_URL"] = sys.argv[1]
    main()
