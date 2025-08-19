import asyncio
from playwright.async_api import async_playwright
import os

ARQUIVO_LINKS = "links_organizados.txt"
PASTA_SAIDA = "pdfs_links"

async def salvar_pdfs():
    os.makedirs(PASTA_SAIDA, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()

        with open(ARQUIVO_LINKS, "r", encoding="utf-8") as f:
            linhas = f.readlines()

        for linha in linhas:
            try:
                if ":" not in linha:
                    continue

                # Divide em título e URL
                partes = linha.split(":", 1)
                if len(partes) != 2:
                    continue

                titulo, url = partes
                titulo = titulo.strip().replace(" ", "_").replace("/", "_")

                # Corrige URL (remove ":" inicial, espaços extras)
                url = url.strip()
                if url.startswith(":"):
                    url = url[1:].strip()

                if not url.startswith("http"):
                    print(f"⚠️ URL inválida ignorada: {url}")
                    continue

                print(f"📄 Gerando PDF de: {titulo} -> {url}")
                page = await context.new_page()
                await page.goto(url, wait_until="load", timeout=60000)

                caminho_pdf = os.path.join(PASTA_SAIDA, f"{titulo}.pdf")
                await page.pdf(path=caminho_pdf, format="A4")
                await page.close()

            except Exception as e:
                print(f"❌ Erro ao processar {linha.strip()}: {e}")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(salvar_pdfs())
