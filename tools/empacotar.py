# =============================================================================
#  GALOCHAT  ·  © 2026 F.ER ACADEMY — Todos os direitos reservados.
# =============================================================================
# -*- coding: utf-8 -*-
"""Gera o executável protegido do GALOCHAT.

O que ele faz, nesta ordem:
  1. Minifica os módulos (remove comentários, docstrings e nomes internos legíveis).
  2. Compila com o PyInstaller em UM arquivo, com o FFmpeg embutido.
  3. Grava nos metadados do .exe a autoria «F.ER ACADEMY» (nada pessoal).
  4. Testa o programa gerado (--selftest) antes de declarar sucesso.

Assim, o que é distribuído é só o binário (bytecode), sem o código-fonte.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
MODULOS = ["galochat_core.py", "galochat_app.py", "galochat_brand.py"]
ENTRADA = "galochat_app.py"
VERSAO = "1.0.0"

VERSION_INFO = f"""# gerado automaticamente — metadados do executável
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=(1,0,0,0), prodvers=(1,0,0,0),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0,0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'F.ER ACADEMY'),
      StringStruct('FileDescription', 'GALOCHAT'),
      StringStruct('FileVersion', '{VERSAO}'),
      StringStruct('InternalName', 'GALOCHAT'),
      StringStruct('LegalCopyright', '© 2026 F.ER ACADEMY. Todos os direitos reservados.'),
      StringStruct('OriginalFilename', 'GALOCHAT.exe'),
      StringStruct('ProductName', 'GALOCHAT'),
      StringStruct('ProductVersion', '{VERSAO}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])])
"""


def minificar(origem: Path, destino: Path):
    import python_minifier as m
    destino.write_text(
        m.minify(origem.read_text(encoding="utf-8"), filename=origem.name,
                 remove_literal_statements=True, rename_locals=True, rename_globals=False,
                 hoist_literals=True, remove_annotations=True, combine_imports=True),
        encoding="utf-8")


def main():
    for mod in ("python_minifier", "PyInstaller"):
        try:
            __import__(mod)
        except ImportError:
            sys.exit(f"Falta a ferramenta «{mod}». Rode: pip install python-minifier pyinstaller")

    saida = RAIZ / "dist"
    with tempfile.TemporaryDirectory() as tmp:
        build = Path(tmp)
        for nome in MODULOS:
            print(f"  protegendo {nome}…")
            minificar(RAIZ / nome, build / nome)
        (build / "version_info.txt").write_text(VERSION_INFO, encoding="utf-8")

        cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
               "--name", "GALOCHAT", "--collect-all", "imageio_ffmpeg",
               "--version-file", str(build / "version_info.txt"),
               "--distpath", str(saida), "--workpath", str(build / "b"), "--specpath", str(build),
               str(build / ENTRADA)]
        if sys.platform != "win32":
            cmd.insert(-1, "--strip")               # remove símbolos no Linux
        print("  compilando com o PyInstaller…")
        if subprocess.run(cmd).returncode != 0:
            sys.exit("Falha ao compilar.")

    exe = saida / ("GALOCHAT.exe" if sys.platform == "win32" else "GALOCHAT")
    print("  testando o executável gerado…")
    try:
        res = subprocess.run([str(exe), "--selftest"], capture_output=True, text=True)
        print(res.stdout[-400:])
        if res.returncode != 0:
            sys.exit("O autoteste do executável falhou.")
    except PermissionError:
        print("  (não foi possível executar o teste nesta pasta; rode o .exe à mão para conferir)")
    print(f"\nPronto: {exe}")
    print("Distribua apenas este arquivo. O código-fonte não vai dentro de forma legível.")


if __name__ == "__main__":
    main()
