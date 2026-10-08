@echo off
setlocal
cd /d "%~dp0"
title GALOCHAT - gerar executavel protegido

where python >nul 2>nul
if errorlevel 1 (
  echo Python nao encontrado.
  echo Instale o Python 3.10 ou mais novo em https://www.python.org/downloads/
  echo e marque "Add python.exe to PATH" durante a instalacao.
  pause
  exit /b 1
)

echo Instalando as ferramentas de build...
python -m pip install --upgrade pip
python -m pip install -r requirements-build.txt
if errorlevel 1 goto falhou

echo.
echo Gerando o GALOCHAT.exe protegido...
python tools\empacotar.py
if errorlevel 1 goto falhou

echo.
echo Pronto! O programa esta em:  dist\GALOCHAT.exe
echo Distribua APENAS esse arquivo. O codigo-fonte nao vai dentro de forma legivel.
pause
exit /b 0

:falhou
echo.
echo Algo deu errado. Copie as mensagens acima para analisar.
pause
exit /b 1
