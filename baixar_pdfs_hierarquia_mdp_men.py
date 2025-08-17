
# -*- coding: utf-8 -*-
"""
baixar_pdfs_hierarquia_mdp_men.py
- Lê links_organizados.txt (linhas "Seção" e linhas " - Título :: URL")
- Mantém hierarquia de seções como pastas
- Salva PDFs em PDFs_TDN_MDP_MEN/<Seção>/<CÓDIGO - Título>.pdf quando houver código
- Usa Playwright/Chromium para "imprimir" a página (com background)
- Progresso no console + log.csv + status.json
"""

from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
import re, csv, time, json

INPUT_TXT = Path("links_organizados.txt")
OUT_ROOT  = Path("PDFs_TDN_MDP_MEN")
HEADLESS  = True
PRINT_BG  = True
SCROLL_STEPS = 100
SCROLL_WAIT_MS = 180

# Códigos alvo: DP/DPR/DMDP (MDP) e EN/ENR/DMEN/ENAPI/BOIN (MEN)
CODE_RE = re.compile(r"\b(DP\d{4}[A-Z]?|DPR\d{3}[A-Z]?|DMDP0*\d+|EN\d{4}[A-Z]?|ENR\d{3}[A-Z]?|DMEN0*\d+|ENAPI\d+|BOIN\d+)\b", re.I)

def limpar_nome(s: str) -> str:
    if not s: return "arquivo"
    s = s.replace("\u00A0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"^(TOTVS\s*[\|\-]\s*)", "", s, flags=re.I)
    s = re.sub(r'[\\/*?:"<>|]+', " ", s).strip()
    return s[:150] or "arquivo"

def extrair_codigo(texto: str) -> str:
    m = CODE_RE.search(texto or "")
    return (m.group(1).upper() if m else "").replace("  ", " ")

def rolar_ate_fim(page):
    last = 0
    for _ in range(SCROLL_STEPS):
        try:
            page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
            page.wait_for_timeout(SCROLL_WAIT_MS)
            h = page.evaluate("document.body.scrollHeight")
            if h == last: break
            last = h
        except Exception:
            break

def titulo_da_pagina(page) -> str:
    try:
        t = page.title() or ""
        return limpar_nome(t) or "pagina"
    except Exception:
        return "pagina"

def nome_arquivo(titulo: str, page_title: str) -> str:
    # prioridade: código (do título fornecido), senão do título da página
    code = extrair_codigo(titulo) or extrair_codigo(page_title)
    base_title = limpar_nome(titulo)
    if code and not base_title.upper().startswith(code):
        return f"{code} - {base_title}.pdf"
    return f"{base_title}.pdf"

def parse_links(txt_path: Path):
    """
    Retorna lista de dicts: {"section": "...", "title": "...", "url": "..."}
    """
    items = []
    section = "Outros"
    for raw in txt_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line: 
            continue
        if line.startswith(" - "):  # item
            body = line[3:].strip()
            if " :: " in body:
                t, u = body.split(" :: ", 1)
            elif " -> " in body:
                t, u = body.split(" -> ", 1)
            else:
                # formato inesperado, ignora
                continue
            items.append({"section": section, "title": t.strip(), "url": u.strip()})
        else:
            section = line
    return items

def nome_unico(dest: Path) -> Path:
    if not dest.exists():
        return dest
    base = dest.with_suffix("")
    ext = dest.suffix
    i = 2
    while True:
        cand = Path(f"{base} ({i}){ext}")
        if not cand.exists():
            return cand
        i += 1

def main():
    if not INPUT_TXT.exists():
        raise FileNotFoundError("links_organizados.txt não encontrado.")
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    log_csv = OUT_ROOT / "log.csv"
    status_json = OUT_ROOT / "status.json"

    new_log = not log_csv.exists()
    flog = log_csv.open("a", encoding="utf-8", newline="")
    wlog = csv.writer(flog)
    if new_log:
        wlog.writerow(["section","title","url","pdf_path","status","erro"])

    items = [it for it in parse_links(INPUT_TXT) if it["url"].startswith("http")]
    total = len(items)
    print(f"Total de links válidos: {total}")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=HEADLESS)
        ctx = browser.new_context(locale="pt-BR", viewport={"width": 1400, "height": 900})
        page = ctx.new_page()
        page.set_default_timeout(90_000)

        start = time.time()
        ok_count = 0

        for i, it in enumerate(items, start=1):
            sec = limpar_nome(it["section"]) or "Outros"
            pasta = OUT_ROOT / sec
            pasta.mkdir(parents=True, exist_ok=True)

            url = it["url"]
            titulo = limpar_nome(it["title"])

            pdf_name = f"{titulo}.pdf"  # provisório
            pdf_path = pasta / pdf_name

            ok = False
            err = ""
            real_title = ""
            for tent in range(3):
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=120_000)
                    page.wait_for_timeout(600)
                    rolar_ate_fim(page)
                    real_title = titulo_da_pagina(page)
                    # renomeia usando código (se houver)
                    pdf_name = nome_arquivo(titulo, real_title)
                    pdf_path = nome_unico(pasta / pdf_name)
                    page.pdf(path=str(pdf_path), format="A4", print_background=PRINT_BG)
                    ok = True
                    break
                except Exception as e:
                    err = str(e)
                    time.sleep(0.9*(tent+1))

            if ok:
                ok_count += 1
                wlog.writerow([sec, it["title"], url, str(pdf_path), "OK", ""])
            else:
                wlog.writerow([sec, it["title"], url, "", "ERRO", err])

            flog.flush()
            elapsed = time.time() - start
            rate = (i/elapsed*60) if elapsed>0 else 0.0
            eta_s = int((total - i) / rate * 60) if rate > 0 else 0
            status_json.write_text(json.dumps({
                "total": total, "done": i, "ok": ok_count,
                "last": str(pdf_path if ok else url),
                "rate_pages_per_min": round(rate, 1),
                "eta": f"{eta_s//60:02d}:{eta_s%60:02d}"
            }, ensure_ascii=False), encoding="utf-8")
            print(f"[{i}/{total}] {'OK   ' if ok else 'ERRO '}| {pdf_path.name if ok else '(falha)'} | {rate:.1f} pág/min",
                  flush=True)

        ctx.close()
        browser.close()

    flog.close()
    print(f"\n✅ Concluído. PDFs em: {OUT_ROOT.resolve()}")
    print(f"   - log: {log_csv}")
    print(f"   - status: {status_json}")

if __name__ == "__main__":
    main()
