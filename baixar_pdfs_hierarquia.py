# -*- coding: utf-8 -*-
"""
Lê links_organizados.txt no formato:
Seção A
 - Título X :: https://...
 - Título Y :: https://...
Seção B
 - Outro Título :: https://...

Cria:
PDFs_TDN/
  Seção A/
    Título X.pdf
    Título Y.pdf
  Seção B/
    Outro Título.pdf

Mostra progresso, gera log.csv e status.json.
Aceita também linhas com " -> " em vez de " :: ".
"""

from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
import re, csv, time, json

TXT = Path("links_organizados.txt")
OUT = Path("PDFs_TDN")
HEADLESS = True          # coloque False se quiser ver a janela
PRINT_BG = True          # imprimir com fundo
SCROLL_STEPS = 80        # aumente se as páginas forem longas
SCROLL_WAIT_MS = 200

def limpar_nome(s: str) -> str:
    if not s: return "arquivo"
    s = s.replace("\u00A0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    # remove prefixos genéricos
    s = re.sub(r"^(TOTVS\s*[\|\-]\s*)", "", s, flags=re.I)
    # pro nome de arquivo no Windows
    s = re.sub(r'[\\/*?:"<>|]+', " ", s).strip()
    return s[:150] or "arquivo"

def rolar_ate_fim(page):
    last = 0
    for _ in range(SCROLL_STEPS):
        try:
            page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
            page.wait_for_timeout(SCROLL_WAIT_MS)
            h = page.evaluate("document.body.scrollHeight")
            if h == last: break
            last = h
        except: break

def titulo_da_pagina(page) -> str:
    try:
        t = page.title() or ""
        t = limpar_nome(t)
        return t or "pagina"
    except:
        return "pagina"

def salvar_pdf(page, url: str, destino: Path):
    page.goto(url, wait_until="domcontentloaded", timeout=120_000)
    page.wait_for_timeout(600)
    rolar_ate_fim(page)
    page.pdf(path=str(destino), format="A4", print_background=PRINT_BG)

def parse_linhas(txt: Path):
    """
    Retorna lista de dicts:
    {"section":"Seção", "title":"Título", "url":"https://..."}
    """
    linhas = [ln.rstrip("\n") for ln in txt.read_text(encoding="utf-8").splitlines() if ln.strip()]
    items = []
    sec = "Outros"
    for ln in linhas:
        if ln.startswith(" - "):  # item
            body = ln[3:].strip()
            # aceita "Título :: URL" ou "Título -> URL"
            if " :: " in body:
                t, u = body.split(" :: ", 1)
            elif " -> " in body:
                t, u = body.split(" -> ", 1)
            else:
                # linha de item sem separador esperado: ignora
                continue
            items.append({"section": sec, "title": t.strip(), "url": u.strip()})
        else:
            # é seção (linha sem prefixo " - ")
            sec = ln.strip()
    return items

def nome_unico(dest: Path) -> Path:
    if not dest.exists(): return dest
    base = dest.with_suffix("")
    ext = dest.suffix
    i = 2
    while True:
        cand = Path(f"{base} ({i}){ext}")
        if not cand.exists(): return cand
        i += 1

def main():
    if not TXT.exists():
        raise FileNotFoundError("links_organizados.txt não encontrado na pasta atual.")

    OUT.mkdir(parents=True, exist_ok=True)
    log_csv = OUT / "log.csv"
    status_json = OUT / "status.json"

    novo_log = not log_csv.exists()
    flog = log_csv.open("a", encoding="utf-8", newline="")
    wlog = csv.writer(flog)
    if novo_log:
        wlog.writerow(["section","title","url","pdf_path","status","erro"])

    items = parse_linhas(TXT)
    total = len(items)
    print(f"Total de links: {total}")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=HEADLESS)
        ctx = browser.new_context(locale="pt-BR", viewport={"width": 1400, "height": 900})
        page = ctx.new_page()
        page.set_default_timeout(90_000)

        start = time.time()
        ok_count = 0

        for i, it in enumerate(items, start=1):
            sec = limpar_nome(it["section"]) or "Outros"
            pasta = OUT / sec
            pasta.mkdir(parents=True, exist_ok=True)

            url = it["url"]
            # tenta nomear pelo título real da página (melhor)
            titulo = limpar_nome(it["title"])
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=120_000)
                page.wait_for_timeout(600)
                rolar_ate_fim(page)
                real = titulo_da_pagina(page)
                if real and len(real) > 5:
                    titulo = real
            except PWTimeout:
                pass
            except Exception:
                pass

            pdf_path = pasta / f"{titulo}.pdf"
            pdf_path = nome_unico(pdf_path)

            if pdf_path.exists():
                wlog.writerow([sec, it["title"], url, str(pdf_path), "SKIP", ""])
                flog.flush()
                elapsed = time.time() - start
                rate = (i/elapsed*60) if elapsed>0 else 0.0
                print(f"[{i}/{total}] SKIP  | {pdf_path.name} | {rate:.1f} pág/min", flush=True)
                continue

            ok = False; err = ""
            for tent in range(3):
                try:
                    salvar_pdf(page, url, pdf_path)
                    ok = True
                    break
                except Exception as e:
                    err = str(e)
                    time.sleep(0.8*(tent+1))

            if ok:
                ok_count += 1
                wlog.writerow([sec, it["title"], url, str(pdf_path), "OK", ""])
            else:
                wlog.writerow([sec, it["title"], url, "", "ERRO", err])

            flog.flush()
            elapsed = time.time() - start
            rate = (i/elapsed*60) if elapsed>0 else 0.0
            rem_s = int((total - i) / rate * 60) if rate > 0 else 0
            status_json.write_text(json.dumps({
                "total": total, "done": i, "ok": ok_count,
                "last": str(pdf_path if ok else url),
                "rate_pages_per_min": round(rate, 1),
                "eta": f"{rem_s//60:02d}:{rem_s%60:02d}"
            }, ensure_ascii=False), encoding="utf-8")
            print(f"[{i}/{total}] {'OK   ' if ok else 'ERRO '}| {pdf_path.name if ok else '(falha)'} | {rate:.1f} pág/min",
                  flush=True)

        ctx.close()
        browser.close()

    flog.close()
    print(f"\n✅ Concluído. PDFs em: {OUT.resolve()}\n   - log: {log_csv}\n   - status: {status_json}")

if __name__ == "__main__":
    main()
