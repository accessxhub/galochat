# =============================================================================
#  GALOCHAT  ·  © 2026 F.ER ACADEMY — Todos os direitos reservados.
#  Software proprietário da F.ER ACADEMY. Proibida a cópia, a engenharia
#  reversa ou a redistribuição, total ou parcial, sem autorização por escrito.
# =============================================================================
# -*- coding: utf-8 -*-
"""GALOCHAT — interface gráfica. Três passos: conta e destino, cursos, publicar."""
from __future__ import annotations

import asyncio
import os
import queue
import re
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime
from pathlib import Path

import galochat_core as core
import galochat_brand as marca

AVISO = (
    f"GALOCHAT, da {marca.MARCA}, organiza e publica arquivos no SEU canal do Telegram.\n\n"
    "Use apenas conteúdo que você tem direito de guardar e compartilhar: material próprio, "
    "licenciado ou autorizado por quem o criou. Você é o responsável pelo que publica.\n\n"
    "Seus dados de acesso e a sessão ficam somente neste computador."
)

COR = {"fundo": "#faf8f5", "card": "#ffffff", "texto": "#201d18", "suave": "#746b60",
       "acento": marca.VERMELHO, "acento2": "#8f181d", "ok": "#2f9e44", "erro": "#c92a2a",
       "linha": "#e6ddcf", "ouro": marca.DOURADO, "ouro_claro": marca.DOURADO_CLARO,
       "preto": marca.PRETO, "preto_painel": marca.PRETO_PAINEL, "creme": marca.CREME,
       "creme_suave": marca.CREME_SUAVE}


def seguro(t) -> str:
    """O Tk antigo trava com emojis fora do plano básico; troca por um quadrado."""
    return "".join(ch if ord(ch) <= 0xFFFF else "□" for ch in str(t))


class Worker:
    """Roda o Telethon (asyncio) numa thread própria e devolve os resultados à interface."""

    def __init__(self, fila: queue.Queue):
        self.fila = fila
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self._rodar, daemon=True).start()

    def _rodar(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def enviar(self, coro, ok=None, erro=None):
        fut = asyncio.run_coroutine_threadsafe(coro, self.loop)

        def pronto(f):
            if f.cancelled():
                if erro:
                    self.fila.put(lambda: erro(asyncio.CancelledError()))
                return
            ex = f.exception()
            if ex is not None:
                if erro:
                    self.fila.put(lambda: erro(ex))
            elif ok:
                res = f.result()
                self.fila.put(lambda: ok(res))

        fut.add_done_callback(pronto)
        return fut


class App:
    def __init__(self):
        import tkinter as tk
        from tkinter import ttk, filedialog, messagebox, simpledialog
        from tkinter import font as tkfont
        self.tk, self.ttk = tk, ttk
        self.filedialog, self.messagebox, self.simpledialog, self.tkfont = filedialog, messagebox, simpledialog, tkfont

        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                pass

        self.root = tk.Tk()
        self.root.title(f"GALOCHAT · {marca.MARCA}")
        self.root.geometry("1120x810")
        self.root.minsize(940, 700)

        self.img = {
            "about": tk.PhotoImage(data=marca.LOGO_ABOUT),
            "header": tk.PhotoImage(data=marca.LOGO_HEADER),
            "icone": tk.PhotoImage(data=marca.LOGO_ICONE),
        }
        try:
            self.root.iconphoto(True, self.img["icone"])
        except Exception:
            pass

        self.cfg = core.carregar_config()
        self.fila: queue.Queue = queue.Queue()
        self.worker = Worker(self.fila)
        self.sessao = core.SessaoTelegram()
        self.usuario = None
        self.destinos: list = []
        self.colecoes: list = []
        self.publicando = None
        self._carregando = False
        self.log_arquivo = core.pasta_dados() / "galochat.log"

        self._estilo()
        self._montar()
        self.root.protocol("WM_DELETE_WINDOW", self._fechar)
        self.root.after(100, self._poll)

    # ═════════════ infraestrutura ═════════════

    def _poll(self):
        try:
            while True:
                self.fila.get_nowait()()
        except queue.Empty:
            pass
        except Exception as ex:                       # nunca deixa o laço morrer
            self._log_arquivo(f"ERRO interno: {ex!r}")
        self.root.after(100, self._poll)

    def _emit(self, tipo, **kw):                      # chamado de qualquer thread
        self.fila.put(lambda: self._evento(tipo, kw))

    def _log_arquivo(self, texto):
        try:
            with open(self.log_arquivo, "a", encoding="utf-8") as f:
                f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {texto}\n")
        except OSError:
            pass

    def executar(self):
        self.root.after(200, self._inicio)
        self.root.mainloop()

    def _dialogo_marca(self, titulo, corpo, ok="Entendi", cancelar=None):
        """Janela modal com a logo da F.ER ACADEMY sobre painel escuro."""
        tk = self.tk
        win = tk.Toplevel(self.root)
        win.title(titulo)
        win.configure(bg=COR["fundo"])
        win.transient(self.root)
        win.resizable(False, False)
        topo = tk.Frame(win, bg=COR["preto_painel"])
        topo.pack(fill="x")
        tk.Label(topo, image=self.img["about"], bg=COR["preto_painel"], bd=0).pack(pady=14)
        tk.Label(win, text="GALOCHAT", bg=COR["fundo"], fg=COR["acento2"],
                 font=(self.fam, 16, "bold")).pack(pady=(12, 0))
        tk.Label(win, text=f"por {marca.MARCA}", bg=COR["fundo"], fg=COR["suave"],
                 font=(self.fam, 9, "bold")).pack()
        tk.Message(win, text=corpo, width=440, bg=COR["fundo"], fg=COR["texto"],
                   font=(self.fam, 10), justify="left").pack(padx=24, pady=14)
        barra = tk.Frame(win, bg=COR["fundo"])
        barra.pack(pady=(0, 16))
        resp = {"v": False}

        def fechar(v):
            resp["v"] = v
            win.destroy()
        if cancelar:
            self.ttk.Button(barra, text=cancelar, command=lambda: fechar(False)).pack(side="left", padx=6)
        self.ttk.Button(barra, text=ok, style="Acento.TButton",
                        command=lambda: fechar(True)).pack(side="left", padx=6)
        win.protocol("WM_DELETE_WINDOW", lambda: fechar(False))
        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_width()) // 2
        y = self.root.winfo_rooty() + 60
        win.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        win.grab_set()
        win.wait_window()
        return resp["v"]

    def _inicio(self):
        if not self.cfg.get("aviso_aceito"):
            if not self._dialogo_marca("GALOCHAT · antes de começar", AVISO, ok="Começar", cancelar="Sair"):
                self.root.destroy()
                return
            self.cfg["aviso_aceito"] = True
            core.salvar_config(self.cfg)
        if self.cfg.get("api_id") and self.cfg.get("api_hash") and (core.pasta_dados() / "sessao.session").exists():
            self.v_status.set("Reconectando ao Telegram…")
            self.worker.enviar(self.sessao.conectar(self.cfg["api_id"], self.cfg["api_hash"]),
                               ok=lambda u: self._logado(u) if u else self.v_status.set("Entre na sua conta (passo 1)."),
                               erro=lambda ex: self.v_status.set("Sem conexão com o Telegram. Verifique a internet."))
        else:
            self.v_status.set("Comece conectando sua conta do Telegram (passo 1).")

    def _fechar(self):
        if self.publicando and not self.publicando.done():
            if not self.messagebox.askyesno("GALOCHAT", "Há uma publicação em andamento. Parar e sair?\n"
                                            "Você poderá continuar depois de onde parou."):
                return
            self.publicando.cancel()
            core.matar_processos()
        self.root.destroy()

    def _abrir_pasta_dados(self):
        p = str(core.pasta_dados())
        try:
            if sys.platform == "win32":
                os.startfile(p)                       # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", p])
            else:
                subprocess.Popen(["xdg-open", p])
        except Exception:
            self.messagebox.showinfo("GALOCHAT", p)

    # ═════════════ estilo ═════════════

    def _estilo(self):
        r, ttk = self.root, self.ttk
        r.configure(bg=COR["fundo"])
        st = ttk.Style(r)
        st.theme_use("clam")
        padrao = self.tkfont.nametofont("TkDefaultFont")
        if sys.platform == "win32":
            for n in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
                self.tkfont.nametofont(n).configure(family="Segoe UI", size=10)
        self.fam = padrao.actual("family")
        st.configure(".", background=COR["fundo"], foreground=COR["texto"], bordercolor=COR["linha"])
        st.configure("TFrame", background=COR["fundo"])
        st.configure("TLabel", background=COR["fundo"])
        st.configure("Suave.TLabel", foreground=COR["suave"])
        st.configure("H.TLabel", font=(self.fam, 11, "bold"))
        st.configure("Ok.TLabel", foreground=COR["ok"], font=(self.fam, 11, "bold"))
        st.configure("TLabelframe", background=COR["fundo"], bordercolor=COR["linha"])
        st.configure("TLabelframe.Label", background=COR["fundo"], foreground=COR["acento2"],
                     font=(self.fam, 10, "bold"))
        st.configure("TButton", padding=(10, 5))
        st.configure("Acento.TButton", background=COR["acento"], foreground="white",
                     font=(self.fam, 11, "bold"), padding=(18, 9))
        st.map("Acento.TButton", background=[("disabled", "#d9b6b7"), ("active", COR["acento2"])],
               foreground=[("disabled", "white")])
        st.configure("TCheckbutton", background=COR["fundo"])
        st.configure("TNotebook", background=COR["fundo"], borderwidth=0)
        st.configure("TNotebook.Tab", padding=(18, 9), background="#ece4d6", font=(self.fam, 10, "bold"))
        st.map("TNotebook.Tab", background=[("selected", "white")], foreground=[("selected", COR["acento2"])])
        st.configure("Treeview", rowheight=26, background="white", fieldbackground="white")
        st.configure("Treeview.Heading", font=(self.fam, 10, "bold"), background="#ece4d6")
        st.map("Treeview", background=[("selected", "#f6e4c6")], foreground=[("selected", COR["texto"])])
        st.configure("Horizontal.TProgressbar", troughcolor="#ece6de", background=COR["acento"], thickness=10)

    # ═════════════ montagem das telas ═════════════

    def _montar(self):
        tk, ttk = self.tk, self.ttk
        # faixa escura de marca (não minimalista): logo + marca-nominal em ouro
        faixa = tk.Frame(self.root, bg=COR["preto"])
        faixa.pack(fill="x")
        interno = tk.Frame(faixa, bg=COR["preto"])
        interno.pack(anchor="w", padx=22, pady=12)
        tk.Label(interno, image=self.img["header"], bg=COR["preto_painel"], bd=0).pack(side="left")
        txt = tk.Frame(interno, bg=COR["preto"])
        txt.pack(side="left", padx=16)
        tk.Label(txt, text="GALOCHAT", bg=COR["preto"], fg=COR["ouro"],
                 font=(self.fam, 28, "bold")).pack(anchor="w")
        tk.Label(txt, text="Organize e publique seus cursos e vídeos no Telegram",
                 bg=COR["preto"], fg=COR["creme_suave"], font=(self.fam, 10)).pack(anchor="w")
        tk.Label(txt, text=f"por {marca.MARCA}", bg=COR["preto"], fg=COR["ouro_claro"],
                 font=(self.fam, 9, "bold")).pack(anchor="w", pady=(2, 0))
        tk.Frame(self.root, bg=COR["ouro"], height=3).pack(fill="x")  # filete dourado

        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=16, pady=(4, 6))
        self.aba1, self.aba2, self.aba3 = (ttk.Frame(self.nb, padding=16) for _ in range(3))
        self.nb.add(self.aba1, text="1 · Conta e destino")
        self.nb.add(self.aba2, text="2 · Cursos")
        self.nb.add(self.aba3, text="3 · Publicar")

        self.v_status = tk.StringVar(value="")
        ttk.Label(self.root, textvariable=self.v_status, style="Suave.TLabel",
                  padding=(20, 0, 20, 8)).pack(fill="x")

        self._montar_aba1()
        self._montar_aba2()
        self._montar_aba3()

    # ── aba 1 ──
    def _montar_aba1(self):
        tk, ttk, f = self.tk, self.ttk, self.aba1
        f.columnconfigure(0, weight=1)
        self.v_conta = tk.StringVar(value="Você ainda não está conectado.")
        self.lbl_conta = ttk.Label(f, textvariable=self.v_conta, style="H.TLabel")
        self.lbl_conta.grid(row=0, column=0, sticky="w")

        # login
        self.f_login = ttk.LabelFrame(f, text="Conectar sua conta do Telegram", padding=14)
        self.f_login.grid(row=1, column=0, sticky="ew", pady=(10, 10))
        fl = self.f_login
        fl.columnconfigure(1, weight=1)
        self.v_api_id = tk.StringVar(value=str(self.cfg.get("api_id", "")))
        self.v_api_hash = tk.StringVar(value=str(self.cfg.get("api_hash", "")))
        self.v_tel = tk.StringVar()
        self.v_cod = tk.StringVar()
        self.v_senha = tk.StringVar()

        ttk.Label(fl, text="1) Pegue seus dados de acesso (só na primeira vez)", style="H.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(fl, style="Suave.TLabel", justify="left", wraplength=800,
                  text="Entre em my.telegram.org com o seu número, abra «API development tools», crie um app "
                       "(o nome é livre) e copie o api_id e o api_hash.").grid(row=1, column=0, columnspan=3,
                                                                                   sticky="w", pady=(2, 6))
        ttk.Button(fl, text="Abrir my.telegram.org", command=lambda: webbrowser.open("https://my.telegram.org/apps")
                   ).grid(row=2, column=0, sticky="w")
        ttk.Label(fl, text="api_id").grid(row=3, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(fl, textvariable=self.v_api_id, width=18).grid(row=3, column=1, sticky="w", pady=(8, 0))
        ttk.Label(fl, text="api_hash").grid(row=4, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(fl, textvariable=self.v_api_hash, width=44).grid(row=4, column=1, sticky="w", pady=(4, 0))

        ttk.Label(fl, text="2) Seu telefone, com código do país", style="H.TLabel").grid(
            row=5, column=0, columnspan=3, sticky="w", pady=(14, 0))
        ttk.Label(fl, text="Telefone").grid(row=6, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(fl, textvariable=self.v_tel, width=22).grid(row=6, column=1, sticky="w", pady=(4, 0))
        ttk.Button(fl, text="Enviar código", command=self._btn_codigo).grid(row=6, column=2, padx=8, pady=(4, 0))

        ttk.Label(fl, text="3) Digite o código que chegou no seu Telegram", style="H.TLabel").grid(
            row=7, column=0, columnspan=3, sticky="w", pady=(14, 0))
        ttk.Label(fl, text="Código").grid(row=8, column=0, sticky="w", pady=(4, 0))
        self.ent_cod = ttk.Entry(fl, textvariable=self.v_cod, width=12)
        self.ent_cod.grid(row=8, column=1, sticky="w", pady=(4, 0))
        ttk.Button(fl, text="Entrar", command=self._btn_entrar).grid(row=8, column=2, padx=8, pady=(4, 0))

        self.f_senha = ttk.Frame(fl)
        self.f_senha.grid(row=9, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Label(self.f_senha, text="Sua conta tem verificação em duas etapas. Senha:").pack(side="left")
        ttk.Entry(self.f_senha, textvariable=self.v_senha, show="•", width=22).pack(side="left", padx=8)
        ttk.Button(self.f_senha, text="Confirmar", command=self._btn_senha).pack(side="left")
        self.f_senha.grid_remove()

        # conectado
        self.f_conectado = ttk.Frame(f)
        self.f_conectado.grid(row=1, column=0, sticky="ew", pady=(6, 6))
        ttk.Button(self.f_conectado, text="Sair desta conta", command=self._btn_sair).pack(side="left")
        self.f_conectado.grid_remove()

        # destino
        self.f_dest = ttk.LabelFrame(f, text="Onde publicar", padding=14)
        self.f_dest.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        fd = self.f_dest
        fd.columnconfigure(0, weight=1)
        self.v_destino = tk.StringVar()
        self.cb_destino = ttk.Combobox(fd, textvariable=self.v_destino, state="readonly", width=60)
        self.cb_destino.grid(row=0, column=0, sticky="ew")
        self.cb_destino.bind("<<ComboboxSelected>>", self._destino_escolhido)
        ttk.Button(fd, text="Atualizar lista", command=self._carregar_destinos).grid(row=0, column=1, padx=(8, 0))
        ttk.Button(fd, text="Criar canal privado…", command=self._criar_canal).grid(row=0, column=2, padx=(8, 0))
        ttk.Label(fd, style="Suave.TLabel", justify="left", wraplength=800,
                  text="Dica: crie um canal privado só para o seu acervo. Aparecem aqui os canais em que você é "
                       "dono ou administrador. «Mensagens Salvas» é a sua conversa privada com você mesmo."
                  ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))

        self.btn_prox1 = ttk.Button(f, text="Continuar  ›", style="Acento.TButton",
                                    command=lambda: self.nb.select(self.aba2))
        self.btn_prox1.grid(row=3, column=0, sticky="e", pady=(10, 0))
        self._mostrar_login(True)

    def _mostrar_login(self, mostrar: bool):
        if mostrar:
            self.f_conectado.grid_remove()
            self.f_login.grid()
        else:
            self.f_login.grid_remove()
            self.f_conectado.grid()

    # ── aba 2 ──
    def _montar_aba2(self):
        tk, ttk, f = self.tk, self.ttk, self.aba2
        f.columnconfigure(0, weight=3)
        f.columnconfigure(1, weight=2)
        f.rowconfigure(1, weight=1)

        barra = ttk.Frame(f)
        barra.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        ttk.Button(barra, text="＋ Adicionar pasta…", command=self._add_pasta).pack(side="left")
        ttk.Button(barra, text="＋ Adicionar .zip…", command=self._add_zips).pack(side="left", padx=6)
        ttk.Button(barra, text="Remover", command=self._remover).pack(side="left")
        ttk.Label(barra, style="Suave.TLabel",
                  text="  Cada curso = uma pasta ou um .zip"
                  ).pack(side="left", padx=8)

        esq = ttk.Frame(f)
        esq.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
        esq.columnconfigure(0, weight=1)
        esq.rowconfigure(0, weight=1)
        cols = ("env", "nome", "cat", "vid", "doc", "tam", "st")
        self.tv = ttk.Treeview(esq, columns=cols, show="headings", selectmode="extended", height=8)
        for c, t, w, a in (("env", "Enviar", 60, "center"), ("nome", "Curso", 170, "w"), ("cat", "Categoria", 90, "w"),
                           ("vid", "Vídeos", 62, "e"), ("doc", "Docs", 50, "e"), ("tam", "Tamanho", 82, "e"),
                           ("st", "Situação", 96, "w")):
            self.tv.heading(c, text=t)
            self.tv.column(c, width=w, anchor=a, stretch=(c == "nome"))
        self.tv.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(esq, orient="vertical", command=self.tv.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.tv.configure(yscrollcommand=sb.set)
        self.tv.bind("<<TreeviewSelect>>", self._ao_selecionar)
        self.tv.bind("<Button-1>", self._clique_lista)

        ed = ttk.LabelFrame(esq, text="Dados do curso (aparecem na capa)", padding=12)
        ed.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ed.columnconfigure(1, weight=1)
        self.v_nome, self.v_cat, self.v_tipo, self.v_pref = (tk.StringVar() for _ in range(4))
        self.v_capa = tk.StringVar(value="Automática")
        ttk.Label(ed, text="Nome").grid(row=0, column=0, sticky="w")
        self.ent_nome = ttk.Entry(ed, textvariable=self.v_nome)
        self.ent_nome.grid(row=0, column=1, columnspan=3, sticky="ew", pady=2)
        ttk.Label(ed, text="Categoria").grid(row=1, column=0, sticky="w")
        self.cb_cat = ttk.Combobox(ed, textvariable=self.v_cat, width=24)
        self.cb_cat.grid(row=1, column=1, sticky="w", pady=2)
        ttk.Label(ed, text="  Tipo").grid(row=1, column=2, sticky="w")
        ttk.Entry(ed, textvariable=self.v_tipo, width=22).grid(row=1, column=3, sticky="w", pady=2)
        ttk.Label(ed, text="Prefixo das #").grid(row=2, column=0, sticky="w")
        self.ent_pref = ttk.Entry(ed, textvariable=self.v_pref, width=12)
        self.ent_pref.grid(row=2, column=1, sticky="w", pady=2)
        ttk.Label(ed, text="  ex.: EXC → #EXC_F001", style="Suave.TLabel").grid(row=2, column=2, columnspan=2, sticky="w")
        ttk.Label(ed, text="Capa").grid(row=3, column=0, sticky="w")
        ttk.Label(ed, textvariable=self.v_capa, style="Suave.TLabel", wraplength=300).grid(
            row=3, column=1, sticky="w", pady=2)
        fc = ttk.Frame(ed)
        fc.grid(row=3, column=2, columnspan=2, sticky="e")
        ttk.Button(fc, text="Escolher imagem…", command=self._escolher_capa).pack(side="left")
        ttk.Button(fc, text="Automática", command=self._capa_auto).pack(side="left", padx=(6, 0))
        for v in (self.v_nome, self.v_cat, self.v_tipo, self.v_pref):
            v.trace_add("write", self._campo_mudou)

        dir_ = ttk.LabelFrame(f, text="Prévia: módulos, aulas e hashtags", padding=8)
        dir_.grid(row=1, column=1, sticky="nsew")
        dir_.columnconfigure(0, weight=1)
        dir_.rowconfigure(1, weight=1)
        self.v_resumo_curso = tk.StringVar(value="Selecione um curso")
        ttk.Label(dir_, textvariable=self.v_resumo_curso, style="Suave.TLabel").grid(row=0, column=0, sticky="w")
        self.tp = ttk.Treeview(dir_, columns=("tag", "tam"), show="tree headings")
        self.tp.heading("#0", text="Módulo / aula")
        self.tp.heading("tag", text="Hashtag")
        self.tp.heading("tam", text="Tam.")
        self.tp.column("#0", width=180, stretch=True)
        self.tp.column("tag", width=104, anchor="w", stretch=False)
        self.tp.column("tam", width=84, anchor="e", stretch=False)
        self.tp.grid(row=1, column=0, sticky="nsew")
        sb2 = ttk.Scrollbar(dir_, orient="vertical", command=self.tp.yview)
        sb2.grid(row=1, column=1, sticky="ns")
        self.tp.configure(yscrollcommand=sb2.set)

        ttk.Button(f, text="Continuar  ›", style="Acento.TButton",
                   command=lambda: (self._atualizar_resumo(), self.nb.select(self.aba3))
                   ).grid(row=2, column=1, sticky="e", pady=(10, 0))

    # ── aba 3 ──
    def _montar_aba3(self):
        tk, ttk, f = self.tk, self.ttk, self.aba3
        f.columnconfigure(0, weight=1)
        f.rowconfigure(3, weight=1)

        op = ttk.LabelFrame(f, text="Opções", padding=12)
        op.grid(row=0, column=0, sticky="ew")
        op.columnconfigure(1, weight=1)
        c = self.cfg
        self.v_conv = tk.BooleanVar(value=c["converter_incompativeis"])
        self.v_docs = tk.BooleanVar(value=c["enviar_documentos"])
        self.v_usar_pref = tk.BooleanVar(value=c["usar_prefixo"])
        self.v_fixar = tk.BooleanVar(value=c["fixar"])
        self.v_indice = tk.BooleanVar(value=c["indice"])
        self.v_boas = tk.StringVar(value=c["boas_vindas"])
        self.v_ass = tk.StringVar(value=c["assinatura"])
        self.v_depois = tk.StringVar(value="Mover os arquivos para a pasta _enviados" if c["depois"] == "mover"
                                     else "Não fazer nada")
        ttk.Checkbutton(op, text="Converter formatos que o Telegram não reproduz (AVI, WMV…). Mais lento, mas toca em qualquer aparelho",
                        variable=self.v_conv).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(op, text="Enviar também documentos (PDF, planilhas, textos…)", variable=self.v_docs
                        ).grid(row=1, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(op, text="Usar prefixo nas hashtags (#EXC_F001). Recomendado se o canal tiver mais de um curso",
                        variable=self.v_usar_pref, command=self._retag_todos).grid(row=2, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(op, text="Fixar o guia (ou o índice) no topo do canal", variable=self.v_fixar
                        ).grid(row=3, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(op, text="Manter um índice com todos os cursos do canal", variable=self.v_indice
                        ).grid(row=4, column=0, columnspan=2, sticky="w")
        ttk.Label(op, text="Texto de boas-vindas do guia").grid(row=5, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(op, textvariable=self.v_boas).grid(row=5, column=1, sticky="ew", pady=(8, 0), padx=(8, 0))
        ttk.Label(op, text="Assinatura nas aulas (opcional)").grid(row=6, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(op, textvariable=self.v_ass).grid(row=6, column=1, sticky="ew", pady=(4, 0), padx=(8, 0))
        ttk.Label(op, text="Depois de publicar").grid(row=7, column=0, sticky="w", pady=(4, 0))
        ttk.Combobox(op, textvariable=self.v_depois, state="readonly", width=44,
                     values=("Não fazer nada", "Mover os arquivos para a pasta _enviados")
                     ).grid(row=7, column=1, sticky="w", pady=(4, 0), padx=(8, 0))

        self.v_resumo = tk.StringVar()
        ttk.Label(f, textvariable=self.v_resumo, style="H.TLabel").grid(row=1, column=0, sticky="w", pady=(12, 6))

        acoes = ttk.Frame(f)
        acoes.grid(row=2, column=0, sticky="ew")
        acoes.columnconfigure(2, weight=1)
        self.btn_pub = ttk.Button(acoes, text="▶  Publicar", style="Acento.TButton", command=self._publicar)
        self.btn_pub.grid(row=0, column=0)
        self.btn_parar = ttk.Button(acoes, text="■  Parar", command=self._parar, state="disabled")
        self.btn_parar.grid(row=0, column=1, padx=8)
        ttk.Button(acoes, text="Abrir pasta de registros", command=self._abrir_pasta_dados).grid(row=0, column=3)

        prog = ttk.Frame(f)
        prog.grid(row=3, column=0, sticky="nsew", pady=(10, 0))
        prog.columnconfigure(0, weight=1)
        prog.rowconfigure(5, weight=1)
        self.v_item = tk.StringVar(value="Pronto para publicar.")
        self.v_etapa = tk.StringVar(value="")
        self.v_totaltxt = tk.StringVar(value="")
        ttk.Label(prog, textvariable=self.v_item, style="H.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(prog, textvariable=self.v_etapa, style="Suave.TLabel").grid(row=1, column=0, sticky="w")
        self.pb_arq = ttk.Progressbar(prog, maximum=1000)
        self.pb_arq.grid(row=2, column=0, sticky="ew", pady=(4, 6))
        ttk.Label(prog, textvariable=self.v_totaltxt, style="Suave.TLabel").grid(row=3, column=0, sticky="w")
        self.pb_tot = ttk.Progressbar(prog, maximum=1000)
        self.pb_tot.grid(row=4, column=0, sticky="ew", pady=(4, 8))
        fl = ttk.Frame(prog)
        fl.grid(row=5, column=0, sticky="nsew")
        fl.columnconfigure(0, weight=1)
        fl.rowconfigure(0, weight=1)
        self.txt_log = tk.Text(fl, height=8, wrap="word", state="disabled", bg="white", relief="solid", bd=1,
                               highlightthickness=0, font=(self.fam, 9))
        self.txt_log.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(fl, orient="vertical", command=self.txt_log.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.txt_log.configure(yscrollcommand=sb.set)

    # ═════════════ conta e destino ═════════════

    def _ocupado(self, texto):
        self.v_status.set(texto)
        self.root.configure(cursor="watch")

    def _livre(self):
        self.root.configure(cursor="")

    def _erro(self, ex):
        self._livre()
        if isinstance(ex, asyncio.CancelledError):
            return
        msg = core.traduzir_erro(ex)
        self._log_arquivo(f"ERRO: {ex!r}")
        self.v_status.set(msg)
        self.messagebox.showerror("GALOCHAT", msg)

    def _salvar_credenciais(self):
        self.cfg["api_id"] = self.v_api_id.get().strip()
        self.cfg["api_hash"] = self.v_api_hash.get().strip()
        core.salvar_config(self.cfg)

    def _btn_codigo(self):
        api_id, api_hash, tel = self.v_api_id.get().strip(), self.v_api_hash.get().strip(), self.v_tel.get().strip()
        if not api_id.isdigit() or len(api_hash) < 20:
            self.messagebox.showwarning("GALOCHAT", "Preencha o api_id (só números) e o api_hash (32 caracteres) "
                                        "copiados de my.telegram.org.")
            return
        if not re.fullmatch(r"\+?\d[\d\s\-()]{7,}", tel):
            self.messagebox.showwarning("GALOCHAT", "Digite o telefone com o código do país, por exemplo +5511999999999.")
            return
        self._salvar_credenciais()
        self._ocupado("Conectando ao Telegram…")

        async def tarefa():
            usuario = await self.sessao.conectar(api_id, api_hash)
            if usuario:
                return usuario
            await self.sessao.enviar_codigo(tel if tel.startswith("+") else "+" + tel)
            return None

        def ok(usuario):
            self._livre()
            if usuario:
                self._logado(usuario)
            else:
                self.v_status.set("Código enviado! Abra o Telegram, copie o código e digite acima.")
                self.ent_cod.focus_set()

        self.worker.enviar(tarefa(), ok=ok, erro=self._erro)

    def _btn_entrar(self):
        cod = self.v_cod.get().strip()
        if not cod:
            return
        self._ocupado("Entrando…")

        def ok(res):
            self._livre()
            if res == "SENHA":
                self.f_senha.grid()
                self.v_status.set("Digite a senha da verificação em duas etapas.")
            else:
                self._logado(res)

        self.worker.enviar(self.sessao.entrar_codigo(cod), ok=ok, erro=self._erro)

    def _btn_senha(self):
        self._ocupado("Entrando…")
        self.worker.enviar(self.sessao.entrar_senha(self.v_senha.get()),
                           ok=lambda u: (self._livre(), self._logado(u)), erro=self._erro)

    def _btn_sair(self):
        if not self.messagebox.askyesno("GALOCHAT", "Sair desta conta do Telegram neste computador?"):
            return
        self.worker.enviar(self.sessao.sair(), ok=lambda _: self._deslogado(), erro=self._erro)

    def _deslogado(self):
        self.usuario = None
        self.v_conta.set("Você ainda não está conectado.")
        self.lbl_conta.configure(style="H.TLabel")
        self._mostrar_login(True)
        self.cb_destino.configure(values=[])
        self.v_destino.set("")
        self.v_status.set("Conta desconectada.")

    def _logado(self, usuario):
        self.usuario = usuario
        extra = f"  (@{usuario['usuario']})" if usuario.get("usuario") else ""
        premium = "  ·  Premium: arquivos de até ~4 GB" if usuario.get("premium") else ""
        self.v_conta.set(seguro(f"✔ Conectado como {usuario['nome']}{extra}{premium}"))
        self.lbl_conta.configure(style="Ok.TLabel")
        self._mostrar_login(False)
        self.v_status.set("Escolha onde publicar.")
        self._carregar_destinos()

    def _carregar_destinos(self):
        if not self.usuario:
            return
        self._ocupado("Buscando seus canais…")

        def ok(lista):
            self._livre()
            self.destinos = lista
            self.cb_destino.configure(values=[seguro(d["titulo"]) for d in lista])
            salvo = self.cfg.get("destino")
            idx = next((i for i, d in enumerate(lista) if salvo and str(d["id"]) == str(salvo["id"])), None)
            if idx is not None:
                self.cb_destino.current(idx)
                self.v_status.set("Tudo pronto. Vá para o passo 2.")
            else:
                self.v_status.set("Escolha o canal onde os cursos serão publicados.")

        self.worker.enviar(self.sessao.destinos(), ok=ok, erro=self._erro)

    def _destino_escolhido(self, _=None):
        i = self.cb_destino.current()
        if 0 <= i < len(self.destinos):
            self.cfg["destino"] = self.destinos[i]
            core.salvar_config(self.cfg)
            self._recalcular_status_publicado()
            self._atualizar_resumo()

    def _criar_canal(self):
        if not self.usuario:
            self.messagebox.showinfo("GALOCHAT", "Conecte sua conta primeiro.")
            return
        nome = self.simpledialog.askstring("Novo canal privado", "Nome do canal:", parent=self.root)
        if not nome or not nome.strip():
            return
        self._ocupado("Criando o canal…")

        def ok(d):
            self._livre()
            self.destinos.append(d)
            self.cb_destino.configure(values=[seguro(x["titulo"]) for x in self.destinos])
            self.cb_destino.current(len(self.destinos) - 1)
            self._destino_escolhido()
            self.v_status.set("Canal criado e selecionado.")

        self.worker.enviar(self.sessao.criar_canal(nome), ok=ok, erro=self._erro)

    # ═════════════ cursos ═════════════

    def _add_pasta(self):
        d = self.filedialog.askdirectory(title="Escolha a pasta do curso (ou uma pasta com vários cursos)")
        if not d:
            return
        pasta = Path(d)
        try:
            subs = [x for x in sorted(pasta.iterdir()) if x.is_dir() and x.name != core.PASTA_ENVIADOS
                    and core.tem_conteudo(x)]
            soltos = sorted(pasta.glob("*.zip"))
        except OSError as ex:
            self.messagebox.showerror("GALOCHAT", str(ex))
            return
        grupos = []
        varios = False
        if len(subs) >= 2 or (subs and soltos):
            r = self.messagebox.askyesnocancel(
                "Esta pasta tem vários cursos?",
                f"Encontrei {len(subs)} subpasta(s)" + (f" e {len(soltos)} .zip solto(s)" if soltos else "") +
                f" dentro de «{pasta.name}».\n\nSim  =  cada subpasta (e cada .zip) é um curso diferente\n"
                "Não  =  a pasta inteira é um único curso")
            if r is None:
                return
            varios = r
        if varios:
            grupos += [(core.fontes_da_pasta(s), None) for s in subs]
            grupos += [([{"tipo": "zip", "caminho": str(z)}], None) for z in soltos]
        else:
            grupos.append((core.fontes_da_pasta(pasta), None))
        self._analisar(grupos)

    def _add_zips(self):
        arqs = self.filedialog.askopenfilenames(title="Escolha um ou mais .zip (cada um vira um curso)",
                                                filetypes=[("Arquivos zip", "*.zip")])
        if arqs:
            self._analisar([([{"tipo": "zip", "caminho": a}], None) for a in arqs])

    def _analisar(self, grupos):
        self._ocupado("Lendo os arquivos…")
        cfg = dict(self.cfg)

        def tarefa():
            novos, erros = [], []
            for fontes, nome in grupos:
                try:
                    novos.append(core.analisar_colecao(fontes, nome, cfg))
                except Exception as ex:
                    erros.append(str(ex))
            self.fila.put(lambda: self._colecoes_prontas(novos, erros))

        threading.Thread(target=tarefa, daemon=True).start()

    def _canal_chave(self):
        d = self.cfg.get("destino")
        return str(d["id"]) if d else None

    def _colecoes_prontas(self, novos, erros):
        self._livre()
        existentes = {c["id"] for c in self.colecoes}
        usados = {c["prefixo"] for c in self.colecoes}
        if self._canal_chave():
            usados |= core.prefixos_usados(self._canal_chave())
        adicionados = []
        for col in novos:
            if col["id"] in existentes:
                continue
            if not col["itens"]:
                erros.append(f"«{col['nome']}» não tem vídeos nem documentos.")
                continue
            col["prefixo"] = core.prefixo_unico(core.sugerir_prefixo(col["nome"]), usados)
            usados.add(col["prefixo"])
            self._retag(col)
            col["status"] = "Pronto"
            self.colecoes.append(col)
            adicionados.append(col)
        self._recalcular_status_publicado()
        self._redesenhar_lista()
        if adicionados:
            self.tv.selection_set(adicionados[0]["id"])
            self.v_status.set(f"{len(adicionados)} curso(s) adicionado(s).")
        if erros:
            self.messagebox.showwarning("GALOCHAT", "\n\n".join(erros[:5]))
        self._atualizar_resumo()

    def _recalcular_status_publicado(self):
        ck = self._canal_chave()
        for col in self.colecoes:
            if col.get("status") == "Publicado ✔":
                continue
            if ck and core.ja_publicado(ck, col["id"]):
                col["status"], col["marcada"] = "Já publicado", False
            elif col.get("status") == "Já publicado":
                col["status"], col["marcada"] = "Pronto", True
        self._redesenhar_lista()

    def _retag(self, col):
        core.atribuir_tags(col["itens"], col["prefixo"] if self.v_usar_pref.get() else "")

    def _retag_todos(self):
        for c in self.colecoes:
            self._retag(c)
        sel = self._selecionadas()
        if len(sel) == 1:
            self._previa(sel[0])

    def _valores(self, col):
        vid = sum(1 for i in col["itens"] if i["tipo"] == "video")
        return ("☑" if col["marcada"] else "☐", seguro(col["nome"]), seguro(col["categoria"]), vid,
                len(col["itens"]) - vid, core.fmt_tamanho(col["tamanho_total"]), col.get("status", ""))

    def _redesenhar_lista(self):
        sel = set(self.tv.selection())
        self.tv.delete(*self.tv.get_children())
        for col in self.colecoes:
            self.tv.insert("", "end", iid=col["id"], values=self._valores(col))
        keep = [i for i in sel if self.tv.exists(i)]
        if keep:
            self.tv.selection_set(keep)
        cats = sorted({c["categoria"] for c in self.colecoes} | {self.cfg["categoria_padrao"]})
        self.cb_cat.configure(values=[seguro(c) for c in cats])

    def _linha(self, col):
        if self.tv.exists(col["id"]):
            self.tv.item(col["id"], values=self._valores(col))

    def _selecionadas(self):
        ids = set(self.tv.selection())
        return [c for c in self.colecoes if c["id"] in ids]

    def _clique_lista(self, ev):
        if self.tv.identify_region(ev.x, ev.y) == "cell" and self.tv.identify_column(ev.x) == "#1":
            iid = self.tv.identify_row(ev.y)
            col = next((c for c in self.colecoes if c["id"] == iid), None)
            if col:
                col["marcada"] = not col["marcada"]
                self._linha(col)
                self._atualizar_resumo()
            return "break"

    def _remover(self):
        if self.publicando and not self.publicando.done():
            return
        ids = {c["id"] for c in self._selecionadas()}
        self.colecoes = [c for c in self.colecoes if c["id"] not in ids]
        self._redesenhar_lista()
        self._ao_selecionar()
        self._atualizar_resumo()

    def _ao_selecionar(self, _=None):
        sel = self._selecionadas()
        self._carregando = True
        try:
            multi = len(sel) > 1
            self.ent_nome.configure(state="disabled" if multi or not sel else "normal")
            self.ent_pref.configure(state="disabled" if multi or not sel else "normal")
            if sel:
                c = sel[0]
                self.v_nome.set("(vários cursos)" if multi else c["nome"])
                self.v_cat.set(c["categoria"] if not multi or len({x["categoria"] for x in sel}) == 1 else "")
                self.v_tipo.set(c["tipo"] if not multi or len({x["tipo"] for x in sel}) == 1 else "")
                self.v_pref.set("" if multi else c["prefixo"])
                self.v_capa.set("—" if multi else ("Automática" if not c.get("capa") else Path(c["capa"]).name))
            else:
                for v in (self.v_nome, self.v_cat, self.v_tipo, self.v_pref):
                    v.set("")
        finally:
            self._carregando = False
        self._previa(sel[0]) if len(sel) == 1 else self._previa(None)

    def _campo_mudou(self, *_):
        if self._carregando:
            return
        sel = self._selecionadas()
        if not sel:
            return
        multi = len(sel) > 1
        retag = False
        for c in sel:
            if not multi:
                c["nome"] = self.v_nome.get().strip() or c["nome"]
                novo = core.limpar_tag(self.v_pref.get())
                if novo != c["prefixo"]:
                    c["prefixo"], retag = novo, True
            if self.v_cat.get().strip() or not multi:
                c["categoria"] = self.v_cat.get().strip() or self.cfg["categoria_padrao"]
            if self.v_tipo.get().strip() or not multi:
                c["tipo"] = self.v_tipo.get().strip() or self.cfg["tipo_padrao"]
            self._linha(c)
        if retag:
            self._retag(sel[0])
            self._previa(sel[0])

    def _escolher_capa(self):
        sel = self._selecionadas()
        if not sel:
            return
        a = self.filedialog.askopenfilename(title="Imagem de capa", filetypes=[("Imagens", "*.jpg *.jpeg *.png *.webp")])
        if a:
            for c in sel:
                c["capa"] = a
            self.v_capa.set(Path(a).name)

    def _capa_auto(self):
        for c in self._selecionadas():
            c["capa"] = None
        self.v_capa.set("Automática")

    def _previa(self, col):
        self.tp.delete(*self.tp.get_children())
        if not col:
            self.v_resumo_curso.set("Selecione um curso" if not self._selecionadas() else "Vários cursos selecionados")
            return
        vid = sum(1 for i in col["itens"] if i["tipo"] == "video")
        self.v_resumo_curso.set(f"{vid} vídeo(s) · {len(col['itens']) - vid} documento(s) · "
                                f"{core.fmt_tamanho(col['tamanho_total'])}")
        abrir = len(col["itens"]) < 300
        nos: dict = {}
        for it in col["itens"]:
            pai = ""
            for k in range(len(it["modulo"])):
                chave = tuple(it["modulo"][:k + 1])
                if chave not in nos:
                    nos[chave] = self.tp.insert(pai, "end", text=seguro(it["modulo"][k]), open=abrir, values=("", ""))
                pai = nos[chave]
            self.tp.insert(pai, "end", text=seguro(it["arquivo"]), values=(it["tag"], core.fmt_tamanho(it["tamanho"])))

    # ═════════════ publicar ═════════════

    def _atualizar_resumo(self):
        marc = [c for c in self.colecoes if c["marcada"]]
        vid = sum(1 for c in marc for i in c["itens"] if i["tipo"] == "video")
        tam = sum(c["tamanho_total"] for c in marc)
        d = self.cfg.get("destino")
        destino = seguro(d["titulo"]) if d else "(escolha um destino no passo 1)"
        self.v_resumo.set(f"Destino: {destino}   ·   {len(marc)} curso(s)   ·   {vid} vídeo(s)   ·   {core.fmt_tamanho(tam)}")

    def _ler_opcoes(self):
        c = self.cfg
        c["converter_incompativeis"] = self.v_conv.get()
        c["enviar_documentos"] = self.v_docs.get()
        c["usar_prefixo"] = self.v_usar_pref.get()
        c["fixar"] = self.v_fixar.get()
        c["indice"] = self.v_indice.get()
        c["boas_vindas"] = self.v_boas.get().strip() or core.CONFIG_PADRAO["boas_vindas"]
        c["assinatura"] = self.v_ass.get().strip()
        c["depois"] = "mover" if self.v_depois.get().startswith("Mover") else "nada"
        core.salvar_config(c)

    def _copia_para_publicar(self, col):
        c = dict(col)
        itens = [dict(i) for i in col["itens"] if self.cfg["enviar_documentos"] or i["tipo"] == "video"]
        c["itens"] = itens
        c["tamanho_total"] = sum(i["tamanho"] for i in itens)
        return c

    def _publicar(self):
        if self.publicando and not self.publicando.done():
            return
        if not self.usuario:
            self.messagebox.showinfo("GALOCHAT", "Conecte sua conta no passo 1.")
            self.nb.select(self.aba1)
            return
        if not self.cfg.get("destino"):
            self.messagebox.showinfo("GALOCHAT", "Escolha onde publicar no passo 1.")
            self.nb.select(self.aba1)
            return
        marcadas = [c for c in self.colecoes if c["marcada"]]
        if not marcadas:
            self.messagebox.showinfo("GALOCHAT", "Adicione pelo menos um curso (e deixe-o marcado) no passo 2.")
            self.nb.select(self.aba2)
            return
        try:
            core.caminho_ffmpeg()
        except RuntimeError as ex:
            self.messagebox.showerror("GALOCHAT", str(ex))
            return
        self._ler_opcoes()
        cols = [self._copia_para_publicar(c) for c in marcadas]
        self.btn_pub.configure(state="disabled")
        self.btn_parar.configure(state="normal")
        self.pb_arq["value"] = self.pb_tot["value"] = 0
        self.v_item.set("Começando…")
        self._log(f"── Publicação iniciada ({len(cols)} curso(s)) ──")
        self.publicando = self.worker.enviar(
            core.publicar(self.sessao, self.cfg["destino"], cols, dict(self.cfg), self._emit),
            ok=self._fim, erro=self._fim_erro)

    def _parar(self):
        if self.publicando and not self.publicando.done():
            self.v_etapa.set("Parando…")
            self.publicando.cancel()
            core.matar_processos()

    def _fim(self, resumo):
        self.btn_pub.configure(state="normal")
        self.btn_parar.configure(state="disabled")
        self.pb_arq["value"], self.pb_tot["value"] = 0, 1000
        self.v_item.set("Concluído.")
        self.v_etapa.set("")
        self._atualizar_resumo()
        texto = (f"Publicados: {resumo['publicados']}   ·   Já existiam: {resumo['pulados']}   ·   "
                 f"Incompletos: {resumo['incompletos']}   ·   Falhas: {resumo['falhas']}")
        self._log("── " + texto + " ──")
        self.v_status.set(texto)
        self._recalcular_status_publicado()
        self.messagebox.showinfo("GALOCHAT", texto + ("\n\nOs cursos incompletos continuam de onde pararam "
                                                      "quando você clicar em Publicar de novo."
                                                      if resumo["incompletos"] or resumo["falhas"] else ""))

    def _fim_erro(self, ex):
        self.btn_pub.configure(state="normal")
        self.btn_parar.configure(state="disabled")
        self.v_etapa.set("")
        if isinstance(ex, asyncio.CancelledError):
            self.v_item.set("Interrompido.")
            self._log("■ Interrompido. Clique em Publicar para continuar de onde parou.")
            self.v_status.set("Interrompido. Você pode continuar depois.")
        else:
            self.v_item.set("A publicação parou por um erro.")
            self._log(f"✖ {core.traduzir_erro(ex)}")
            self._log_arquivo(f"ERRO publicação: {ex!r}")
            self.messagebox.showerror("GALOCHAT", core.traduzir_erro(ex))

    def _evento(self, tipo, d):
        if tipo == "log":
            self._log(d["texto"])
        elif tipo == "etapa":
            self.v_etapa.set(seguro(d["texto"]))
        elif tipo == "arquivo":
            self.pb_arq["value"] = int(d["frac"] * 1000)
            self.v_etapa.set(seguro(d["texto"]))
        elif tipo == "item":
            self.v_item.set(seguro(f"({d['n']}/{d['total']})  {d['texto']}"))
            self.pb_arq["value"] = 0
        elif tipo == "total":
            self.pb_tot["value"] = int(1000 * d["feitos"] / max(d["total"], 1))
            self.v_totaltxt.set(f"Progresso geral: {d['feitos']} de {d['total']} item(ns)")
        elif tipo == "colecao_fim":
            col = next((c for c in self.colecoes if c["id"] == d["id"]), None)
            if col:
                col["status"] = {"ok": "Publicado ✔", "pulado": "Já publicado", "incompleto": "Incompleto",
                                 "falha": "Falhou"}[d["resultado"]]
                if d["resultado"] in ("ok", "pulado"):
                    col["marcada"] = False
                self._linha(col)

    def _log(self, texto):
        self._log_arquivo(texto)
        t = self.txt_log
        t.configure(state="normal")
        t.insert("end", seguro(texto) + "\n")
        t.see("end")
        t.configure(state="disabled")


def main():
    if "--selftest" in sys.argv:                      # usado no build: confere FFmpeg e formatação
        ok, log = core.autoteste()
        saida = "\n".join(log) + f"\nRESULTADO: {'OK' if ok else 'FALHOU'}\n"
        for destino in (core.pasta_dados() / "selftest.txt", Path.cwd() / "selftest.txt"):
            try:
                destino.write_text(saida, encoding="utf-8")
            except OSError:
                pass
        try:
            print(saida)
        except Exception:
            pass
        sys.exit(0 if ok else 1)
    App().executar()


if __name__ == "__main__":
    main()
