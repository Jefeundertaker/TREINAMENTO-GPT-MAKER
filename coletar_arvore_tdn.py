# -*- coding: utf-8 -*-
from pathlib import Path
from playwright.sync_api import sync_playwright
import urllib.parse as up
import csv, re, sys, json, time

# === CONFIG ===
PAGE_ID = "224116750"               # <-- seu pageId
HEADLESS = False                    # deixe False pra visualizar se der erro
WAIT_MS = 800
SCROLL_STEPS = 80
SCROLL_WAIT_MS = 200
# ==============

def limpar(s: str) -> str:
    if not s: return ""
    return re.sub(r"\s+", " ", s.strip())

def normalizar(url: str) -> str:
    u = up.urlsplit(url)
    qs = up.parse_qsl(u.query, keep_blank_values=True)
    qs = [(k, v) for (k, v) in qs if k.lower() not in {
        "utm_source","utm_medium","utm_campaign","utm_term","utm_content"}]
    return up.urlunsplit((u.scheme, u.netloc, u.path, up.urlencode(qs), ""))

def rolar_ate_fim(ctx):
    last = 0
    for _ in range(SCROLL_STEPS):
        try:
            ctx.evaluate("window.scrollBy(0, document.body.scrollHeight)")
            ctx.wait_for_timeout(SCROLL_WAIT_MS)
            h = ctx.evaluate("document.body.scrollHeight")
            if h == last: break
            last = h
        except: break

def expandir_tudo(ctx):
    # tenta "Expand all"
    tries = [
        ".plugin_pagetree_expand_all",
        'button:has-text("Expand")',
        'a:has-text("Expand")',
        'button:has-text("Expandir")',
        'a:has-text("Expandir")',
    ]
    for sel in tries:
        try:
            loc = ctx.locator(sel)
            if loc.count() > 0:
                loc.first.click(timeout=800)
                ctx.wait_for_timeout(WAIT_MS)
        except: pass
    # abre <details>
    try:
        ctx.evaluate("() => { for (const d of document.querySelectorAll('details')) d.open = true; }")
    except: pass
    # clica toggles várias passadas
    for _ in range(25):
        clicou = False
        for sel in [".plugin_pagetree_child_toggle", ".pagetree-toggle", ".plugin_pagetree_expandcollapse"]:
            try:
                loc = ctx.locator(sel)
                cnt = loc.count()
            except: cnt = 0
            for i in range(cnt):
                try:
                    loc.nth(i).click(timeout=300)
                    clicou = True
                except: pass
        ctx.wait_for_timeout(300)
        if not clicou:
            break

def achar_spacekey_no_release(page, release_url):
    """Abre a releaseview e tenta extrair o space key por vários meios."""
    page.goto(release_url, wait_until="domcontentloaded", timeout=120_000)
    page.wait_for_timeout(WAIT_MS)

    # 1) meta ajs-space-key
    for sel in [
        'meta[name="ajs-space-key"]',
        'meta[name="confluence-space-key"]',
    ]:
        try:
            val = page.get_attribute(sel, "content")
            if val and val.strip():
                return val.strip()
        except: pass

    # 2) atributo data-space-key em algum container
    try:
        val = page.eval_on_selector("body", "b => b.getAttribute('data-space-key')")
        if val: return val
    except: pass

    # 3) tentar achar em links de breadcrumbs: /display/{SPACE}/
    try:
        hrefs = page.eval_on_selector_all('a[href*="/display/"]', "els => els.map(a => a.getAttribute('href'))")
        if hrefs:
            for h in hrefs:
                m = re.search(r"/display/([A-Z0-9]+)/", h or "")
                if m: return m.group(1)
    except: pass

    # 4) fallback usando title/url (nem sempre funciona)
    return "LDT"  # último recurso; ajuste manual se necessário

def coletar_arvore_de_context(ctx):
    """
    Procura a UL raiz da árvore em um context (página/frame)
    e extrai nós recursivamente como path/title/url.
    """
    # tenta múltiplos seletores de UL
    ul_sel_list = [
        "ul.plugin_pagetree_children",
        ".pagetree ul.plugin_pagetree_children",
        "ul.children",
        ".plugin_pagetree > ul",
    ]
    root_found = None
    for sel in ul_sel_list:
        try:
            loc = ctx.locator(sel)
            if loc.count() > 0:
                root_found = sel
                break
        except: pass
    if not root_found:
        return []

    data = ctx.evaluate(f"""
(sel) => {{
  function T(s){{ return (s||'').trim().replace(/\\s+/g,' '); }}
  function getNodes(ul, prefix){{
    const out = [];
    const lis = Array.from(ul.querySelectorAll(':scope > li'));
    for(const li of lis){{
      const a = li.querySelector(':scope > .plugin_pagetree_children_content a, :scope > a, :scope > .content a');
      const title = T(a ? a.textContent : '');
      const url = a ? a.href : '';
      if(title && url){{
        const path = [...prefix, title];
        out.push({{path, title, url}});
      }}
      const child = li.querySelector(':scope > ul.plugin_pagetree_children, :scope > ul.children, :scope > ul');
      if(child){{
        out.push(...getNodes(child, (out.length ? out[out.length-1].path : prefix)));
      }}
    }}
    return out;
  }}
  const root = document.querySelector(sel);
  if(!root) return [];
  return getNodes(root, []);
}}
""", root_found)

    saida = []
    vistos = set()
    for n in data or []:
        title = limpar(n.get("title"))
        url = normalizar(n.get("url") or "")
        path = [limpar(x) for x in (n.get("path") or [])]
        key = (tuple(path), url)
        if url and key not in vistos:
            vistos.add(key)
            saida.append({"path": path, "title": title, "url": url})
    return saida

def main():
    page_url = f"https://tdn.totvs.com.br/pages/releaseview.action?pageId={PAGE_ID}"

    out_txt  = Path("links.txt")
    out_csv  = Path("links_tree.csv")
    debug_dir = Path("debug")
    debug_dir.mkdir(exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=HEADLESS)
        ctx = browser.new_context(locale="pt-BR", viewport={"width": 1400, "height": 900})
        page = ctx.new_page()

        # 1) Descobrir SPACE_KEY automaticamente
        space_key = achar_spacekey_no_release(page, page_url)
        print(f"SPACE_KEY detectado: {space_key}")

        # 2) Ir para a visão de hierarquia (árvore)
        tree_url = f"https://tdn.totvs.com.br/pages/reorderpages.action?key={space_key}&openId={PAGE_ID}"
        page.goto(tree_url, wait_until="domcontentloaded", timeout=120_000)
        page.wait_for_timeout(WAIT_MS)

        # 3) Expandir e rolar
        expandir_tudo(page)
        rolar_ate_fim(page)
        expandir_tudo(page)

        # 4) Tentar coletar no main frame
        nodes = coletar_arvore_de_context(page)

        # 5) Se vazio, tentar em iframes
        if not nodes:
            try:
                frames = page.frames
                print(f"iframes: {len(frames)}")
                for fr in frames:
                    try:
                        expandir_tudo(fr)
                        rolar_ate_fim(fr)
                        expandir_tudo(fr)
                        nodes += coletar_arvore_de_context(fr)
                    except: pass
            except: pass

        # 6) Se ainda vazio, salvar screenshot e html para debug
        if not nodes:
            page.screenshot(path=str(debug_dir / "tree_fail.png"), full_page=True)
            try:
                html = page.content()
                (debug_dir / "tree_fail.html").write_text(html, encoding="utf-8")
            except: pass
            print("⚠️ Não encontrei a árvore. Salvei debug/tree_fail.png e tree_fail.html para inspeção.")
        else:
            # Salvar saídas
            with out_txt.open("w", encoding="utf-8") as f:
                for n in nodes:
                    f.write(n["url"] + "\n")

            with out_csv.open("w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(["path","title","url"])
                for n in nodes:
                    w.writerow([" / ".join(n["path"]), n["title"], n["url"]])

            print(f"✅ Nós coletados: {len(nodes)}")
            print(f"   - {out_txt}")
            print(f"   - {out_csv}")

        ctx.close()
        browser.close()

if __name__ == "__main__":
    # permite sobrescrever PAGE_ID por parâmetro
    if len(sys.argv) > 1:
        pid = re.sub(r"\\D", "", sys.argv[1])
        if pid:
            PAGE_ID = pid
    main()
