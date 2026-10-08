# =============================================================================
#  GALOCHAT  ·  © 2026 F.ER ACADEMY — Todos os direitos reservados.
#  Software proprietário da F.ER ACADEMY. Proibida a cópia, a engenharia
#  reversa ou a redistribuição, total ou parcial, sem autorização por escrito.
# =============================================================================
# -*- coding: utf-8 -*-
"""GALOCHAT — núcleo (sem interface). Lê cursos em .zip/pastas, prepara os vídeos
com FFmpeg, publica no Telegram (capa, aulas, documentos, guia) e retoma de onde parou."""
from __future__ import annotations

import asyncio
import hashlib
import html
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath

from telethon import TelegramClient, errors
from telethon.tl.functions.channels import CreateChannelRequest
from telethon.tl.types import Channel, DocumentAttributeVideo, PeerChannel

APP_NOME = "GALOCHAT"
VERSAO = "1.0.0"
MIB = 1024 * 1024
PASTA_ENVIADOS = "_enviados"

EXT_VIDEO = {".mp4", ".mkv", ".mov", ".avi", ".m4v", ".webm", ".wmv", ".flv",
             ".ts", ".mts", ".m2ts", ".mpg", ".mpeg", ".3gp", ".vob"}
EXT_IMG = {".jpg", ".jpeg", ".png", ".webp"}
NOMES_CAPA = {"capa", "cover"}
IGNORAR_NOMES = {"thumbs.db", "desktop.ini", ".ds_store"}
IGNORAR_EXT = {".url", ".lnk", ".nfo", ".tmp", ".part", ".crdownload"}

CONFIG_PADRAO = {
    "api_id": "",
    "api_hash": "",
    "destino": None,                  # {"id": 123 | "me", "titulo": "...", "username": ...}
    "aviso_aceito": False,
    "usar_prefixo": True,             # #EIE_F001 em vez de #F001 (evita choque entre cursos)
    "enviar_documentos": True,
    "otimizar_streaming": True,       # MP4 "faststart": começa a tocar na hora
    "converter_incompativeis": True,  # AVI/WMV/VP9... -> H.264 para tocar no Telegram
    "preset_x264": "veryfast",
    "crf_x264": 21,
    "fixar": True,                    # fixa o guia (ou o índice) no topo do canal
    "indice": False,                  # mantém um índice com todos os cursos do canal
    "boas_vindas": "Seja bem-vindo(a). Use os links abaixo para navegar entre os módulos e aulas:",
    "assinatura": "",                 # texto opcional ao final do nome de cada aula
    "depois": "nada",                 # "nada" | "mover"
    "categoria_padrao": "Geral",
    "tipo_padrao": "Curso",
}


# ═══════════════════════ dados do app ═══════════════════════

def pasta_dados() -> Path:
    if os.environ.get("GALOCHAT_DADOS"):
        p = Path(os.environ["GALOCHAT_DADOS"])
    else:
        if sys.platform == "win32":
            base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
        elif sys.platform == "darwin":
            base = Path.home() / "Library" / "Application Support"
        else:
            base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
        p = base / APP_NOME
    p.mkdir(parents=True, exist_ok=True)
    return p


def ler_json(caminho: Path, padrao):
    caminho = Path(caminho)
    if not caminho.exists():
        return padrao
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        try:
            caminho.replace(caminho.with_suffix(caminho.suffix + ".corrompido"))
        except OSError:
            pass
        return padrao


def salvar_json(caminho: Path, dados):
    caminho = Path(caminho)
    tmp = caminho.with_suffix(caminho.suffix + ".tmp")
    tmp.write_text(json.dumps(dados, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(caminho)          # escrita atômica: não corrompe se o PC desligar


def carregar_config() -> dict:
    cfg = dict(CONFIG_PADRAO)
    cfg.update(ler_json(pasta_dados() / "config.json", {}))
    return cfg


def salvar_config(cfg: dict):
    salvar_json(pasta_dados() / "config.json", cfg)


# ═══════════════════════ utilidades de texto ═══════════════════════

def e(t) -> str:
    return html.escape(str(t), quote=False)


def cortar(t: str, n: int) -> str:
    t = str(t)
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def fmt_tamanho(b: float) -> str:
    for un in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024 or un == "TB":
            return f"{int(b)} B" if un == "B" else f"{b:.2f} {un}"
        b /= 1024


def fmt_gib_html(b: float) -> str:
    return f"{b / 1024 ** 3:.2f} <i>GiB</i>" if b >= 1024 ** 3 else f"{b / MIB:.2f} <i>MiB</i>"


def fmt_duracao(s: float) -> str:
    s = int(round(s))
    h, m, s = s // 3600, s % 3600 // 60, s % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def ordem_natural(texto: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", texto)]


def sem_acentos(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", t) if not unicodedata.combining(c))


def limpar_tag(texto: str) -> str:
    return re.sub(r"\W+", "_", texto, flags=re.UNICODE).strip("_")


def nome_seguro(nome: str, limite: int = 110) -> str:
    nome = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", nome).strip(" .")
    stem, ext = os.path.splitext(nome)
    return (stem[:limite].rstrip() or "arquivo") + ext


def sugerir_prefixo(nome: str) -> str:
    palavras = [p for p in re.split(r"[^A-Za-z0-9]+", sem_acentos(nome)) if p]
    ignorar = {"de", "da", "do", "das", "dos", "e", "a", "o", "the", "of", "and", "com", "para"}
    uteis = [p for p in palavras if p.lower() not in ignorar] or palavras
    if not uteis:
        return "C"
    if len(uteis) == 1:
        return uteis[0][:6].upper()
    return "".join(p[0] for p in uteis[:5]).upper()


def prefixo_unico(prefixo: str, usados: set) -> str:
    prefixo = limpar_tag(prefixo)
    if not prefixo:
        return ""
    base, n = prefixo, 2
    while prefixo.lower() in {u.lower() for u in usados}:
        prefixo = f"{base}{n}"
        n += 1
    return prefixo


def nome_no_zip(info: zipfile.ZipInfo) -> str:
    """Corrige acentos de zips criados no Windows (codificação antiga)."""
    if info.flag_bits & 0x800:
        nome = info.filename
    else:
        try:
            nome = info.filename.encode("cp437").decode("utf-8")
        except UnicodeError:
            nome = info.filename.encode("cp437").decode("cp850", errors="replace")
    return nome.replace("\\", "/")


# ═══════════════════════ FFmpeg ═══════════════════════

_ffmpeg_cache: str | None = None
_procs: set = set()
_procs_lock = threading.Lock()


def caminho_ffmpeg() -> str:
    global _ffmpeg_cache
    if _ffmpeg_cache:
        return _ffmpeg_cache
    candidatos = [os.environ.get("GALOCHAT_FFMPEG")]
    try:
        import imageio_ffmpeg
        candidatos.append(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        pass
    candidatos.append(shutil.which("ffmpeg"))
    for c in candidatos:
        if c and Path(c).exists():
            _ffmpeg_cache = str(c)
            return _ffmpeg_cache
    raise RuntimeError("FFmpeg não encontrado. Reinstale o GALOCHAT ou instale o FFmpeg no sistema.")


def rodar(cmd: list, timeout: float | None = None):
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         encoding="utf-8", errors="replace", creationflags=flags)
    with _procs_lock:
        _procs.add(p)
    try:
        out, err = p.communicate(timeout=timeout)
    finally:
        with _procs_lock:
            _procs.discard(p)
    return subprocess.CompletedProcess(cmd, p.returncode, out, err)


def matar_processos():
    """Interrompe qualquer FFmpeg em andamento (botão Parar)."""
    with _procs_lock:
        for p in list(_procs):
            try:
                p.kill()
            except Exception:
                pass


def sondar(caminho) -> dict | None:
    """Lê codec, resolução e duração usando só o ffmpeg (sem precisar do ffprobe)."""
    r = rodar([caminho_ffmpeg(), "-hide_banner", "-i", str(caminho)])
    txt = r.stderr or ""
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", txt)
    dur = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else 0.0
    codec, w, h = "", 0, 0
    for linha in txt.splitlines():
        if "Video:" in linha and "attached pic" not in linha:
            resto = linha[linha.index("Video:"):]
            mc = re.search(r"Video:\s*([\w\-]+)", resto)
            mr = re.search(r"\b(\d{2,5})x(\d{2,5})\b", resto)
            if mc and mr:
                codec, w, h = mc[1], int(mr[1]), int(mr[2])
                break
    if not codec:
        return None
    mrot = re.search(r"rotation of (-?[\d.]+) degrees", txt) or re.search(r"rotate\s*:\s*(-?\d+)", txt)
    rot = int(round(float(mrot[1]))) if mrot else 0
    if abs(rot) % 180 == 90:
        w, h = h, w
    return {"w": w, "h": h, "codec": codec, "dur": dur}


def preparar_mp4(origem: Path, info: dict, cfg: dict, destino: Path, emit=None):
    """Devolve (arquivo, pode_ser_video). Quando dá, só troca o contêiner (sem perda)."""
    ff = caminho_ffmpeg()
    base = [ff, "-y", "-v", "error", "-i", str(origem), "-map", "0:v:0", "-map", "0:a?"]
    tag = ["-tag:v", "hvc1"] if info["codec"] == "hevc" else []
    fim = ["-movflags", "+faststart", str(destino)]
    if info["codec"] in ("h264", "hevc"):
        if origem.suffix.lower() == ".mp4" and not cfg.get("otimizar_streaming", True):
            return origem, True
        if emit:
            emit("etapa", texto="Preparando MP4 (sem perda de qualidade)…")
        if rodar(base + ["-c", "copy"] + tag + fim).returncode == 0:
            return destino, True
        if rodar(base + ["-c:v", "copy"] + tag + ["-c:a", "aac", "-b:a", "192k"] + fim).returncode == 0:
            return destino, True
        return origem, False
    if cfg.get("converter_incompativeis", True):
        if emit:
            emit("etapa", texto=f"Convertendo {info['codec']} para H.264 (pode demorar)…")
        cmd = base + ["-c:v", "libx264", "-preset", str(cfg.get("preset_x264", "veryfast")),
                      "-crf", str(cfg.get("crf_x264", 21)), "-pix_fmt", "yuv420p",
                      "-c:a", "aac", "-b:a", "192k"] + fim
        if rodar(cmd).returncode == 0:
            return destino, True
    return origem, False


def dividir_video(caminho: Path, info: dict, limite: int, pasta: Path, nome_base: str, emit=None,
                  cfg: dict | None = None) -> list:
    """Corta pelo TEMPO (cada parte toca sozinha). Mantém o arquivo se já couber no limite."""
    if caminho.stat().st_size <= limite:
        return [caminho]
    if info["dur"] <= 0:
        raise RuntimeError("não consegui descobrir a duração para dividir o vídeo")
    segdir = pasta / "cortes"
    n = math.ceil(caminho.stat().st_size / (limite * 0.9))
    for _ in range(5):
        shutil.rmtree(segdir, ignore_errors=True)
        segdir.mkdir(parents=True)
        if emit:
            emit("etapa", texto=f"Dividindo o vídeo em ~{n} partes…")
        rodar([caminho_ffmpeg(), "-y", "-v", "error", "-i", str(caminho), "-map", "0", "-c", "copy",
               "-f", "segment", "-segment_time", f"{info['dur'] / n:.2f}", "-reset_timestamps", "1",
               "-segment_format_options", "movflags=+faststart", str(segdir / "seg_%03d.mp4")])
        segs = sorted(segdir.glob("seg_*.mp4"))
        if segs and all(s.stat().st_size <= limite for s in segs):
            partes = []
            for i, s in enumerate(segs, 1):
                novo = segdir / nome_seguro(f"{nome_base} (parte {i}).mp4")
                s.rename(novo)
                partes.append(novo)
            return partes
        n += max(1, n // 2)       # os cortes caem em quadros-chave; tenta com mais partes

    # Último recurso (vídeo com poucos quadros-chave): recodifica já cortando em pontos exatos.
    cfg = {**CONFIG_PADRAO, **(cfg or {})}
    n = math.ceil(caminho.stat().st_size / (limite * 0.8))
    for _ in range(3):
        seg_s = info["dur"] / n
        shutil.rmtree(segdir, ignore_errors=True)
        segdir.mkdir(parents=True)
        if emit:
            emit("etapa", texto=f"Recodificando para dividir em ~{n} partes (pode demorar)…")
        rodar([caminho_ffmpeg(), "-y", "-v", "error", "-i", str(caminho), "-map", "0:v:0", "-map", "0:a?",
               "-c:v", "libx264", "-preset", str(cfg["preset_x264"]), "-crf", str(cfg["crf_x264"]),
               "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
               "-force_key_frames", f"expr:gte(t,n_forced*{seg_s:.3f})",
               "-f", "segment", "-segment_time", f"{seg_s:.3f}", "-reset_timestamps", "1",
               "-segment_format_options", "movflags=+faststart", str(segdir / "seg_%03d.mp4")])
        segs = sorted(segdir.glob("seg_*.mp4"))
        if segs and all(s_.stat().st_size <= limite for s_ in segs):
            partes = []
            for i, s_ in enumerate(segs, 1):
                novo = segdir / nome_seguro(f"{nome_base} (parte {i}).mp4")
                s_.rename(novo)
                partes.append(novo)
            return partes
        n += max(1, n // 2)
    raise RuntimeError("não consegui cortar o vídeo dentro do limite do Telegram")


def dividir_bytes(arquivo: Path, limite: int, pasta: Path, nome_original: str) -> list:
    segdir = pasta / "cortes"
    segdir.mkdir(parents=True, exist_ok=True)
    partes = []
    with open(arquivo, "rb") as f:
        n = 1
        while True:
            destino = segdir / nome_seguro(f"{nome_original}.{n:03d}", 150)
            escrito = 0
            with open(destino, "wb") as out:
                while escrito < limite and (b := f.read(min(8 * MIB, limite - escrito))):
                    out.write(b)
                    escrito += len(b)
            if escrito == 0:
                destino.unlink()
                break
            partes.append(destino)
            n += 1
    return partes


def gerar_miniatura(video: Path, dur: float, pasta: Path, n: int) -> Path | None:
    thumb = pasta / f"miniatura_{n}.jpg"
    ss = min(max(dur * 0.1, 0), 10)
    rodar([caminho_ffmpeg(), "-y", "-v", "error", "-ss", f"{ss:.2f}", "-i", str(video), "-frames:v", "1",
           "-vf", "scale=320:320:force_original_aspect_ratio=decrease", "-q:v", "4", str(thumb)])
    return thumb if thumb.exists() else None


def gerar_quadro_capa(video: Path, dur: float, destino: Path) -> Path | None:
    ss = min(max(dur * 0.1, 0), 30)
    rodar([caminho_ffmpeg(), "-y", "-v", "error", "-ss", f"{ss:.2f}", "-i", str(video), "-frames:v", "1",
           "-vf", "scale='min(1280,iw)':-2", "-q:v", "3", str(destino)])
    return destino if destino.exists() else None


# ═══════════════════════ descoberta e plano ═══════════════════════

def tem_conteudo(pasta: Path) -> bool:
    for raiz, dirs, arquivos in os.walk(pasta):
        dirs[:] = [d for d in dirs if d != PASTA_ENVIADOS]
        for a in arquivos:
            if Path(a).suffix.lower() in EXT_VIDEO or a.lower().endswith(".zip"):
                return True
    return False


def fontes_da_pasta(pasta: Path) -> list:
    """Uma pasta vira uma fonte 'pasta' + cada .zip dentro dela vira uma fonte 'zip'."""
    pasta = Path(pasta)
    zips = sorted((z for z in pasta.rglob("*.zip")
                   if z.is_file() and PASTA_ENVIADOS not in z.relative_to(pasta).parts),
                  key=lambda p: ordem_natural(str(p)))
    return [{"tipo": "pasta", "caminho": str(pasta)}] + [{"tipo": "zip", "caminho": str(z)} for z in zips]


def _membros(fonte: dict) -> list:
    """[(arc, nome_exibicao, tamanho)] dos arquivos de uma fonte."""
    caminho = Path(fonte["caminho"])
    if fonte["tipo"] == "zip":
        try:
            with zipfile.ZipFile(caminho) as zf:
                saida = []
                for m in zf.infolist():
                    if m.is_dir():
                        continue
                    if m.flag_bits & 0x1:
                        raise RuntimeError(f"«{caminho.name}» tem senha. Extraia-o antes e adicione a pasta.")
                    saida.append((m.filename, nome_no_zip(m), m.file_size))
                return saida
        except zipfile.BadZipFile:
            raise RuntimeError(f"«{caminho.name}» está corrompido ou não é um .zip válido.")
    saida = []
    for raiz, dirs, arquivos in os.walk(caminho):
        dirs[:] = sorted(d for d in dirs if d != PASTA_ENVIADOS)
        for a in sorted(arquivos):
            if a.lower().endswith(".zip"):
                continue                        # zips da pasta são fontes à parte
            p = Path(raiz) / a
            rel = p.relative_to(caminho).as_posix()
            try:
                saida.append((rel, rel, p.stat().st_size))
            except OSError:
                pass
    return saida


def analisar_colecao(fontes: list, nome: str | None = None, cfg: dict | None = None) -> dict:
    """Lê as fontes e devolve a coleção com módulos e aulas (ainda sem hashtags)."""
    cfg = {**CONFIG_PADRAO, **(cfg or {})}
    itens, capa_interna, total = [], None, 0
    for fonte in fontes:
        membros = _membros(fonte)
        caminhos = [PurePosixPath(n).parts for _, n, _ in membros]
        corte = 0
        if fonte["tipo"] == "zip" and caminhos and all(len(p) > 1 for p in caminhos) \
                and len({p[0] for p in caminhos}) == 1:
            corte = 1                           # remove a pasta raiz única que o zip costuma ter
        for (arc, _nome, tam), partes in zip(membros, caminhos):
            partes = partes[corte:]
            if not partes or "__MACOSX" in partes:
                continue
            arq = partes[-1]
            ext = Path(arq).suffix.lower()
            if arq.startswith(".") or arq.lower() in IGNORAR_NOMES or ext in IGNORAR_EXT:
                continue
            if ext in EXT_IMG and Path(arq).stem.lower() in NOMES_CAPA:
                if capa_interna is None:
                    capa_interna = {"fonte": fonte["caminho"], "fonte_tipo": fonte["tipo"], "arc": arc}
                continue
            tipo = "video" if ext in EXT_VIDEO else "doc"
            if tipo == "doc" and not cfg.get("enviar_documentos", True):
                continue
            itens.append({"fonte": fonte["caminho"], "fonte_tipo": fonte["tipo"], "arc": arc,
                          "arquivo": arq, "modulo": list(partes[:-1]), "tipo": tipo, "tamanho": tam,
                          "_ordem": [ordem_natural(p) for p in partes]})
            total += tam
    itens.sort(key=lambda i: i["_ordem"])
    for i in itens:
        del i["_ordem"]
        i["id"] = f"{i['fonte']}::{i['arc']}"

    primeira = Path(fontes[0]["caminho"])
    assinatura = "|".join(f"{f['caminho']}:{len(itens)}:{total}" for f in fontes)
    return {
        "id": hashlib.sha1(assinatura.encode("utf-8")).hexdigest()[:16],
        "nome": nome or (primeira.stem if fontes[0]["tipo"] == "zip" else primeira.name),
        "categoria": cfg["categoria_padrao"],
        "tipo": cfg["tipo_padrao"],
        "prefixo": "",
        "capa": None,
        "capa_interna": capa_interna,
        "fontes": fontes,
        "itens": itens,
        "tamanho_total": total,
        "marcada": True,
    }


def atribuir_tags(itens: list, prefixo: str = ""):
    p = limpar_tag(prefixo)
    p = f"{p}_" if p else ""
    nv = nd = 0
    for i in itens:
        if i["tipo"] == "video":
            nv += 1
            i["tag"] = f"#{p}F{nv:03d}"
        else:
            nd += 1
            i["tag"] = f"#{p}Doc{nd:03d}"


def prefixos_usados(canal_chave: str) -> set:
    """Prefixos de hashtag que já existem neste canal (lidos do registro)."""
    usados = set()
    for chave, reg in ler_json(pasta_dados() / "registro.json", {}).items():
        if chave.startswith(f"{canal_chave}::") and reg.get("itens"):
            m = re.match(r"#(.*?)_?(?:F|Doc)\d+$", reg["itens"][0].get("tag", ""))
            if m and m[1]:
                usados.add(m[1])
    return usados


def ja_publicado(canal_chave: str, colecao_id: str) -> bool:
    reg = ler_json(pasta_dados() / "registro.json", {}).get(f"{canal_chave}::{colecao_id}")
    return bool(reg and reg.get("completo"))


# ═══════════════════════ textos das mensagens ═══════════════════════

def legenda_capa(nome: str, categoria: str, tipo: str, tamanho: int) -> str:
    return (f"⭐ <b>Nome:</b> {e(cortar(nome, 200))}\n\n"
            f"<blockquote>🏛 <b>Categoria:</b> <i>{e(cortar(categoria, 60))}</i>\n"
            f"💠 <b>Tipo:</b> #{limpar_tag(tipo) or 'Curso'}\n"
            f"💽 <b>Tamanho:</b> {fmt_gib_html(tamanho)}</blockquote>")


def legenda_item(item: dict, n: int, total: int, cfg: dict) -> str:
    nome = item["arquivo"] if item["tipo"] == "doc" else Path(item["arquivo"]).stem
    ass = f" {cfg['assinatura']}" if cfg.get("assinatura") else ""
    linhas = [f"{item['tag']} {e(cortar(nome, 180))}{e(cortar(ass, 60))}"]
    if total > 1:
        linhas.append(f"🧩 Parte {n}/{total}")
    mod = item["modulo"]
    if mod:
        linhas += ["", e(cortar(mod[0], 100))] + [f"={e(cortar(m, 100))}" for m in mod[1:4]]
    texto = "\n".join(linhas)
    return texto if len(texto) <= 1000 else "\n".join(linhas[:2])


def _juntar_blocos(cabecalho: str, blocos: list, limite: int = 3800) -> list:
    mensagens, atual = [], cabecalho
    for b in blocos:
        if len(atual) + len(b) + 2 > limite:
            mensagens.append(atual)
            atual = ""
        atual += "\n" + b + "\n"
    mensagens.append(atual)
    return mensagens


def montar_guia(nome: str, itens: list, cfg: dict) -> list:
    cab = (f"<b>{e(cortar(nome, 200))}</b>\n🏆 <b>GUIA DE NAVEGAÇÃO</b>\n\n"
           f"❤️‍🔥 <b>{e(cfg.get('boas_vindas') or CONFIG_PADRAO['boas_vindas'])}</b>\n")
    blocos = []
    docs = [i["tag"] for i in itens if i["tipo"] == "doc"]
    for k in range(0, len(docs), 150):
        blocos.append("Documents\n" + " ".join(docs[k:k + 150]))
    grupos: dict = {}
    for i in itens:
        if i["tipo"] == "video":
            grupos.setdefault(tuple(i["modulo"]), []).append(i["tag"])
    for mod, tags in grupos.items():
        titulo = " › ".join(mod) if mod else "Aulas"
        for k in range(0, len(tags), 150):
            blocos.append(f"= {e(cortar(titulo, 200))}\n" + " ".join(tags[k:k + 150]))
    return _juntar_blocos(cab, blocos)


def link_mensagem(entidade, msg_id: int) -> str | None:
    usuario = getattr(entidade, "username", None)
    if usuario:
        return f"https://t.me/{usuario}/{msg_id}"
    if isinstance(entidade, Channel):
        return f"https://t.me/c/{entidade.id}/{msg_id}"
    return None


def montar_indice(registro: dict, canal_chave: str) -> list:
    por_cat: dict = {}
    for chave, reg in registro.items():
        if chave.startswith(f"{canal_chave}::") and reg.get("completo"):
            por_cat.setdefault(reg.get("categoria") or "Geral", []).append(reg)
    cab = "📚 <b>ÍNDICE DO CANAL</b>\n"
    blocos = []
    for cat in sorted(por_cat, key=ordem_natural):
        linhas = [f"<b>{e(cat)}</b>"]
        for reg in sorted(por_cat[cat], key=lambda r: ordem_natural(r["nome"])):
            nome = e(cortar(reg["nome"], 120))
            link = reg.get("capa_link")
            linhas.append(f'• <a href="{link}">{nome}</a>' if link else f"• {nome}")
        blocos.append("\n".join(linhas))
    return _juntar_blocos(cab, blocos) if blocos else []


# ═══════════════════════ Telegram: conta e destino ═══════════════════════

def traduzir_erro(ex: BaseException) -> str:
    mapa = [
        (errors.ApiIdInvalidError, "API ID/Hash inválidos. Copie de novo em my.telegram.org."),
        (errors.PhoneNumberInvalidError, "Número de telefone inválido. Use o formato +5511999999999."),
        (errors.PhoneCodeInvalidError, "Código incorreto. Confira a mensagem recebida no Telegram."),
        (errors.PhoneCodeExpiredError, "O código expirou. Peça um novo código."),
        (errors.PasswordHashInvalidError, "Senha da verificação em duas etapas incorreta."),
        (errors.ChatWriteForbiddenError, "Sem permissão para postar neste canal."),
        (errors.ChatAdminRequiredError, "Você precisa ser administrador do canal."),
        (errors.ChannelPrivateError, "Canal inacessível. Ele ainda existe e você faz parte dele?"),
        (errors.FilePartsInvalidError, "Arquivo grande demais para a sua conta do Telegram."),
    ]
    for tipo, msg in mapa:
        if isinstance(ex, tipo):
            return msg
    if isinstance(ex, errors.FloodWaitError):
        return f"O Telegram pediu uma pausa de {ex.seconds}s."
    return str(ex) or ex.__class__.__name__


class SessaoTelegram:
    """Conexão com o Telegram (uma só, reaproveitada em todas as operações)."""

    def __init__(self, pasta: Path | None = None):
        self.pasta = Path(pasta) if pasta else pasta_dados()
        self.client: TelegramClient | None = None
        self.telefone = ""

    async def conectar(self, api_id, api_hash):
        await self.desconectar()
        self.client = TelegramClient(str(self.pasta / "sessao"), int(api_id), str(api_hash).strip(),
                                     device_model=APP_NOME, app_version=VERSAO)
        await self.client.connect()
        if await self.client.is_user_authorized():
            return await self._usuario()
        return None

    async def desconectar(self):
        if self.client is not None:
            try:
                await self.client.disconnect()
            except Exception:
                pass
            self.client = None

    async def _usuario(self) -> dict:
        eu = await self.client.get_me()
        nome = " ".join(x for x in (eu.first_name, eu.last_name) if x) or "sem nome"
        return {"nome": nome, "usuario": eu.username, "premium": bool(getattr(eu, "premium", False))}

    async def enviar_codigo(self, telefone: str):
        self.telefone = telefone.strip()
        await self.client.send_code_request(self.telefone)

    async def entrar_codigo(self, codigo: str):
        try:
            await self.client.sign_in(self.telefone, codigo.strip())
        except errors.SessionPasswordNeededError:
            return "SENHA"
        return await self._usuario()

    async def entrar_senha(self, senha: str):
        await self.client.sign_in(password=senha)
        return await self._usuario()

    async def sair(self):
        try:
            if self.client:
                await self.client.log_out()
        finally:
            await self.desconectar()
            for f in self.pasta.glob("sessao.session*"):
                try:
                    f.unlink()
                except OSError:
                    pass

    async def destinos(self) -> list:
        lista = [{"id": "me", "titulo": "Mensagens Salvas (só você vê)", "username": None}]
        async for d in self.client.iter_dialogs():
            ent = d.entity
            if isinstance(ent, Channel) and ent.broadcast:
                pode = ent.creator or (ent.admin_rights is not None and ent.admin_rights.post_messages)
                if pode:
                    lista.append({"id": ent.id, "titulo": d.title, "username": ent.username})
        return lista

    async def criar_canal(self, titulo: str) -> dict:
        res = await self.client(CreateChannelRequest(title=titulo.strip(), about="", broadcast=True))
        ent = res.chats[0]
        return {"id": ent.id, "titulo": titulo.strip(), "username": None}

    async def entidade(self, destino: dict):
        if destino["id"] == "me":
            return "me"
        return await self.client.get_entity(PeerChannel(int(destino["id"])))


# ═══════════════════════ publicação ═══════════════════════

async def com_retry(fn, emit):
    tentativas = 0
    while True:
        try:
            return await fn()
        except errors.FloodWaitError as ex:
            emit("log", texto=f"⏳ O Telegram pediu uma pausa de {ex.seconds}s. Aguardando…")
            await asyncio.sleep(ex.seconds + 3)
        except (ConnectionError, OSError, asyncio.TimeoutError) as ex:
            tentativas += 1
            if tentativas > 5:
                raise
            emit("log", texto=f"⚠ Conexão instável ({ex.__class__.__name__}). Nova tentativa em 20s ({tentativas}/5)…")
            await asyncio.sleep(20)


def checar_espaco(pasta: Path, necessario: int):
    livre = shutil.disk_usage(pasta).free
    if livre < necessario:
        raise RuntimeError(f"Pouco espaço em disco: preciso de ~{fmt_tamanho(necessario)} livres "
                           f"e só há {fmt_tamanho(livre)} em {pasta}.")


def extrair_membro(zf: zipfile.ZipFile, arc: str, destino: Path, cb=None):
    info = zf.getinfo(arc)
    total, lido, ultimo = max(info.file_size, 1), 0, 0.0
    with zf.open(info) as src, open(destino, "wb") as dst:
        while bloco := src.read(8 * MIB):
            dst.write(bloco)
            lido += len(bloco)
            if cb and time.time() - ultimo > 0.3:
                cb(lido / total)
                ultimo = time.time()


class Publicador:
    def __init__(self, client, entidade, canal_chave: str, cfg: dict, emit, limite_bytes: int,
                 registro_path: Path | None = None, pasta_trabalho: Path | None = None):
        self.client, self.ent, self.canal_chave = client, entidade, canal_chave
        self.cfg, self.emit, self.limite = cfg, emit, limite_bytes
        self.registro_path = Path(registro_path or pasta_dados() / "registro.json")
        self.registro = ler_json(self.registro_path, {})
        self.tmp = Path(pasta_trabalho or pasta_dados() / "tmp")
        self.feitos = self.total_itens = 0

    def salvar(self):
        salvar_json(self.registro_path, self.registro)

    # ── geral ──
    async def publicar(self, colecoes: list) -> dict:
        resumo = {"publicados": 0, "pulados": 0, "incompletos": 0, "falhas": 0}
        self.total_itens = sum(len(c["itens"]) for c in colecoes) or 1
        self.feitos = 0
        shutil.rmtree(self.tmp, ignore_errors=True)
        self.tmp.mkdir(parents=True, exist_ok=True)
        try:
            for ci, col in enumerate(colecoes, 1):
                self.emit("log", texto=f"━━ [{ci}/{len(colecoes)}] {col['nome']}")
                try:
                    r = await self._colecao(col)
                except asyncio.CancelledError:
                    raise
                except Exception as ex:
                    self.emit("log", texto=f"✖ Falhou: {traduzir_erro(ex)}")
                    r = "falha"
                resumo[{"ok": "publicados", "pulado": "pulados", "incompleto": "incompletos",
                        "falha": "falhas"}[r]] += 1
                self.emit("colecao_fim", id=col["id"], resultado=r)
            if self.cfg.get("indice") and resumo["publicados"]:
                await self._indice()
        finally:
            shutil.rmtree(self.tmp, ignore_errors=True)
        return resumo

    def _progresso_total(self):
        self.emit("total", feitos=self.feitos, total=self.total_itens)

    # ── uma coleção ──
    async def _colecao(self, col: dict) -> str:
        chave = f"{self.canal_chave}::{col['id']}"
        reg = self.registro.get(chave)
        if reg and reg.get("completo"):
            self.emit("log", texto="✔ Já está publicado neste canal. Pulando.")
            self.feitos += len(col["itens"])
            self._progresso_total()
            return "pulado"
        if not col["itens"]:
            self.emit("log", texto="Nada para publicar nesta coleção.")
            return "falha"
        if not reg:
            reg = {"nome": col["nome"], "categoria": col["categoria"], "tipo": col["tipo"],
                   "itens": col["itens"], "tamanho_total": col["tamanho_total"], "estado": {},
                   "completo": False, "criado_em": datetime.now().isoformat(timespec="seconds")}
            self.registro[chave] = reg
            self.salvar()
        else:
            self.emit("log", texto="↻ Retomando de onde parou.")
        itens = reg["itens"]
        zips: dict = {}
        try:
            for it in itens:
                if it["fonte_tipo"] == "zip" and it["fonte"] not in zips:
                    zips[it["fonte"]] = zipfile.ZipFile(it["fonte"])
            if "capa_msg" not in reg:
                await self._capa(col, reg, zips)
            for i, it in enumerate(itens, 1):
                est = reg["estado"].setdefault(it["id"], {"completo": False, "partes": {}})
                if est["completo"]:
                    self.feitos += 1
                    self._progresso_total()
                    continue
                self.emit("item", n=i, total=len(itens), texto=f"{it['tag']}  {it['arquivo']}")
                try:
                    await self._item(reg, it, est, zips)
                except asyncio.CancelledError:
                    raise
                except Exception as ex:
                    self.emit("log", texto=f"✖ {it['arquivo']}: {traduzir_erro(ex)}")
                self.feitos += 1
                self._progresso_total()
        finally:
            for z in zips.values():
                z.close()

        pendentes = [i for i in itens if not reg["estado"].get(i["id"], {}).get("completo")]
        if pendentes:
            self.emit("log", texto=f"⏸ {len(pendentes)} item(ns) não foram enviados. "
                                   "Clique em Publicar de novo para tentar outra vez; o guia só sai com tudo no ar.")
            return "incompleto"
        await self._guia(reg)
        reg["completo"] = True
        reg["publicado_em"] = datetime.now().isoformat(timespec="seconds")
        self.salvar()
        self.emit("log", texto="✅ Curso publicado!")
        if self.cfg.get("depois") == "mover":
            self._mover_fontes(col)
        return "ok"

    # ── capa ──
    async def _capa(self, col: dict, reg: dict, zips: dict):
        self.emit("etapa", texto="Publicando a capa…")
        legenda = legenda_capa(reg["nome"], reg["categoria"], reg["tipo"], reg["tamanho_total"])
        imagem = None
        pasta = self.tmp / "capa"
        pasta.mkdir(parents=True, exist_ok=True)
        if col.get("capa") and Path(col["capa"]).exists():
            imagem = Path(col["capa"])
        elif col.get("capa_interna"):
            ci = col["capa_interna"]
            destino = pasta / ("capa" + Path(ci["arc"]).suffix.lower())
            try:
                if ci["fonte_tipo"] == "zip":
                    zf = zips.get(ci["fonte"]) or zipfile.ZipFile(ci["fonte"])
                    await asyncio.to_thread(extrair_membro, zf, ci["arc"], destino)
                else:
                    shutil.copyfile(Path(ci["fonte"]) / ci["arc"], destino)
                imagem = destino
            except Exception:
                imagem = None
        if imagem is None:                     # sem capa: usa um quadro do primeiro vídeo
            imagem = await self._quadro_do_primeiro_video(reg, zips, pasta)
        if imagem:
            msg = await com_retry(lambda: self.client.send_file(self.ent, str(imagem), caption=legenda,
                                                                parse_mode="html"), self.emit)
        else:
            msg = await com_retry(lambda: self.client.send_message(self.ent, legenda, parse_mode="html",
                                                                   link_preview=False), self.emit)
        reg["capa_msg"] = msg.id
        reg["capa_legenda"] = legenda
        reg["capa_link"] = link_mensagem(self.ent, msg.id)
        self.salvar()

    async def _quadro_do_primeiro_video(self, reg, zips, pasta):
        video = next((i for i in reg["itens"] if i["tipo"] == "video"), None)
        if not video:
            return None
        try:
            if video["fonte_tipo"] == "zip":
                origem = pasta / nome_seguro(video["arquivo"])
                await asyncio.to_thread(extrair_membro, zips[video["fonte"]], video["arc"], origem)
            else:
                origem = Path(video["fonte"]) / video["arc"]
            info = await asyncio.to_thread(sondar, origem)
            if not info:
                return None
            quadro = await asyncio.to_thread(gerar_quadro_capa, origem, info["dur"], pasta / "quadro.jpg")
            if video["fonte_tipo"] == "zip":
                origem.unlink(missing_ok=True)
            return quadro
        except Exception:
            return None

    # ── um vídeo ou documento ──
    async def _item(self, reg: dict, it: dict, est: dict, zips: dict):
        pasta = self.tmp / "item"
        shutil.rmtree(pasta, ignore_errors=True)
        pasta.mkdir(parents=True)
        emit = self.emit
        try:
            nome_local = nome_seguro(it["arquivo"])
            if it["fonte_tipo"] == "zip":
                checar_espaco(self.tmp, int(it["tamanho"] * 2.3) + 50 * MIB)
                (pasta / "origem").mkdir()
                bruto = pasta / "origem" / nome_local
                emit("etapa", texto="Extraindo do zip…")
                await asyncio.to_thread(extrair_membro, zips[it["fonte"]], it["arc"], bruto,
                                        lambda f: emit("arquivo", frac=f, texto="Extraindo do zip…"))
            else:
                bruto = Path(it["fonte"]) / it["arc"]
                checar_espaco(self.tmp, int(it["tamanho"] * 1.3) + 50 * MIB)

            como_video, arquivo, info = False, bruto, None
            if it["tipo"] == "video":
                info = await asyncio.to_thread(sondar, bruto)
                if info and info["dur"] > 0:
                    destino = pasta / nome_seguro(Path(it["arquivo"]).stem + ".mp4")
                    arquivo, como_video = await asyncio.to_thread(preparar_mp4, bruto, info, self.cfg,
                                                                  destino, emit)
                if not como_video:
                    emit("log", texto="⚠ Este formato não toca no player do Telegram; vai como arquivo.")

            if como_video:
                partes = await asyncio.to_thread(dividir_video, arquivo, info, self.limite, pasta,
                                                 Path(it["arquivo"]).stem, emit, self.cfg)
            elif arquivo.stat().st_size > self.limite:
                emit("etapa", texto="Dividindo o arquivo em partes…")
                partes = await asyncio.to_thread(dividir_bytes, arquivo, self.limite, pasta, it["arquivo"])
            else:
                partes = [arquivo]

            total = len(partes)
            for n, parte in enumerate(partes, 1):
                if str(n) in est["partes"]:
                    continue
                pinfo = (await asyncio.to_thread(sondar, parte) if total > 1 else info) if como_video else None
                thumb = (await asyncio.to_thread(gerar_miniatura, parte, pinfo["dur"], pasta, n)) if pinfo else None
                legenda = legenda_item(it, n, total, self.cfg)
                rotulo = f"parte {n}/{total}" if total > 1 else "arquivo"
                msg = await self._enviar(parte, legenda, rotulo, como_video, pinfo, thumb,
                                         dividido_em_bytes=(not como_video and total > 1))
                est["partes"][str(n)] = {"msg_id": msg.id, "link": link_mensagem(self.ent, msg.id)}
                self.salvar()
                await asyncio.sleep(0.5)
            est["completo"] = True
            self.salvar()
        finally:
            shutil.rmtree(pasta, ignore_errors=True)

    async def _enviar(self, caminho: Path, legenda: str, rotulo: str, como_video: bool, info, thumb,
                      dividido_em_bytes=False):
        inicio, ultimo = time.time(), [0.0]

        def progresso(enviado, total):
            agora = time.time()
            if agora - ultimo[0] < 0.25 and enviado < total:
                return
            ultimo[0] = agora
            vel = enviado / MIB / max(agora - inicio, 0.001)
            self.emit("arquivo", frac=(enviado / total if total else 1),
                      texto=f"Enviando {rotulo}  ·  {enviado / MIB:.0f}/{total / MIB:.0f} MiB  ·  {vel:.1f} MiB/s")

        kw = {"caption": legenda, "parse_mode": "html", "progress_callback": progresso}
        if como_video:
            kw.update(supports_streaming=True, thumb=str(thumb) if thumb else None,
                      attributes=[DocumentAttributeVideo(duration=round(info["dur"]), w=info["w"], h=info["h"],
                                                         supports_streaming=True)])
        else:
            kw["force_document"] = True
        return await com_retry(lambda: self.client.send_file(self.ent, str(caminho), **kw), self.emit)

    # ── guia, índice, fixar ──
    async def _guia(self, reg: dict):
        if "guia_msgs" in reg:
            return
        self.emit("etapa", texto="Publicando o guia de navegação…")
        ids = []
        for texto in montar_guia(reg["nome"], reg["itens"], self.cfg):
            m = await com_retry(lambda t=texto: self.client.send_message(
                self.ent, t, parse_mode="html", link_preview=False), self.emit)
            ids.append(m.id)
        reg["guia_msgs"] = ids
        link = link_mensagem(self.ent, ids[0])
        if link and reg.get("capa_msg"):
            try:
                await self.client.edit_message(self.ent, reg["capa_msg"],
                                               reg["capa_legenda"] + f'\n\n📚 <a href="{link}">Guia de navegação</a>',
                                               parse_mode="html", link_preview=False)
            except Exception:
                pass
        if self.cfg.get("fixar", True) and not self.cfg.get("indice"):
            try:
                await self.client.pin_message(self.ent, ids[0], notify=False)
            except Exception as ex:
                self.emit("log", texto=f"(não consegui fixar o guia: {traduzir_erro(ex)})")
        self.salvar()

    async def _indice(self):
        textos = montar_indice(self.registro, self.canal_chave)
        if not textos:
            return
        self.emit("etapa", texto="Atualizando o índice do canal…")
        salvo = self.registro.setdefault("_indice", {})
        ids = salvo.get(self.canal_chave, [])
        novos = []
        for i, texto in enumerate(textos):
            if i < len(ids):
                try:
                    await self.client.edit_message(self.ent, ids[i], texto, parse_mode="html", link_preview=False)
                    novos.append(ids[i])
                    continue
                except errors.MessageNotModifiedError:
                    novos.append(ids[i])
                    continue
                except Exception:
                    pass
            m = await com_retry(lambda t=texto: self.client.send_message(
                self.ent, t, parse_mode="html", link_preview=False), self.emit)
            novos.append(m.id)
        sobras = [m for m in ids if m not in novos]
        if sobras:
            try:
                await self.client.delete_messages(self.ent, sobras)
            except Exception:
                pass
        if self.cfg.get("fixar", True) and (not ids or novos[0] != ids[0]):
            try:
                await self.client.pin_message(self.ent, novos[0], notify=False)
            except Exception:
                pass
        salvo[self.canal_chave] = novos
        self.salvar()
        self.emit("log", texto="📌 Índice do canal atualizado.")

    # ── depois de publicar ──
    def _mover_fontes(self, col: dict):
        caminhos = [Path(f["caminho"]) for f in col["fontes"]]
        topo = [c for c in caminhos
                if not any(o != c and o.is_dir() and o in c.parents for o in caminhos)]
        for c in topo:
            if not c.exists():
                continue
            destino = c.parent / PASTA_ENVIADOS / c.name
            destino.parent.mkdir(exist_ok=True)
            n = 2
            while destino.exists():
                destino = destino.with_name(f"{c.stem}_{n}{c.suffix}")
                n += 1
            try:
                shutil.move(str(c), str(destino))
                self.emit("log", texto=f"↪ «{c.name}» movido para {PASTA_ENVIADOS}/")
            except OSError as ex:
                self.emit("log", texto=f"(não consegui mover «{c.name}»: {ex})")


async def publicar(sessao: SessaoTelegram, destino: dict, colecoes: list, cfg: dict, emit,
                   limite_mb: int | None = None) -> dict:
    """Ponto de entrada usado pela interface."""
    caminho_ffmpeg()                                  # falha cedo se não houver FFmpeg
    ent = await sessao.entidade(destino)
    eu = await sessao.client.get_me()
    limite = int(limite_mb or (3900 if getattr(eu, "premium", False) else 1950)) * MIB
    emit("log", texto=f"Destino: {destino['titulo']}  ·  limite por arquivo: {limite // MIB} MiB")
    pub = Publicador(sessao.client, ent, str(destino["id"]), cfg, emit, limite)
    return await pub.publicar(colecoes)


# ═══════════════════════ autoteste ═══════════════════════

def autoteste() -> tuple[bool, list]:
    """Confere FFmpeg, leitura de vídeo e formatação de mensagens. Usado no build e na ajuda."""
    log, ok = [], True
    import tempfile
    try:
        ff = caminho_ffmpeg()
        v = rodar([ff, "-version"]).stdout.splitlines()[0]
        log.append(f"FFmpeg: {v}")
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            mkv = d / "teste.mkv"
            r = rodar([ff, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=15",
                       "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:v", "libx264",
                       "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(mkv)])
            if r.returncode != 0:
                raise RuntimeError("não consegui gerar o vídeo de teste: " + (r.stderr or "")[:200])
            info = sondar(mkv)
            log.append(f"Leitura do vídeo: {info}")
            assert info and info["codec"] == "h264" and (info["w"], info["h"]) == (320, 240)
            mp4 = d / "saida.mp4"
            arq, vid = preparar_mp4(mkv, info, CONFIG_PADRAO, mp4)
            assert vid and arq.exists(), "conversão para MP4 falhou"
            assert gerar_miniatura(arq, info["dur"], d, 1), "miniatura falhou"
            log.append("MP4 + miniatura: OK")
        from telethon.extensions import html as thtml
        _, ents = thtml.parse(legenda_capa("Teste", "Geral", "Curso", 5 * MIB))
        assert any(type(x).__name__ == "MessageEntityBlockquote" for x in ents)
        log.append("Formatação das mensagens: OK")
    except Exception as ex:
        ok = False
        log.append(f"FALHOU: {ex.__class__.__name__}: {ex}")
    return ok, log
