@echo off
cd /d "%~dp0"
python --version >nul 2>&1 || (echo Python nao encontrado. Instale o Python 3.x e tente novamente. & pause & exit /b 1)
pip show requests >nul 2>&1 || pip install requests
pip show beautifulsoup4 >nul 2>&1 || pip install beautifulsoup4
python baixar_pdfs_nomeados.py
echo.
echo Concluido. Pressione uma tecla para sair.
pause
