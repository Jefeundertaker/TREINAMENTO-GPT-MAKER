from pathlib import Path
import csv
import re
import html
import urllib.parse as up
from playwright.sync_api import sync_playwright

# >>> COLE AQUI O LINK-ÍNDICE (o do seu print)
SEED_URL = "https://tdn.totvs.com.br/display/public/LDT/MCF+-+Configurador+de+Produtos"

# Configs
HEADLESS = True          # Coloque False para ver a janela abrindo
SCROLL_STEPS = 30        # Quantidade de rolagens até o fim
SCROLL_WAIT_MS = 300     # Espera entre rolagens (ms)
MAX_EXPAND_PASSES = 6    # Quantas “varridas” de expandir faremos

DOMINIO = "tdn.totvs.com.br"

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

def expandir_tudo(page):
    # Abre elementos <details>
    page.evaluate("""() => {
        for (const d of document.querySelectorAll('details')) d.open = true;
    }""")

    # Tenta clicar em botões/links de expandir (várias tentativas/seletores)
    seletores = [
        'button[aria-expanded="false"]',
        '[role="button"][aria-expanded="false"]',
        'a[aria-expanded="false"]',
        'button:has-text("Expandir")',
        'a:has-text("Expandir")',
        '.expand-control',                     # comum em Confluence
        '.plugin_pagetree_expand_all',         # árvores antigas
        '.aui-button[aria-expanded="false"]',
        'span[role="button"][aria-expanded="false"]',
    ]
    for _ in range(MAX_EXPAND_PASSES):
        clicou_algo = False
        for sel in seletores:
            loc = page.locator(sel)
            count = 0
            try:
                count = loc.count()
            except:
                pass
            for i in range(count):
                try:
                    loc.nth(i).click(force=True, timeout=500)
                    clicou_algo = True
                except:
                    pass
        # dar um tempo pra carregar filhos
        page.wait_for_timeout(600)
        if not clicou_algo:
            break

def rolar_ate_fim(page):
    last_height = 0
    for _ in range(SCROLL_STEPS):
        page.evaluate("window.scrollBy(0, document.body.scrollHeight);")
        page.wait_for_timeout(SCROLL_WAIT_MS)
        new_height = page.evaluate("document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height

def coletar_anchors(page):
    pares = page.eval_on_selector_all(
        "a[href]",
        "els => els.map(a => [a.href, (a.textContent||'').trim()])"
    )
    # normaliza, filtra domínio e padrões
    vistos = set()
    uniq = []
    for href, txt in pares:
        url = normalizar(href)
        if not eh_do_tdn(url):
            continue
        path = up.urlsplit(url).path
        if not passa_filtro(path):
            continue
        if url not in vistos:
            vistos.add(url)
            uniq.append((url, txt))
    return uniq

def salvar(pares, pasta: Path):
    pasta.mkdir(parents=True, exist_ok=True)
    # links.txt
    with (pasta / "links.txt").open("w", encoding="utf-8") as f:
        for url, _ in pares:
            f.write(url + "\n")
    # links.csv
    with (pasta / "links.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["url", "texto_ancora"])
        for url, txt in pares:
            w.writerow([url, txt])

def main():
    outdir = Path(".")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        ctx = browser.new_context(locale="pt-BR", user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"))
        page = ctx.new_page()
        page.goto(SEED_URL, wait_until="domcontentloaded", timeout=120_000)
        # dá tempo pra scripts da página
        page.wait_for_timeout(1200)

        expandir_tudo(page)
        rolar_ate_fim(page)          # garante carregamento lazy
        expandir_tudo(page)          # mais uma varrida após rolagem
        rolar_ate_fim(page)

        pares = coletar_anchors(page)
        salvar(pares, outdir)

        print(f"✅ Links coletados: {len(pares)}")
        print(f"   - {outdir / 'links.txt'}")
        print(f"   - {outdir / 'links.csv'}")

        ctx.close()
        browser.close()

if __name__ == "__main__":
    main()
