# GALOCHAT · por F.ER ACADEMY

Organize e publique seus cursos e vídeos no seu canal do Telegram, por uma janela simples e sem usar terminal.

© 2026 F.ER ACADEMY — Todos os direitos reservados. Veja `LICENSE.txt`.

## O que ele faz

Para cada curso, o GALOCHAT publica no seu canal:

1. **Capa** com nome, categoria, tipo e tamanho.
2. **Cada aula como vídeo de verdade** (com player, miniatura, duração e streaming), com uma hashtag única (`#F001`, `#F002`…) e o módulo na legenda.
3. **Documentos** (PDF, planilhas…) como arquivo, com `#Doc001`, `#Doc002`…
4. **Guia de navegação** com as hashtags agrupadas por módulo. Clicar numa hashtag mostra a aula.
5. Opcional: um **índice do canal** com todos os cursos publicados.

Nos bastidores ele extrai um vídeo por vez do `.zip` (pouco espaço em disco), converte para MP4 sem perda de qualidade, divide vídeos maiores que o limite do Telegram em partes que tocam sozinhas, pula o que já foi enviado e retoma de onde parou se a internet cair.

## Como abrir

**Jeito recomendado — gerar o `GALOCHAT.exe` pelo GitHub (não precisa instalar nada no seu PC):**
1. Envie esta pasta para um repositório seu no GitHub.
2. Abra a aba **Actions**, escolha **Gerar GALOCHAT.exe (Windows)** e clique em **Run workflow**.
3. Ao terminar, baixe o `GALOCHAT.exe` em *Artifacts*. É só esse arquivo que você distribui.

Esse caminho é o mais limpo: o programa é compilado numa máquina neutra do GitHub, então nada do seu computador (nome de usuário, pastas) entra no executável.

**No seu próprio Windows:** instale o Python 3.10+ (marque *Add python.exe to PATH*) e dê dois cliques em `build_windows.bat`. O resultado fica em `dist\GALOCHAT.exe`.

**Para testar antes de gerar o .exe** (com Python instalado): dois cliques em `abrir_galochat.bat` (Windows) ou `./abrir_galochat.sh` (Mac/Linux). No Linux pode ser preciso `sudo apt install python3-tk`.

## Passo a passo

**1 · Conta e destino**
1. Clique em *Abrir my.telegram.org*, entre com seu número, abra *API development tools* e crie um app (nome livre). Copie o `api_id` e o `api_hash` para o GALOCHAT. Isso é feito uma vez só.
2. Digite seu telefone com o código do país (`+5511999999999`) e clique em *Enviar código*.
3. Digite o código que chegou no Telegram (e a senha, se sua conta tiver verificação em duas etapas).
4. Escolha o canal de destino ou clique em *Criar canal privado…*.

**2 · Cursos**
- *Adicionar pasta…* adiciona uma pasta como um curso. Se a pasta tiver várias subpastas, o programa pergunta se cada uma é um curso diferente.
- *Adicionar .zip…* adiciona um ou mais zips; cada um vira um curso.
- Clique em um curso para conferir a prévia com módulos e hashtags e para editar nome, categoria, tipo, prefixo das hashtags e capa.

**3 · Publicar**
- Ajuste as opções e clique em *Publicar*. *Parar* interrompe, e o próximo *Publicar* continua do ponto em que parou.

## Como organizar os arquivos

```
Meus Cursos/
├─ Excel Inovador/            <- um curso (pasta com zips e/ou videos)
│   ├─ capa.jpg               <- opcional
│   └─ parte1.zip
│        └─ Excel/01 - Comece por aqui/1 - Boas-vindas.mp4
│           Excel/03 - Primeiros passos/2 - Interface.mp4
│           Excel/Material/apostila.pdf
└─ Outro Curso.zip            <- um zip solto tambem e um curso
```

As pastas dentro do curso viram os **módulos**; os arquivos viram as **aulas**, em ordem numérica natural (`2` vem antes de `10`). A capa é a imagem chamada `capa` ou `cover` dentro do curso; sem ela, o programa usa um quadro do primeiro vídeo. Você também pode escolher a imagem na tela.

## Bom saber

- **Limite por arquivo:** 2 GB (4 GB em conta Premium). Vídeos maiores são cortados pelo tempo e viram "Parte 1/3", "Parte 2/3"… com a mesma hashtag.
- **Prefixo das hashtags:** com vários cursos no mesmo canal, o prefixo (`#EXC_F001`) evita que a busca por `#F001` misture cursos.
- **Formatos:** MKV, MOV, TS e MP4 com H.264/H.265 viram MP4 sem perda. AVI, WMV e outros codecs antigos são convertidos para H.264 (opção ligada por padrão; pode ser desligada).
- **Não abre:** `.rar`, `.7z` e zips com senha. Extraia antes e adicione a pasta.
- **Seus dados:** ficam só no seu computador, em `%APPDATA%\GALOCHAT` (Windows). O arquivo `sessao.session` dá acesso à sua conta do Telegram; não o compartilhe.
- **Pausas do Telegram:** quando o Telegram manda esperar, o programa espera sozinho e continua.
- **Uso responsável:** publique apenas conteúdo que você tem direito de guardar e compartilhar.

## Proteção do programa

- O que você entrega aos usuários é **só o `GALOCHAT.exe`**. O código-fonte não acompanha o executável.
- Antes de compilar, o código passa por uma etapa que remove comentários, descrições e nomes internos legíveis, e é transformado em bytecode dentro do `.exe`. Isso dificulta bastante a leitura por pessoas e por sistemas de inteligência artificial.
- Os metadados do `.exe` levam a autoria **F.ER ACADEMY**, e não dados do seu computador. Gerar pelo GitHub (acima) garante que nada pessoal entre no arquivo.
- A proteção mais forte é a legal: o `LICENSE.txt` declara a F.ER ACADEMY como dona e proíbe cópia, engenharia reversa e uso do código para treinar IA.

Nenhuma proteção de software é absoluta: qualquer programa que roda na máquina de alguém pode, com esforço, ser analisado. As camadas acima elevam muito esse custo e deixam a autoria e os direitos registrados de forma clara.

## Para a própria F.ER ACADEMY (manutenção)

- `galochat_core.py`: toda a lógica (plano, FFmpeg, publicação, registro).
- `galochat_app.py`: a janela (Tkinter).
- `galochat_brand.py`: cores e logo da marca.
- `tools/empacotar.py`: gera o `.exe` protegido.
- `python tests/test_fluxo.py`: testa o fluxo completo com um Telegram simulado e FFmpeg real.
- `python galochat_app.py --selftest`: confere FFmpeg e leitura de vídeo.

Guarde esta pasta de código em local privado. Para o público, publique apenas o `GALOCHAT.exe`.
