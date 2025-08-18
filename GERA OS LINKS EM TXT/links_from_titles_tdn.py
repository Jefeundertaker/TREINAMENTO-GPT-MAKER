import argparse
import requests
from bs4 import BeautifulSoup
import time

# Função para buscar link no TDN pelo título
def buscar_link_por_titulo(titulo):
    url = "https://tdn.totvs.com.br/dosearchsite.action"
    params = {"queryString": titulo}
    headers = {"User-Agent": "Mozilla/5.0"}
    
    resp = requests.get(url, params=params, headers=headers)
    if resp.status_code != 200:
        return None
    
    soup = BeautifulSoup(resp.text, "html.parser")
    link_tag = soup.find("a", href=True, class_="search-result-link")
    if link_tag:
        return "https://tdn.totvs.com.br" + link_tag["href"]
    return None

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Arquivo de títulos")
    parser.add_argument("--out", required=True, help="Arquivo de saída com links")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        titulos = [linha.strip() for linha in f if linha.strip()]

    resultados = []

    for titulo in titulos:
        print(f"🔍 Buscando: {titulo} ...")
        link = buscar_link_por_titulo(titulo)
        if link:
            resultado = f"{titulo} :: {link}"
            print(f"✅ Encontrado: {resultado}")
            resultados.append(resultado)
        else:
            print(f"⚠️ Não encontrado: {titulo}")
        time.sleep(1)  # evitar bloqueio por excesso de requisições

    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(resultados))

    print(f"\n📂 Arquivo {args.out} gerado com {len(resultados)} links")
