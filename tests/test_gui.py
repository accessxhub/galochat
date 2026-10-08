# GALOCHAT · (c) 2026 F.ER ACADEMY — uso interno de testes.
# -*- coding: utf-8 -*-
"""Teste da interface com Telegram simulado. Rode com tela virtual:
   xvfb-run -a -s "-screen 0 1280x900x24" python3 tests/test_gui.py
"""
import os, sys, tempfile, time, types, zipfile, subprocess
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent)); sys.path.insert(0, str(AQUI))
tmp = Path(tempfile.mkdtemp())
os.environ["GALOCHAT_DADOS"] = str(tmp / "dados")
SHOTS = Path(os.environ.get("SHOTS", tmp / "shots")); SHOTS.mkdir(parents=True, exist_ok=True)

import galochat_core as c
c.salvar_config({**c.CONFIG_PADRAO, "aviso_aceito": True, "api_id": "123", "api_hash": "x" * 32,
                 "destino": {"id": "me", "titulo": "Mensagens Salvas (só você vê)", "username": None}})
from test_fluxo import FakeClient, gerar_video
import galochat_app as g


def bombear(app, ate, tempo=120):
    fim = time.time() + tempo
    while time.time() < fim and not ate():
        app.root.update(); time.sleep(0.02)
    app.root.update()
    assert ate(), "tempo esgotado"


def foto(app, nome):
    app.root.update(); time.sleep(0.3); app.root.update()
    subprocess.run(["import", "-window", "root", str(SHOTS / nome)], check=True)


class FC(FakeClient):
    async def get_me(self):
        return types.SimpleNamespace(premium=False)


class FakeSessao:
    def __init__(self): self.client = FC()
    async def entidade(self, d): return "me"


# dados de teste
raiz = tmp / "Cursos"; (raiz / "Excel Inovador").mkdir(parents=True); (raiz / "Design 😀 Pro").mkdir()
v = tmp / "v"; v.mkdir()
for n in ("a", "b", "c"): gerar_video(v / f"{n}.mp4")
with zipfile.ZipFile(raiz / "Excel Inovador" / "p1.zip", "w") as z:
    z.write(v / "a.mp4", "Excel/01 - Comece por aqui/1 - Boas-vindas.mp4")
    z.write(v / "b.mp4", "Excel/01 - Comece por aqui/2 - Como estudar.mp4")
    z.write(v / "c.mp4", "Excel/03 - Primeiros passos/1 - Interface.mp4")
    z.writestr("Excel/Material/apostila.pdf", b"%PDF-1.4")
with zipfile.ZipFile(raiz / "Design 😀 Pro" / "d.zip", "w") as z:
    z.write(v / "a.mp4", "Design/Aula 😀 1.mp4")
with zipfile.ZipFile(raiz / "Solto.zip", "w") as z:
    z.write(v / "c.mp4", "intro.mp4")

app = g.App()
app.messagebox = types.SimpleNamespace(
    showinfo=lambda *a, **k: print("  [info]", a[1][:90].replace("\n", " ")), showerror=lambda *a, **k: print("  [erro]", a),
    showwarning=lambda *a, **k: print("  [aviso]", a), askyesno=lambda *a, **k: True,
    askokcancel=lambda *a, **k: True, askyesnocancel=lambda *a, **k: True)
app.sessao = FakeSessao()
app.usuario = {"nome": "Pessoa 😀 Exemplo", "usuario": "exemplo", "premium": False}
app._mostrar_login(False)
app.v_conta.set(g.seguro("✔ Conectado como Pessoa 😀 Exemplo  (@exemplo)")); app.lbl_conta.configure(style="Ok.TLabel")
app.destinos = [{"id": "me", "titulo": "Mensagens Salvas (só você vê)", "username": None},
                {"id": 1, "titulo": "Meu Acervo 😀", "username": None}]
app.cb_destino.configure(values=[g.seguro(d["titulo"]) for d in app.destinos]); app.cb_destino.current(0)
app.root.update()
foto(app, "1_conta.png")

# Adicionar pasta com vários cursos (diálogo simulado devolve "Sim")
app.filedialog = types.SimpleNamespace(askdirectory=lambda **k: str(raiz))
app._add_pasta()
bombear(app, lambda: len(app.colecoes) == 3)
print("coleções:", [(c_["nome"], c_["prefixo"], len(c_["itens"])) for c_ in app.colecoes])
app.nb.select(app.aba2)
app.tv.selection_set(app.colecoes[0]["id"]); app.root.update()
app.v_cat.set("Receitas"); app.v_tipo.set("Profissionalizante"); app.root.update()
assert app.colecoes[0]["categoria"] == "Receitas"
app.v_pref.set("EXC"); app.root.update()
assert app.colecoes[0]["itens"][0]["tag"].startswith("#EXC_F"), app.colecoes[0]["itens"][0]["tag"]
foto(app, "2_cursos.png")

# Publicar pela interface
app.nb.select(app.aba3); app._atualizar_resumo(); app.v_indice.set(True)
foto(app, "3_publicar_antes.png")
app._publicar()
bombear(app, lambda: app.publicando.done() and str(app.btn_pub["state"]) == "normal")
foto(app, "4_publicar_depois.png")
log = app.txt_log.get("1.0", "end")
assert log.count("Curso publicado") == 3, log
st = [c_["status"] for c_ in app.colecoes]
print("status:", st)
assert all(s.startswith("Publicado") for s in st)
cli = app.sessao.client
print("mensagens: arquivos", len(cli.enviados), "| textos", len(cli.textos))
assert len(cli.enviados) >= 8 and len(cli.textos) >= 4      # 3 guias + índice
assert any("ÍNDICE" in t["texto"] for t in cli.textos)

# Segunda vez: tudo já publicado -> nada marcado
app._recalcular_status_publicado()
print("depois:", [c_["status"] for c_ in app.colecoes])

# Parar no meio: novo lote com um vídeo "grande" lento não é necessário; testa cancelamento imediato
app.colecoes[0]["marcada"] = True; app.colecoes[0]["status"] = "Pronto"
reg = c.ler_json(tmp / "dados" / "registro.json", {})
for k in list(reg): reg.pop(k)
c.salvar_json(tmp / "dados" / "registro.json", reg)
app._publicar(); app.root.update(); app._parar()
bombear(app, lambda: app.publicando.done() and str(app.btn_pub["state"]) == "normal")
print("após parar:", app.v_item.get())
app.root.destroy()
print("GUI OK")
