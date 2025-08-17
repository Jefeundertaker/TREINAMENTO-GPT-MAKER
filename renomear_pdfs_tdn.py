import os
import re

# Caminho base onde estão os PDFs
BASE_DIR = r"C:\TDN TOTVS"

# Regex para capturar códigos como PC0101, MPD1234 etc.
CODIGO_REGEX = re.compile(r'\b([A-Z]{2,4}\d{3,4})\b')

def renomear_pdfs(base_dir):
    for root, _, files in os.walk(base_dir):
        for file in files:
            if file.lower().endswith(".pdf"):
                old_path = os.path.join(root, file)

                # Se já tem prefixo "-XXX", pula
                if re.match(r"^-[A-Z]{2,4}\d{3,4}\s", file):
                    print(f"🔹 Já renomeado, ignorando: {file}")
                    continue

                # Procurar código no nome
                match = CODIGO_REGEX.search(file)
                if match:
                    codigo = match.group(1)
                    new_name = f"-{codigo} {file}"
                    new_path = os.path.join(root, new_name)

                    try:
                        os.rename(old_path, new_path)
                        print(f"✅ Renomeado: {file} -> {new_name}")
                    except Exception as e:
                        print(f"❌ Erro ao renomear {file}: {e}")
                else:
                    print(f"⚠️ Código não encontrado em: {file}")

if __name__ == "__main__":
    renomear_pdfs(BASE_DIR)
    print("\n🎯 Concluído. Todos os PDFs foram processados.")
