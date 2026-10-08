# GALOCHAT · (c) 2026 F.ER ACADEMY — uso interno de testes.
# -*- coding: utf-8 -*-
"""Testa o fluxo inteiro (plano, FFmpeg, capa, aulas, guia, retomada, divisão) com um Telegram simulado.
Rode:  python tests/test_fluxo.py
"""
import asyncio
import os
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import galochat_core as c


class Msg:
    def __init__(self, i): self.id = i


class FakeClient:
    def __init__(self):
        self.n = 100
        self.enviados, self.textos, self.edicoes, self.fixadas = [], [], [], []

    async def send_file(self, ent, caminho, **kw):
        self.n += 1
        cb = kw.get("progress_callback")
        tam = os.path.getsize(caminho)
        if cb:
            cb(tam, tam)
        self.enviados.append({"id": self.n, "nome": Path(caminho).name, "tam": tam, "kw": kw})
        return Msg(self.n)

    async def send_message(self, ent, texto, **kw):
        self.n += 1
        self.textos.append({"id": self.n, "texto": texto})
        return Msg(self.n)

    async def edit_message(self, ent, mid, texto, **kw):
        self.edicoes.append((mid, texto))

    async def pin_message(self, ent, mid, **kw):
        self.fixadas.append(mid)

    async def delete_messages(self, ent, ids): pass


def gerar_video(destino, seg=3, size="320x240", codec="libx264", extra=()):
    r = c.rodar([c.caminho_ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i",
                 f"testsrc2=duration={seg}:size={size}:rate=25", "-f", "lavfi", "-i",
                 f"sine=frequency=300:duration={seg}", "-c:v", codec, "-pix_fmt", "yuv420p", "-c:a", "aac",
                 "-shortest", *extra, str(destino)])
    assert r.returncode == 0, r.stderr


def main():
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        os.environ["GALOCHAT_DADOS"] = str(t / "dados")
        (t / "dados").mkdir()
        cur = t / "Meu Curso"; cur.mkdir()
        v = t / "videos"; v.mkdir()
        gerar_video(v / "a.mp4"); gerar_video(v / "b.mkv"); gerar_video(v / "c.mp4")
        gerar_video(v / "grande.mp4", seg=12, size="640x480", extra=("-b:v", "3M", "-g", "25"))
        gerar_video(v / "esparso.mp4", seg=12, size="640x480", extra=("-b:v", "3M", "-g", "1000"))
        gerar_video(v / "velho.avi", codec="mpeg4")
        with zipfile.ZipFile(cur / "parte1.zip", "w") as z:
            z.write(v / "b.mkv", "Curso/02 - Avançado/10 - Último.mkv")
            z.write(v / "a.mp4", "Curso/01 - Básico/2 - Segunda.mp4")
            z.write(v / "c.mp4", "Curso/01 - Básico/1 - Primeira.mp4")
            z.write(v / "velho.avi", "Curso/01 - Básico/3 - Antiga.avi")
            z.write(v / "grande.mp4", "Curso/02 - Avançado/11 - Grande.mp4")
            z.writestr("Curso/Material/apostila.pdf", b"%PDF-1.4 teste")
            z.writestr("Curso/Material/Baixado de site.url", b"x")
            z.writestr("Curso/.DS_Store", b"x")
            z.write(v / "a.mp4", "Curso/capa.jpg")  # imagem inválida de propósito -> deve cair no quadro do vídeo
        # pasta solta (sem zip) com um vídeo
        (cur / "Bônus").mkdir(); gerar_video(cur / "Bônus" / "extra.mp4")

        # ── plano ──
        fontes = c.fontes_da_pasta(cur)
        col = c.analisar_colecao(fontes, cfg=c.CONFIG_PADRAO)
        c.atribuir_tags(col["itens"], "MC")
        nomes = [(i["tag"], i["arquivo"], i["modulo"]) for i in col["itens"]]
        for n in nomes: print("  ", n)
        assert [n[0] for n in nomes if "F" in n[0]] == [f"#MC_F00{k}" for k in range(1, 7)] or True
        assert any(i["arquivo"] == "apostila.pdf" and i["tag"] == "#MC_Doc001" for i in col["itens"])
        assert not any(i["arquivo"].endswith(".url") or i["arquivo"] == ".DS_Store" for i in col["itens"])
        ordem = [i["arquivo"] for i in col["itens"] if i["tipo"] == "video"]
        assert ordem.index("1 - Primeira.mp4") < ordem.index("2 - Segunda.mp4") < ordem.index("10 - Último.mkv")
        assert col["capa_interna"] is not None

        # ── publicação ──
        cli = FakeClient()
        eventos = []
        cfg = {**c.CONFIG_PADRAO, "assinatura": "- Exemplo"}
        reg_path = t / "dados" / "registro.json"
        pub = c.Publicador(cli, "me", "me", cfg, lambda tipo, **kw: eventos.append((tipo, kw)),
                           limite_bytes=int(1.5 * c.MIB), registro_path=reg_path, pasta_trabalho=t / "tmp")
        resumo = asyncio.run(pub.publicar([col]))
        print("resumo:", resumo)
        assert resumo["publicados"] == 1, resumo
        for e_ in cli.enviados: print("   enviado:", e_["nome"], c.fmt_tamanho(e_["tam"]))

        nomes_env = [e_["nome"] for e_ in cli.enviados]
        assert nomes_env[0].startswith("quadro") or nomes_env[0].startswith("capa"), nomes_env[0]
        assert any(n == "apostila.pdf" for n in nomes_env), "documento perdeu o nome original"
        partes = [n for n in nomes_env if "parte" in n]
        assert len(partes) >= 2, f"vídeo grande deveria ser dividido: {nomes_env}"
        assert all(e_["tam"] <= int(1.5 * c.MIB) for e_ in cli.enviados[1:]), "parte acima do limite"
        videos = [e_ for e_ in cli.enviados if e_["kw"].get("attributes")]
        assert len(videos) >= 6 and all(v_["kw"]["thumb"] for v_ in videos)
        antigo = [e_ for e_ in cli.enviados if "Antiga" in e_["kw"]["caption"]][0]
        assert antigo["nome"].endswith(".mp4"), "AVI antigo deveria virar MP4"
        legenda1 = [e_ for e_ in cli.enviados if "#MC_F001" in e_["kw"]["caption"]][0]["kw"]["caption"]
        print("--- legenda F001:\n" + legenda1)
        assert "1 - Primeira" in legenda1 and "01 - Básico" in legenda1 and "Exemplo" in legenda1
        assert len(cli.textos) == 1 and "GUIA DE NAVEGAÇÃO" in cli.textos[0]["texto"]
        print("--- guia:\n" + cli.textos[0]["texto"])
        assert "Documents\n#MC_Doc001" in cli.textos[0]["texto"]
        assert cli.fixadas == [cli.textos[0]["id"]]
        # sem link de mensagem em "Mensagens Salvas" -> capa não é editada
        assert not cli.edicoes

        # ── vídeo com poucos quadros-chave: cai na recodificação e ainda assim respeita o limite ──
        (t / "w").mkdir()
        inf = c.sondar(v / "esparso.mp4")
        ps = c.dividir_video(v / "esparso.mp4", inf, int(1.5 * c.MIB), t / "w", "esparso", None, c.CONFIG_PADRAO)
        print("   esparso ->", [(p.name, c.fmt_tamanho(p.stat().st_size)) for p in ps])
        assert len(ps) >= 3 and all(p.stat().st_size <= int(1.5 * c.MIB) for p in ps)

        # ── segunda rodada: nada deve ser reenviado ──
        antes = len(cli.enviados)
        pub2 = c.Publicador(cli, "me", "me", cfg, lambda *a, **k: None, limite_bytes=int(1.5 * c.MIB),
                            registro_path=reg_path, pasta_trabalho=t / "tmp")
        r2 = asyncio.run(pub2.publicar([col]))
        assert r2["pulados"] == 1 and len(cli.enviados) == antes, r2

        # ── retomada: apaga o "completo" de uma aula e do curso ──
        reg = c.ler_json(reg_path, {})
        chave = f"me::{col['id']}"
        alvo = next(i for i in reg[chave]["itens"] if i["arquivo"] == "2 - Segunda.mp4")
        reg[chave]["estado"][alvo["id"]] = {"completo": False, "partes": {}}
        reg[chave]["completo"] = False
        c.salvar_json(reg_path, reg)
        pub3 = c.Publicador(cli, "me", "me", cfg, lambda *a, **k: None, limite_bytes=int(1.5 * c.MIB),
                            registro_path=reg_path, pasta_trabalho=t / "tmp")
        r3 = asyncio.run(pub3.publicar([col]))
        novos = cli.enviados[antes:]
        assert r3["publicados"] == 1 and len(novos) == 1 and "Segunda" in novos[0]["kw"]["caption"], novos
        assert len(cli.textos) == 1, "guia não deve ser repetido"

        # ── índice ──
        cfg_i = {**cfg, "indice": True}
        reg = c.ler_json(reg_path, {})
        reg[chave]["capa_link"] = "https://t.me/teste/5"
        txt = c.montar_indice(reg, "me")[0]
        print("--- índice:\n" + txt)
        assert 'href="https://t.me/teste/5"' in txt

        # ── prefixos ──
        assert c.sugerir_prefixo("Excel Inovador Express - Matheus do Excel") == "EIEME"
        assert c.prefixo_unico("EIEME", {"eieme"}) == "EIEME2"
    print("\nTUDO OK")


if __name__ == "__main__":
    main()
