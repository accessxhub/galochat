@echo off
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python nao encontrado. Instale em https://www.python.org/downloads/ ^(marque "Add python.exe to PATH"^).
  pause
  exit /b 1
)
python -c "import telethon, imageio_ffmpeg" >nul 2>nul
if errorlevel 1 (
  echo Instalando o que o GALOCHAT precisa ^(so na primeira vez^)...
  python -m pip install -r requirements.txt
  if errorlevel 1 (
    echo Falhou ao instalar. Verifique a internet e tente de novo.
    pause
    exit /b 1
  )
)
start "" pythonw galochat_app.py
