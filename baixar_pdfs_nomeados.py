import subprocess
import requests
from bs4 import BeautifulSoup
import re
import os
import time
import shutil
from urllib.parse import urlparse, parse_qs
from pathlib import Path

# ======= CONFIG =======
CANDIDATOS_CHROME = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
TIMEOUT = 30
RETRIES = 3
SLEEP_RETRY = 2
# ======================

def encontrar_navegador():
    for path in CANDIDATOS_CHROME:
        if os.path.isfile(path):
            return path
    for cmd in ["chrome.exe", "msedge.exe"]:
        which = shutil.which(cmd)
        if which:
            return which
    raise FileNotFoundError(
        "Não encontrei Google Chrome / Microsoft Edge. "
        "Instale o Chrome ou ajuste o caminho no script."
    )

def limpar_nome(nome: str) -> str:
    nome = nome.strip()
    nome = re.sub(r"^\s*(TOTVS\s*\|\s*|TOTVS\s*-\s*)", "", nome, flags=re.I)
    nome = re.sub(r'[\\/*?:"<>|]+', " ", nome)
    nome = re.sub(r"\s{2,}", " ", nome)
    return nome[:150].strip() or "pagina"

def extrair_fallback_do_link(link: str) -> str:
    try:
        u = urlparse(link)
        qs = parse_qs(u.query)
        if "pageId" in qs and qs["pageId"]:
            return f"TDN pageId {qs['pageId'][0]}"
        base = os.path.basename(u.path) or "pagina"
        return base
    except Exception:
        return "pagina"

def obter_titulo(link: str) -> str:
    headers = {"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9"}
    for tent in range(1, RETRIES + 1):
        try:
            r = requests.get(link, headers=headers, timeout=TIMEOUT)
            if r.status_code >= 400:
                raise requests.RequestException(f"HTTP {r.status_code}")
            r.encoding = r.apparent_encoding or "utf-8"
            soup = BeautifulSoup(r.text, "html.parser")
            if soup.title and soup.title.string and soup.title.string.strip():
                return limpar_nome(soup.title.string)
            h1 = soup.find("h1")
            if h1 and h1.get_text(strip=True):
                return limpar_nome(h1.get_text(strip=True))
            return limpar_nome(extrair_fallback_do_link(link))
        except Exception:
            if tent < RETRIES:
                time.sleep(SLEEP_RETRY * tent)
            else:
                return limpar_nome(extrair_fallback_do_link(link))

def nome_unico(caminho: Path) -> Path:
    if not caminho.exists():
        return caminho
    base = caminho.with_suffix("")
    ext = caminho.suffix
    i = 2
    while True:
        cand = Path(f"{base} ({i}){ext}")
        if not cand.exists():
            return cand
        i += 1

def imprimir_pdf(navegador_path: str, url: str, saida_pdf: Path):
    # Chrome/Edge headless exigem caminho ABSOLUTO no --print-to-pdf (principal correção)
    saida_pdf = saida_pdf.resolve()
    args = [
        navegador_path,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--print-to-pdf-no-header",
        "--disable-features=Translate,MediaRouter,OptimizationHints",
        "--no-first-run",
        "--virtual-time-budget=15000",
        f"--print-to-pdf={str(saida_pdf)}",
        url,
    ]
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0 or not saida_pdf.exists():
        raise RuntimeError(f"Falha ao gerar PDF. STDERR: {proc.stderr}")

def main():
    navegador = encontrar_navegador()
    print(f"➡️ Usando navegador: {navegador}")

    links_path = Path("links.txt").resolve()
    if not links_path.exists():
        raise FileNotFoundError("Arquivo 'links.txt' não encontrado na pasta atual.")

    with links_path.open("r", encoding="utf-8") as f:
        links = [ln.strip() for ln in f if ln.strip()]

    if not links:
        print("Nenhum link encontrado em links.txt.")
        return

    out_dir = Path(__file__).parent.resolve() / "PDFs"
    out_dir.mkdir(parents=True, exist_ok=True)

    for idx, link in enumerate(links, start=1):
        print(f"\n[{idx}/{len(links)}] Processando: {link}")
        titulo = obter_titulo(link)
        nome_pdf = f"{titulo}.pdf"
        destino = nome_unico(out_dir / nome_pdf)

        try:
            imprimir_pdf(navegador, link, destino)
            print(f"✅ PDF gerado: {destino}")
        except Exception as e:
            print(f"⚠️ Erro ao gerar com título '{titulo}': {e}")
            fallback = limpar_nome(extrair_fallback_do_link(link)) + ".pdf"
            destino_fb = nome_unico(out_dir / fallback)
            try:
                imprimir_pdf(navegador, link, destino_fb)
                print(f"✅ PDF gerado (fallback): {destino_fb}")
            except Exception as e2:
                print(f"❌ Falha final neste link: {e2}")

if __name__ == "__main__":
    main()
