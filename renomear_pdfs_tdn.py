import os
import re

# === CONFIGURE AQUI SE PRECISAR ===
BASE_DIR = r"C:\TDN TOTVS"

# Captura códigos tipo LF0304, OF0312, RI0201, PC0101 etc. mesmo cercados por _ - espaços etc.
CODIGO_REGEX = re.compile(r'(?<![A-Z0-9])([A-Z]{2,4}\d{3,4})(?![A-Z0-9])')

# Já está renomeado se começar com CÓDIGO + espaço
JA_PREFIXADO = re.compile(r'^[A-Z]{2,4}\d{3,4}\s')

def renomear_pdfs(base_dir: str):
    total = 0
    com_codigo = 0
    ja_ok = 0
    sem_codigo = 0

    for root, _, files in os.walk(base_dir):
        for file in files:
            if not file.lower().endswith(".pdf"):
                continue

            total += 1
            old_path = os.path.join(root, file)

            # pula se já começa com código
            if JA_PREFIXADO.match(file):
                ja_ok += 1
                print(f"🔹 Já renomeado, ignorando: {file}")
                continue

            nome, ext = os.path.splitext(file)
            m = CODIGO_REGEX.search(nome)

            if m:
                codigo = m.group(1)
                new_name = f"{codigo} {file}"
                new_path = os.path.join(root, new_name)

                if os.path.exists(new_path):
                    # evita sobrescrever
                    i = 2
                    base_nome = f"{codigo} {nome}"
                    while True:
                        cand = f"{base_nome} ({i}){ext}"
                        cand_path = os.path.join(root, cand)
                        if not os.path.exists(cand_path):
                            new_path = cand_path
                            new_name = cand
                            break
                        i += 1

                try:
                    os.rename(old_path, new_path)
                    com_codigo += 1
                    print(f"✅ Renomeado: {file}  ->  {new_name}")
                except Exception as e:
                    print(f"❌ Erro ao renomear {file}: {e}")
            else:
                sem_codigo += 1
                print(f"⚠️ Código não encontrado em: {file}")

    print("\n— Resumo —")
    print(f"Total PDFs: {total}")
    print(f"Renomeados com código: {com_codigo}")
    print(f"Já prefixados (ignorados): {ja_ok}")
    print(f"Sem código no nome: {sem_codigo}")

if __name__ == "__main__":
    renomear_pdfs(BASE_DIR)
    print("\n🎯 Concluído.")
