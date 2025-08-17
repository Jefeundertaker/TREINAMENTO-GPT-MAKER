import os
import re
import asyncio
import argparse
from pathlib import Path
from playwright.async_api import async_playwright

# Regex para extrair código tipo PC0101, MPD1234, etc.
CODIGO_REGEX = re.compile(r"\b([A-Z]{2,4}\d{3,4})\b")

async def baixar_pdf(playwright, url, pasta_saida, idx):
    """Abre a página e gera PDF"""
    browser = await playwright.chromium.launch(headless=True)
    page = await browser.new_page()

    try:
        await page.goto(url, timeout=60000)
        await page.wait_for_timeout(5000)

        # Extrair título da página
        titulo = await page.title()
        titulo = titulo.replace(":", " -").replace("/", "-").strip()

        # Extrair código do programa
        m = CODIGO_REGEX.search(titulo)
        codigo = m.group(1) if m else None

        # Definir nome do arquivo no formato pedido
        if codigo:
            nome_arquivo = f"-{codigo} {titulo} - {codigo}.pdf"
        else:
            nome_arquivo = f"{titulo}.pdf"

        caminho_pdf = os.path.join(pasta_saida, nome_arquivo)

        # Gerar PDF
        await page.pdf(path=caminho_pdf, format="A4")
        print(f"[{idx}] ✅ PDF salvo: {caminho_pdf}")

    except Exception as e:
        print(f"[{idx}] ❌ Erro em {url}: {e}")

    finally:
        await browser.close()


async def processar_links(arquivo_input, pasta_saida):
    """Processa todos os links e gera PDFs"""
    pasta_saida = Path(pasta_saida)
    pasta_saida.mkdir(parents=True, exist_ok=True)

    with open(arquivo_input, "r", encoding="utf-8") as f:
        linhas = [l.strip() for l in f.readlines() if l.strip()]

    # Apenas linhas que contenham http
    links = [l.split("::")[-1].strip() for l in linhas if "http" in l]

    print(f"Total de links válidos: {len(links)}")

    if not links:
        print("Nenhum link encontrado. Verifique o arquivo.")
        return

    async with async_playwright() as playwright:
        for idx, url in enumerate(links, start=1):
            await baixar_pdf(playwright, url, pasta_saida, idx)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Baixar PDFs do TDN")
    parser.add_argument("--input", type=str, default="links_organizados.txt", help="Arquivo com links")
    parser.add_argument("--out", type=str, default="PDFs_TDN_MDP_MEN", help="Pasta de saída")

    args = parser.parse_args()
    asyncio.run(processar_links(args.input, args.out))
