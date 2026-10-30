# Dashboard BD_Thopen — produto do cliente

Flask na porta **5080**. Réplica do Power BI "Performance da Usina" que o cliente Thopen acessa. **Com login por pessoa
desde 16/10/2026** (seção abaixo; até então público, sem senha): com `THOPEN_LOGIN=1` cada conta entra com usuário (o de
hoje do cliente, ou um e-mail) e senha e vê só as carteiras dela. O app são catorze arquivos (a lista no `deploy/_package_thopen.py`, `ITENS`). Lê tudo do PostgreSQL pela
Gridco Performance API; não abre planilha nenhuma. Ver o `CLAUDE.md` da raiz para as convenções gerais.

**É produto de cliente, não ferramenta interna.** Mudança aqui é visível para fora: teste antes
e evite alterar layout sem pedido.

## Onde roda (conferido em 08/10/2026)

- **O cliente é servido deste PC**, não da nuvem: `C:\GridcoAuto\servir_thopen.py` sobe o app com waitress
  (`127.0.0.1:5080`, 8 threads, um processo só) a partir do clone `C:\GridcoAuto\PerformancePainel\thopen`, e o
  `C:\GridcoAuto\vigia_thopen.ps1` (tarefa agendada "Dashboard Thopen - Vigia", a cada 3 min) religa o servidor se a
  5080 não escuta e reabre o túnel **trycloudflare** quando a URL de `C:\GridcoAuto\thopen_url.txt` não responde em
  `/api/t/versao`. O quick tunnel troca de endereço quando reabre: o link do cliente muda. **A tarefa roda na bateria e
  recupera a hora perdida no descanso** (desde 24/10/2026: com o padrão do Agendador, "só na tomada", ela parou em
  23/10 às 17:15 com o notebook na bateria, o servidor caiu e ninguém religou até 12:05 do dia seguinte). Não
  acorda o PC (sem `WakeToRun`): com o notebook dormindo, a 5080 fica fora até ele acordar. (A docstring do
  `servir_thopen.py` ainda fala em ler o `.xlsx` do OneDrive — vale o código, que só importa este app.)
- **Atualizar o cliente:** `git pull` no clone e reiniciar SÓ o `pythonw` do `servir_thopen.py` — achar o processo pelo
  caminho do script na linha de comando, nunca pelo nome (há outros `pythonw` na máquina) — sem tocar no `cloudflared`
  (o da 5050 também roda aqui). O vigia religa o servidor em até 3 min.
- **Railway: fora do ar** (404 em 08/10/2026). `railway.toml` e `render.yaml` da RAIZ continuam descrevendo o deploy de
  nuvem (`gunicorn dashboard_thopen:app --chdir thopen ... --workers 1`, 334 MB de pico por worker);
  `deploy/Procfile` e `deploy/railway.toml` daqui nunca foram lidos (o Railway lê a raiz).
- **Instalador por zip** (`python thopen/deploy/_package_thopen.py` → `deploy/thopen-app.zip`): os 14 arquivos do app +
  `requirements-thopen.txt`, `railway.toml`, `render.yaml` e um LEIAME com as variáveis; aborta se um segredo entrar.
  Arquivo novo que o dashboard importa entra em `ITENS` — o `tests/test_thopen_operacao_rota.py` confere ITENS contra
  os imports (o zip só com os 3 arquivos de antes de 08/10 nem subia).
- Sobra do tempo da planilha, que o app não lê: `data/`, `Atualizar Nuvem.bat`/`atualizar_nuvem.ps1`.
  `tunel_guardian_5080.ps1` está desativado desde 27/08 (brigava com o vigia) — **não rearmar**. O
  `Iniciar Dashboards.bat` da raiz derruba a 5080 do cliente e não sobe nada (ver o CLAUDE.md da raiz).
- Para testar código novo: **nunca na 5080** (neste PC ela é a do cliente). Portas de teste: **5081** sem login e
  **5082** com o login ligado (`THOPEN_LOGIN=1`, `THOPEN_PREFIXO=/performance`, a privada do par de 14/10 e as contas
  REAIS do Nexus), cada uma atrás de um túnel trycloudflare próprio; ver "Como provar".
- **Destino: o servidor da T.I.**, em `https://app.gridco.com.br/performance/` (entrada em `/performance/login`), no
  lugar do Dashboard Thopen com login próprio que a T.I. montou lá (campos Usuário e Senha). Roteiro e `thopen.env` em
  `C:\GridcoAuto\entrega-ti\thopen-login-2026-10-14\`. **Desde 27/10/2026 o servidor anda sozinho com a `main`**
  (Levi: "A TI já está subindo automático, assim que vc commita já carrega no server"): push = cliente atualizado.
  O 5080 deste PC ainda roda; atualize-o do mesmo jeito. Por isso novidade sobe fechada ao cliente (seção
  "Liberação ao cliente").
- **O 5080 deste PC com o login ligado (16/10/2026**, Levi: "com login claro"): o `servir_thopen.py` põe
  `THOPEN_LOGIN=1` e `THOPEN_PREFIXO=/performance` (o mesmo caminho do servidor da T.I.: o link de senha do Nexus,
  `https://app.gridco.com.br/performance/convite/...`, vale no túnel trocando só o endereço; a raiz do túnel leva à
  entrada), e os segredos vêm do `.env` da raiz do clone (gitignorado): `THOPEN_ACESSOS_CHAVE_PRIVADA`,
  `THOPEN_SESSAO_CHAVE`, `GRIDCO_SQL_TOKEN`, `THOPEN_CONTESTACAO_CHAVE_PUBLICA`, `FRACTTAL_CLIENT_*` e os
  `THOPEN_TEAMS_*` (o do COS ainda falta). O cliente só entra com a conta criada em Nexus → Acessos dos clientes.
  **O vigia aceita 401** no `/api/t/versao` (é o painel respondendo sem sessão; erro da Cloudflare é 502/530): sem
  isso ele reabria o túnel a cada 3 min. Voltar ao painel aberto: `THOPEN_LOGIN=0` no ambiente do processo.

## Login por pessoa (14/10/2026)

Levi, 14/10/2026: "É possível implementarmos uma visão de login e senha para o dashboard thopen?" — por pessoa, ligada a
um cliente; contas administradas **no Nexus** (Contratos e clientes → Acessos dos clientes); o painel sobe no **servidor
da T.I.** em `https://app.gridco.com.br/performance/` (entrada em `/performance/login`). Spec:
`docs/superpowers/specs/2026-10-14-thopen-login-por-pessoa-design.md`. Código: `acessos.py` (contas, senhas, convite,
limite de tentativas), `livro_banco.py` (ler/acrescentar livro do banco, genérico), o portão e as rotas no
`dashboard_thopen.py`, `templates/entrar.html`.

- **Desligado = o painel de antes.** Sem `THOPEN_LOGIN=1` nada muda (o PC do cliente ficou assim até 16/10/2026).
- **Quem grava o quê.** As contas vêm do Nexus (livro `nexus_acessos_clientes` · `dim_conta_cliente`), relidas a cada
  2 min: desativada lá = fora daqui em até 2 min (medido 37 s no ensaio). As senhas, este app grava (livro
  `thopen_acessos` · `senhas`, 1 linha por senha definida; vale a mais nova da conta). Um livro por sistema.
- **Cifra.** O nome e o e-mail chegam selados para a PÚBLICA deste app (`dados_5080`, X25519 + HKDF + AES-GCM, info
  `thopen-acessos/v1`); só a privada (`THOPEN_ACESSOS_CHAVE_PRIVADA`) abre. A senha vira hash scrypt (werkzeug) e vai
  ao banco cifrada com uma chave derivada da mesma privada (`cs1:`). O banco tem leitura aberta: nada em claro. Sem a
  privada, ninguém entra ("login não configurado"), nunca abre sem senha. Conta cujo selo não abre (outro par) não
  entra: no Nexus, "Gerar link" sela de novo para a pública em uso.
- **Convite.** O Nexus gera o link de uso único (72 h; no banco só o sha256): `/performance/convite/<token>` → "Definir
  senha" (mínimo 6 caracteres desde 15/10/2026, para o cliente repetir a senha de hoje; as duas iguais) → já entra.
  **Um envio só** (15/10/2026, a conta Performance: o "Salvar e entrar" clicado três vezes — o 1º gravou a senha e entrou,
  os outros mostraram "Este link já foi usado" e pareceu erro): o botão trava no 1º clique, e link usado com a pessoa já
  conectada vai direto ao painel.
  **Usuário de entrar** (15/10/2026, Levi: "Mesmo usuário e senha de hoje" — o login da T.I. em `/performance` pede
  Usuário e Senha): a conta traz `usuario` (um nome de usuário ou um e-mail; sem caixa nem espaço) e `email` só quando
  ele é e-mail; as contas de antes entram pelo e-mail.
- **Com a pessoa conectada** (15/10/2026): o nome de quem entrou e o **Sair** ficam na faixa laranja do topo, ao lado da
  marca (Levi: "não tem um botão de sair da conta no dashboard thopen" — no fim da barra de botões ele saía da tela nas
  janelas estreitas). Na contestação a pessoa escreve só o nome ("não precisa preencher o e-mail, só o nome!"): o
  contato é o da conta, o e-mail dela ou "usuário X (conta do painel)" (`contestacao.validar(..., contato_da_conta)`). Link usado = há linha de senha com o mesmo hash; vencido,
  usado ou de conta desativada: a tela diz qual e pede outro à Grid Co.
- **Portão** (`before_request`): sem sessão, página → `/login` e `/api/...` → 401 (o `get` da tela volta à entrada).
  Usina ou carteira fora da conta → 403 (overview, diário, operação, rondas, geral, contestar); OS de ronda de outra
  usina → 404. O papel `grid` vê todas as carteiras; só ele força a releitura (`/api/t/reload`) e grava os Comentários
  adicionais (403 aos outros; a tela esconde o Atualizar e os botões). A contestação vai com o nome e o e-mail da conta.
- **Tentativas.** 5 erradas em 15 min por IP ou por conta = "Muitas tentativas" (em memória, um processo).
- **Sessão.** Cookie próprio `thopen_sessao` (não colide com o `session` da plataforma nem com o `nexus_sessao`),
  caminho = o prefixo, HttpOnly, SameSite=Lax, Secure (`THOPEN_COOKIE_SEGURO=0` só em http local), 12 h. Assinado com
  `THOPEN_SESSAO_CHAVE` (sem ela, uma aleatória por processo: todos entram de novo a cada reinício).
- **Caminho.** `THOPEN_PREFIXO=/performance`: o `_Prefixo` aceita o pedido com ou sem o prefixo (o Caddy pode tirar ou
  não) e toda chamada da tela sai de `RAIZ` (`request.script_root`).
- **No servidor da T.I.** O `/performance` JÁ existe lá (conferido 14/10/2026): um Dashboard Thopen com login próprio
  da T.I. (campos `user`/`senha`, waitress), fora dos nossos repositórios. Este app o SUBSTITUI no mesmo endereço; os
  usuários de lá não migram. Roteiro em `C:\GridcoAuto\entrega-ti\thopen-login-2026-10-14\ROTEIRO-DEPLOY.txt` (serviço
  systemd do clone da plataforma, 1 worker; o destino do `/performance` no Caddy passa a ser ele; o antigo só para, é
  a volta) com o `thopen.env` (segredo). Variáveis: `THOPEN_LOGIN=1`, `THOPEN_PREFIXO=/performance`, `THOPEN_ACESSOS_CHAVE_PRIVADA`,
  `THOPEN_SESSAO_CHAVE`, `GRIDCO_SQL_TOKEN` (grava as senhas). O par de 14/10/2026 está em
  `C:\GridcoAuto\entrega-ti\acessos-chaves-2026-10-14\` (a privada e a chave da sessão nos `.segredo`, nunca
  impressas; a pública vai no Nexus, Base → Chaves do Nexus). Perder a privada = todas as senhas param de valer (cada
  pessoa recebe link novo).
- **Como provar.** `python -m pytest -q tests/test_thopen_acessos.py tests/test_thopen_login_rota.py`; o teste cruzado
  mora no Nexus (`tests/test_contratos_acessos_clientes.py` com `PLATAFORMA_REPO`). Ponta a ponta em 14/10/2026 no banco
  de verdade (Nexus de ensaio 5072, este app com login em `/performance` na 5088): conta TESTE criada no Nexus → link →
  senha → só a carteira Thopen (outra usina, outra carteira e o Atualizar: 403) → link de novo: "já foi usado" → sair e
  entrar → desativada no Nexus, fora em 37 s. A conta TESTE ficou no livro, desativada.

## Liberação ao cliente (27/10/2026)

Levi: "vamos subir as atualizações primeiro para o usuário de performance, o usuário thopen que é o do cliente só vê
se eu liberar". Como o push já chega ao cliente, toda tela ou aba nova sobe com uma chave em `LIBERADO_AO_CLIENTE`
(`dashboard_thopen.py`) valendo `False`: o papel `grid` (a conta Performance) vê; a conta de cliente (a `thopen`) não
vê a aba (o `libera` do template) e a rota responde 403 "ainda não está liberada" (`_portao`). Liberar = o Levi pede,
a chave vira `True` e sobe. Mudança dentro de uma tela que o cliente já vê não tem chave sozinha: precisa dos dois
caminhos (`_liberado(chave)` escolhe) até a liberação, e o velho sai quando ela vem. Login desligado (as cópias de
prova) vê tudo, como o `_e_grid`. Fechada hoje: `zeladoria`. Prova:
`tests/test_thopen_liberacao.py`.

- **A disponibilidade da Thopen pelas normalizações do COS (29/10/2026; liberada ao cliente em 30/10/2026):** a régua
  em `plataforma/CLAUDE.md`, "A Thopen pelas normalizações do COS". Ficou fechada ao cliente um dia (a chave
  `disponibilidade_cos` e as abas `_fracttal` com a conta de antes) e foi liberada depois da conferência com as barras do
  Diário (Levi: "o que fizer manda para frente"); no mesmo dia a conta de antes saiu ("garanta que a única fonte seja a
  de normalizações"): uma conta só, para todas as contas. O comentário da OS do COS leva as proteções que atuaram
  ("Desligamento Usina Trip 27ABC/86 de ... a ...; OS 17001"; "Falha de comunicação com a geração parada, Usina de ...;
  OS ..."; "sem OS" quando a normalização não tem), com a volta de cada usina quando o Levi a corrigiu numa só, e não
  vai buscar o trip no Fracttal. A Metodologia, a nota dos Registros e as mensagens da tabela de comentários dizem a
  fonte ao cliente (30/10/2026): as paradas registradas pelo COS na Ronda COS e, nas usinas fora dela, os comentários
  da equipe; "OS do Fracttal" ficou só nas strings, que seguem vindo das OS de recomposição. Prova:
  `tests/test_thopen_disp_cos.py` e `test_metodologia_disponibilidade_pelas_paradas_do_cos_sem_geracao`.
- **As usinas que a Ronda COS não cobre, pelos comentários do BD_Thopen (30/10/2026**, Levi: "A disponibilidade dessas
  UFVs devem ser calculados de acordo com os comentários do BD_Thopen e os comentários também"): Rondonópolis, Aruanã,
  AP. do Taboado, Areia Branca, Monte Aprazível, Nova Iguaçu, Sapopema, Segredo e Cambé (`disp_comentarios.USINAS`; as
  Sol Maior GD I a V da lista dele não estão no dashboard). De 10/2026 em diante a disponibilidade de cada dia sai do
  PERÍODO escrito no comentário da equipe ("... - 04/10 às 09:35h ao 09/10 às 07:14h"), na janela de sol 06–18 h, e o
  comentário da tela é o do BD (a tabela por dia, com a disponibilidade; o dia em 100% com comentário também aparece).
  A coluna de disponibilidade do BD não serve em outubro (vazia; a Nova Iguaçu em 100% e a Segredo em 0% contra o
  comentário). Decisões dele: falha de comunicação não conta; desligamento de cabine conta 1 ÷ nº de cabines;
  desligamento de inversor, os inversores citados na linha ("1.3 e 1.4"; um, se não citar) ÷ os da usina. **O de-para de
  usina, cabines e inversores é a própria aba do BD_Thopen** (`_estrutura_bd`: as colunas "Inversor N.M", N = a cabine;
  Levi, 30/10/2026, "faça um de-para simples ... só usina, cabines e inversores", e "no dashboard, pela aba do BD":
  AP. do Taboado, Areia Branca, Monte Aprazível, Nova Iguaçu e Rondonópolis nem estão no Registro mestre do Nexus);
  sem as colunas, as cabines do cadastro do Nexus (`nexus_estrutura_usina · dim_cabine`); sem nada, a usina inteira.
  Ex.: Segredo 5 cabines e 40 inversores, Nova Iguaçu 2 e 18. O mesmo evento escrito
  em vários dias conta uma vez; o mês anterior entra na leitura (o desligamento de 30/09 que segue em outubro). Vale no
  card do mês (`/api/t/operacao`, `fonte_disp` = "bd_comentarios"), no Diário, na Visão Geral e nos Registros
  (`_disp_dias`). A Cambé tem normalizações do COS na plataforma: no dashboard vale o BD. Prova:
  `tests/test_thopen_disp_comentarios.py`.

## Dados

**A fonte é o PostgreSQL** (Levi, 28/08/2026): a coleta continua ESCREVENDO no `BD_Thopen.xlsx`,
o `sync_gridco_api.py` leva o arquivo para o banco, e o dashboard só LÊ do banco. `fonte_api.py`
monta o mesmo workbook em memória a partir da Gridco Performance API (`row_number` = a linha original; data ISO volta
a ser `date`) — por isso todos os leitores continuam sendo código de worksheet.

- `GRIDCO_API_TTL` (600 s) é o intervalo de recarga; `/api/t/reload` (botão Atualizar) derruba o cache na hora.
- **A recarga roda DENTRO da requisição, sob o `_lock` do `_wb()`**: o 1º acesso depois do TTL esperou **~130 s**
  (medido em 08/10/2026; a docstring do `fonte_api` diz ~4 s, medido na migração). Problema conhecido, à parte.
- **Se a API cair** há dois degraus e só dois: o workbook já em memória e o **cache em disco**
  `cache_bd_thopen.json.gz` (`GRIDCO_API_CACHE`), a última leitura boa, com a idade real na tela (`/api/t/fonte`,
  `/api/t/versao`); 60 s sem tentar de novo depois de uma falha. **Não há fallback para `.xlsx`**, nem
  `THOPEN_FONTE`, nem `THOPEN_DATA_DIR` (saíram em 28/08: "tem que ser 100% postgresql"). Sem API e sem cache, a rota
  dá erro.
- Token: `GRIDCO_SQL_TOKEN` do ambiente, do `tokens.txt` da raiz ou, por último, do `.env` da raiz (`fonte_api._token`;
  a leitura hoje é aberta; vai assim mesmo). O `.env` entrou em 19/10/2026: o clone do cliente tinha só o `.env`, e no
  5080 com login a senha do link e a contestação não gravavam, caladas, de 16 a 19/10
  (`tests/test_thopen_fonte_api_token.py`).
- O único dado que o app GRAVA: `comentarios_adicionais.json` (campo digitável do Diário; `COMENTARIOS_DIR`).
- Trocar a fonte, ou qualquer mudança no `dashboard_thopen.py`, se prova com número: `_snap_dash.py` fotografa as
  ~1.300 respostas das rotas e `_diff_snap.py` compara antes × depois (0 diferença). Os dois não estão no repositório;
  a última cópia ficou no scratchpad da sessão `7c3991ac-...` (`%TEMP%\claude\...\scratchpad\`).
- **Nome da usina na aba `Historico`**: o 5080 procura o nome EXATO. Quando um ano está gravado com outro nome, ele
  some da tela calado (Levi, 09/10/2026: "O dado de Produzida 2025 sumiu" — a Nova Londrina tinha 2025 como "Nova
  Londrina 1"). Os de-paras são explícitos, nunca regra automática: `_META_NOME` para a meta e `_HIST_NOME` para a
  produção dos anos anteriores (Nova Londrina, Rondonópolis, Monte Aprazível, Poconé 1, Vargem Grande 1, Araçoiaba da
  Serra 1/2 = "A"/"B" pela palavra do Levi). O ano no nome do 5080 vence o mesmo ano no outro nome — nunca soma.
  Para achar o próximo caso: nomes de `Produzida (...)` da `Historico` que não estão em `/api/t/usinas`. (Esta regra
  está na `main` desde `fb322ce`; o worktree da rodada 3–5 nasceu antes dela e só a recebeu em 16/10/2026, quando a
  Nova Londrina apareceu sem 2025 no link de teste.)

## Registros (23/10/2026)

Levi, 23/10/2026: "no botão ao lado de metodologia eu quero um de Registros / Quero uma visão de drill down / Carteira,
usinas, ao expandir usinas aparece as colunas que tem no anexo / a pessoa vai poder exportar, ao exportar vai ter só
usina/data/geração/irradiação/disponibilidade / Geração e irradiação continua sendo da BD_Thopen, disponibilidade vai ser
da forma nova! / quero que a visão seja em corner-shape bevel conforme referências".

- **Rotas.** `GET /api/t/registros?carteira=&ano=&mes=` (`_registros`): cada usina da carteira com o mês (soma da
  geração e do IPOA, média da disponibilidade) e os dias `{data, ger, ipoa, disp}`. `GET /api/t/registros.xlsx` (mesmos
  parâmetros): o Excel só com Usina, Data, Geração (kWh), Irradiação (kWh/m²) e Disponibilidade (%), a disponibilidade em
  fração com formato de %. Carteira fora da conta: 403 (o portão, como a Visão Geral); parâmetro inválido: 400.
- **De onde.** Geração e IPOA do `_daily_records` (o BD_Thopen, com a correção da Polaris e as planilhas de Copel e
  Matrix, como o resto do painel). Disponibilidade de 10/2026 em diante pelas OS do Fracttal (`_disp_dias`, a mesma do
  card do Diário), antes a do BD. Sem a leitura das OS: `disp_carregando` e a tela avisa (nunca um 0).
- **O 0 do dia não coletado.** O BD nasce com o mês pré-criado: depois do último dia com geração ou IPOA, a geração 0
  sem IPOA é "sem dado" (—, célula vazia no Excel), não geração zero (em 23/10 a Altair tinha 22/10 assim, já com 100%
  nas OS). No meio do mês, o 0 é o que a usina gerou. Dia sem nenhum dos três fica fora.
- **Tela.** Aba ao lado da Metodologia; carteira e mês da barra do topo (o seletor de usina some, como na Visão Geral).
  Cartão da carteira, a lista das usinas e, ao expandir, a tabela dos dias. Cantos em `corner-shape: bevel` dentro de
  `@supports` (sem suporte, Firefox e Safari em 10/2026: os mesmos cartões arredondados). Fora do Ctrl+P, do Baixar PDF
  e do PDF Carteira, como a Metodologia. Em 375 px a linha da usina põe os três números embaixo do nome, com rótulo. (A
  barra do topo do painel inteiro não quebra linha: o painel é de tela larga, de antes.)
- **Medido em 23/10/2026** (cópia de prova): Thopen de outubro com 59 usinas e 1.289 linhas no Excel; a Altair com 22
  dias, 13/10 a 73,56% (a mesma conta do card do Diário).

## Zeladoria (26 e 27/10/2026)

Levi, 26/10/2026, pela sessão do Campo no Nexus: "agora faz a mesma tela no dashboard do cliente" (a de Nexus > Campo ·
App > Zeladoria, no modelo "Rondas Sujidade e Vegetação"). Decisões dele: **o Nexus publica a visão pronta** e o 5080 só
mostra (a conta fica num lugar só); a evolução agrupada pela **carteira**; "Aprovar recomendação" e "Solicitar orçamento"
**fora** por enquanto. Código: `zeladoria_cliente.py` (puro), `fonte_zeladoria.py` (leitura), a rota `/api/t/zeladoria` e
a aba no `dashboard_thopen.html` (`renderZeladoria`, `_zlDesenha`, `abrirZelUsina`). **Fechada ao cliente desde
27/10/2026** ("zeladoria pode tirar da visualização do cliente thopen"): só o papel `grid` vê a aba.

- **De onde.** O livro `nexus_zeladoria` do banco (Nexus, commit d6f37d7, 27/10/2026; a visão é registrada no catálogo do
  Nexus): `zeladoria_semana`, uma linha por usina × semana COM leitura (segunda a domingo, 12 semanas até a corrente, os
  níveis da última leitura da semana, a recomendação e a situação sobre a leitura daquela semana, datas em data_id
  AAAAMMDD), e `atualizacao` (uma linha: `semana_corrente` e `linhas_qtd`). O Nexus grava de hora em hora (entre :32 e
  :37) e troca o livro inteiro. Os nomes moram em `zeladoria_cliente` (WORKBOOK, ABA, CAMPOS).
- **Leitura** (`fonte_zeladoria`): o mesmo cuidado do `fonte_operacao` — a requisição nunca espera a rede, relê em segundo
  plano a cada 10 min, só aceita a leitura que bate com `linhas_qtd` e guarda a última boa em `cache_zeladoria.json.gz`.
  Sem o livro: a aba diz "carregando". `THOPEN_ZELADORIA=0` desliga.
- **A usina** sai do de-para do sistema do 5080 pelo `usina_id` do Nexus (o mesmo que o `fonte_operacao` lê): 80 das 131
  usinas do Nexus têm a linha; das 81 da Thopen, só a Ouro Branco (usina_id 105) não.
- **A tela.** Semana (a corrente e as 4 anteriores; a corrente "em andamento" mesmo sem linha), usina e situação; seis
  números (com leitura na semana, vegetação e sujidade acima de 3 e a média, recomendações a programar); a evolução das 8
  semanas da carteira, com a linha da carteira "acima de 3 / com leitura"; as recomendações (a mais grave primeiro, a
  feita fora da fila); a tabela por usina (a última leitura até a semana escolhida, com a seta para a anterior); a gaveta
  (as 8 semanas, a recomendação e o botão "Ver a ronda e as fotos", que abre a janela das rondas na ronda da última
  leitura); e a régua "Como classificamos" (`operacao_mes.REGUA`). A situação em palavras do cliente: "a programar",
  "programada para 28/10", "feita em 23/10"; sem nome de técnico. Fora do PDF.
- **Prova:** `tests/test_thopen_zeladoria.py` (semanas, carteira, números, fila, nível 3 que não pede ação, data_id,
  conferência, rota, portão, tela).

## Acoplamento com a plataforma

`plataforma/app.py` importa este módulo (`sys.path` para `thopen/`) e usa **7 atributos**: `_CARTEIRA_DE`,
`_registro()`, `_daily_records()`, `_daily_inversores()` (histórico por inversor), `_meta2026()` (metas do relatório
semanal), `_wb()` e `_state["daily"]` (o índice das abas diárias, para achar a aba da usina). **Não mude nome,
assinatura nem formato de retorno desses sem checar o uso lá.** E **nada pode rodar no import** (sem thread, sem
rede): a plataforma importa o módulo, e com ele o `fonte_operacao` e o `operacao_mes`.

## Carteiras

Os botões de carteira saem do dicionário `CARTEIRAS` neste arquivo (de-para carteira → usinas).

Nenhuma carteira depende de Excel: Copel, Matrix, Caroá e Piancó moram na aba **Histórico Carteira** do BD_Thopen (a
coluna `Fonte` separa) e a Polaris tem aba diária por usina + a aba **Histórico Polaris**, que é a camada de CORREÇÃO
MANUAL — o que estiver escrito lá sobrescreve o automático campo a campo, e célula vazia não apaga nada. Sem a aba, a
carteira fica sem dado: não há Excel de reserva (as docstrings que ainda falam do Budget como fallback são de antes de
28/08).

## Operação no Mês (08/10/2026)

**Para que serve.** Pedido do Levi: por usina e mês, quantas strings ficaram sem corrente, quantos trackers distintos
pararam e o nível de zeladoria das rondas — "tem que garantir a confiabilidade e prever possíveis erros". Aparece **só
de 10/2026 em diante** (`operacao_mes.DESDE`): um card na aba Diário (ao lado da tabela de comentários desde a
rodada 4), a tabela de comentários do Diário com uma linha por dia e a disponibilidade do Gerencial (rodada 4), a
**contestação** do cliente sobre um dia da tabela (rodada 4), a janela das **rondas do mês** (ícone no canto do card,
com as fotos — rodada 3) e a aba **Metodologia**. Antes de 10/2026 a tela e a folha ficam exatamente como eram (teste,
e o PDF de setembro idêntico, pixel a pixel, ao do HEAD).

### De onde vem o dado

Tudo pela mesma API do BD_Thopen (`fonte_api._get`, mesmo token), em outros workbooks:

| Workbook · aba | Quem publica | Para quê |
|---|---|---|
| `falhas_performance` · `strings_os` | plataforma do servidor, de hora em hora | Strings: as OS de recomposição de string do Fracttal, pela data do evento |
| `falhas_performance` · `trackers_episodios`, `trackers_dia` | idem | Trackers distintos no mês e por dia |
| `falhas_performance` · `cobertura` | idem | Separa "0" de "sem monitoramento" |
| `falhas_performance` · `atualizacao` | idem | Contagem de cada aba por mês (conferência da leitura) e fim do período |
| `falhas_performance` · `strings_episodios` | idem | Lida (lista branca), mas não dá mais número ao card |
| `falhas_performance` · `disponibilidade_dia` | idem, do índice do Gerencial › Disponibilidade (`frac_disp_index.json`, OS do Fracttal) | Rodada 4: a coluna Disp (%) da tabela e o card "Disponibilidade Usina" de 10/2026 em diante |
| `falhas_performance` · `disponibilidade_os_dia` | idem, da MESMA varredura da `disponibilidade_dia` (a parcela de cada OS em cada dia) | 14/10, noite: o comentário de cada dia abaixo de 100% (o que cada OS tirou naquele dia e em que horários). Lidos só `mes, dia, usina, usina_fracttal, os, tipo, escopo, kwp, inicio, fim, aberta, trechos, h_perdidas` — a origem fica fora; o nº da OS entra desde 15/10/2026 à tarde (Levi: "quero o número desse OS"), para o comentário. A `disponibilidade_os` (as OS do mês) não é mais lida |
| `rondas_app_campo` · `OS de ronda` | servidor do App de Campo, regravado de hora em hora (aos :50) | Zeladoria e a janela das rondas (OS, horário, níveis, checklist) — com e sem OS |
| `cadastro_nexus` · `de_para` | Nexus (sistema "BD_Thopen · Dados Gerais Usinas") | Usina do 5080 → `usina_id` das rondas |

As colunas e abas novas do `falhas_performance` e as regras delas (comunicou, origem da quantidade, cobertura) estão no
`plataforma/CLAUDE.md`, seção "Falhas de strings e trackers". **Rondas: só o livro do App** (Levi, 09/10: "as rondas já
foram atualizadas até hoje porém no server não está atualizando, tem que ser dinâmico"). Até 09/10 o 5080 lia o
`campo_nexus · rondas` (coletor do Nexus, parado em 02/10) e a carga única das rondas sem OS (06/10); o livro do App
tem as duas (as 125 sem OS e 580 das 584 rondas do `campo_nexus`) e chega a hoje. Ele não tem `usina_id`: sai do de-para
do Nexus pelo código do ativo (`BD_Performance · Base UFV`/`Tickets`) ou pelo nome da usina no Fracttal
(`Fracttal · Classificação 1`) — `rondas_cliente.mapa_usinas`/`da_app`. As **fotos** não vêm da API: são os anexos da
OS no Fracttal (`fotos_ronda.py`, abaixo).

### As regras (`operacao_mes.py`, puro: sem rede e sem Flask)

- **Strings = OS do Fracttal** ("Strings é OS", Levi, 08/10 à tarde — não a régua de 2 h da plataforma). Conta as OS de
  recomposição de string com a **data do evento** no mês; cancelada fica fora; a mesma OS lida duas vezes (nº + usina
  + inversor) conta uma. OS com as strings listadas: strings DISTINTAS por (usina das falhas, inversor, string) — a
  usina entra porque Primavera 1 e 2 (uma Primavera no 5080) têm cada uma o seu "Inversor 1.1". OS sem lista: soma o
  `qtd`. A quantidade sai do contrato com o OS Creator, a linha `Strings sem corrente: N (Ipv3, Ipv7, ...)` na
  observação da tarefa de cada inversor; sem ela, das strings citadas no texto. **Outubro de 2026**: OS sem
  quantidade nem citação foi completada pela Grid (`origem = estimado`, as strings que a régua viu sem corrente naquele
  inversor no dia do evento — decisão do Levi, "sem tocar no Fracttal") e o card avisa "parte das strings estimada pela
  Grid". Depois de outubro, OS sem quantidade fica fora da soma e vira aviso ("N OS de string sem quantidade").
- **Trackers = ocorrências da plataforma** com a usina comunicando ("quando fica parado sem comunicação essa ocorrência
  é ignorada; se a usina comunicou inversor ou string então aí conta"). DISTINTOS por (fonte, `plant_id`, tracker) nos
  episódios com `dias_comunicou > 0` ou `dias_sem_prova > 0` — o dia corrente, sem a geração fechada, conta (não é falha
  de comunicação comprovada; Barretos e Matão 2 só provam pela geração). Nunca menos que o maior número de um dia da
  tabela. A chave leva `plant_id` porque a Brodowski são dois cadastros com TRK1..52 cada: pelo nome dava 52 em vez de
  103.
- **Zeladoria** = a ÚLTIMA ronda do mês com nível lido (a mesma régua do Relatório Semanal e do Nexus): sujidade dos
  módulos e altura da vegetação, de 1 (limpo) a 5 (crítico), com a data, das colunas de nível do livro do App. Uma
  ronda por `usina_id + dia + hora_inicio + hora_fim`. O `Início` do App é ISO em **UTC**: o dia é o de Brasília
  (−3 h). Ronda sem OS (OS não criada) vale para a zeladoria. A régua de 5 níveis, com a frase de cada um, mora
  SÓ em `operacao_mes.REGUA`: a rota manda para o card, o `render_template` manda para a Metodologia; o HTML não
  repete frase nenhuma (duas cópias divergem).
- **Nomes falhas → 5080**: igualdade sem acento + `ALIAS_FALHAS` (Marajoara I, Piracicaba I, Nova Londrina 1/2,
  Primavera 1/2, Santo Antonio do Platina). Só linha de cliente `Thopen` (a Ipixuna do Pará da 2C nunca entra). Ouro
  Branco (um nome nas falhas, I a V no 5080) fica sem número até haver de-para por `plant_id`. Zeladoria pelo de-para
  do cadastro do Nexus, N:N (Primavera e Nova Londrina com dois ids somam os dois; Coração 1 e 2 dividem um).
- **Disponibilidade = a do Gerencial** (rodada 4, Levi 09/10: "calculada pelo Fracttal, da mesma forma que calculamos
  pelo gerencial da plataforma"; "a partir de outubro somente; antes disso é modelo anterior"). `disp_por_dia`: um
  valor por dia FECHADO, `100·(1 − h_perdidas/12)` — pelas horas e não pelo `disp` de 1 casa da aba (arredondado, a
  média do mês saía 0,01–0,02 fora do Gerencial). Usina do 5080 com mais de uma do Gerencial: média pela potência.
  Liga **primeiro pelo nome** (sem acento) e só sem nome igual pelo nome do Fracttal no de-para: Aparecida do Taboado
  1 e 2 dividem um site no Fracttal ("1 e 2 - MS") e, pelo site, as duas davam 87,53. O mês (`disponibilidade`) é a
  média dos dias, 2 casas. Conferido em 09/10 nas 100 usinas: 80 com valor, iguais ao Gerencial menos Araçoiaba da
  Serra 1 (94,19 × 94,18); 7 casam só pelo Fracttal (Córrego do Sapucaia, Marajoara 1, Nova Londrina, Piracicaba 1,
  Primavera, Santo Antonio da Platina, Vargem Grande 1); 20 fora do catálogo do Gerencial (Ouro Branco I a V, Coração
  2, Lyon, Pharma II a IV, AP. do Taboado...) ficam "—" — o modelo anterior também não tinha valor para elas em
  outubro (só Nova Iguaçu 100% e dois 0%).
- **De 10/2026 em diante, comentário e disponibilidade são SÓ das OS do Fracttal** (Levi, 14/10/2026, noite: "A partir
  de outubro quero os comentários 100% OS Fracttal. Comentários e disponibilidade! Antes deixe como estava!"). **Por
  quê** (a causa dos erros de 13 e 14/10): a tabela juntava duas contas que não se conversam — o comentário da equipe no
  BD_Thopen (hora do alarme; a disponibilidade da equipe só existe preenchida na Polaris) e a disponibilidade do
  Gerencial (abertura e fechamento da OS). Medido em 1 a 13/10, 1.300 dias-usina: em 37 dias de 14 usinas a equipe
  registrava parada e o Gerencial dizia 100% (Ipixuna II 04/10, parada longa de inversor repetida todo dia); em 90 dias o
  mesmo desligamento saía duas vezes (Ipixuna II 01/10: o comentário e a linha da OS). Os remendos de 13/10 (a OS só no
  dia sem comentário) e de 14/10 (a OS sempre, embaixo do comentário) trataram o efeito e criaram os duplicados.
  - **O comentário do dia = as OS que formaram a disponibilidade dele**, da aba `disponibilidade_os_dia` — a parcela de
    cada OS em cada dia, que a plataforma tira da MESMA varredura da `disponibilidade_dia`. Somadas, as parcelas dão a
    perda do dia (provado no índice real de 14/10: 1.203 dias-usina com perda, todos fechando). Até 14/10 o 5080 refazia
    a conta com as OS do mês (início e fim) e errava onde a conta do Gerencial não segue o início e o fim da OS: a OS
    excluída, a hierarquia usina > cabine > inversor e, na régua de então, o dia que a geração tirava da conta (Canarana
    1, 08 a 12/10: "usina parada o dia todo" ao lado de 87,5%, quando só o inversor 1.8 contou; essa régua saiu em
    15/10/2026, ver abaixo).
  - `os_por_dia` liga as linhas como a disponibilidade (`_gerencial_por_nome`: o nome vence o site). **A frase é curta
    e leva o nº da OS** (15/10/2026, tarde, Levi: "pode ficar só como: Desligamento Cabine 2 de 09/10 às 16:29h a 13/10
    às 18:21h; religamento, OS do Fracttal / invés de OS do fracttal quero o número desse OS"): "Desligamento Cabine 2 de
    09/10 às 16:29h a 13/10 às 18:21h; religamento, OS 15xxx" — o que parou ("Usina" na de usina inteira), o desligamento
    inteiro da OS, o tipo e o nº (sem o nº na linha, "OS do Fracttal"); aberta: "desde 30/09 às 10:00h, em aberto". A
    linha do dia só sai onde a OS tirou hora na conta (os trechos); o trecho do dia e a parte da potência saíram do texto
    (até 15/10 de manhã: "Cabine 2 parada o dia todo, 20% da potência da usina (...)"), e dias seguidos com o mesmo
    texto e a mesma disponibilidade viram uma linha. Duas OS de usina inteira para a mesma parada (Mandaguaçu 11/10: OS
    abertas uma por cima da outra) dividem a parcela: a que cabe nos trechos de outra não vira linha. **O trip** (23/10/2026,
    seção "Trip das OS"): com `trips` ({nº da OS: "27/86"}), a proteção entra depois do que parou — "Desligamento Usina
    Trip 27/86 de 13/10 às 17:02h a 14/10 às 07:29h; religamento, OS 16249"; sem proteção, a frase de sempre.
  - `os` no `por_dia`: lista no dia abaixo de 100%; `[]` no dia de 100%; **None** = a parcela ainda não publicada no mês
    (coluna vazia na `atualizacao`; índice de antes do deploy da plataforma) — a tela diz "ainda não foi publicado",
    nunca um dia "sem OS".
  - O `/api/t/diario` não manda o comentário da equipe nem a disponibilidade do BD nesses meses (`_so_os_fracttal`), e a
    Visão Geral (`_resumo_usina`) usa a do Gerencial (`_disp_gerencial`, a mesma do card): a de outubro mostrava a Altair
    com 0,0% (a do BD_Thopen ainda não preenchida). Antes de 10/2026, tudo como estava (comentário e disponibilidade do
    BD_Thopen, a tabela de 3 colunas).
  - **A disponibilidade é full Fracttal, isolada da geração** (Levi, 15/10/2026: "a geração não deve afetar a
    disponibilidade"; a regra mora em `plataforma/CLAUDE.md`, "Disponibilidade por OS"): a régua do Gerencial conta as
    OS fechadas e as abertas (a aberta até o último dia fechado), o evento depois do fim usa a data de criação e nenhum
    dia sai da conta pela geração. O 5080 não lê geração para a disponibilidade nem para o comentário: de 10/2026 em
    diante só a `disponibilidade_dia` e a `disponibilidade_os_dia`; antes, a do BD_Thopen como sempre (a coluna
    "Disponibilidade Usina (%)" da aba diária, `_daily_bd`). A Metodologia diz isso ao cliente. Fica à vista o que o Fracttal registra errado, e a correção é nele (a
    plataforma lista as OS para alinhar): Mandaguaçu 01 e 02/10 a 0% ("usina parada o dia todo") gerando 8,5 e 17,5
    MWh (a OS fechada com atraso conta até o fim registrado); Álvares Machado, a OS 15410 fechada um dia depois da volta
    da usina.
- **Ronda do dia** (`ronda_por_dia`): a última ronda de cada dia (Brasília) com algum nível lido, para a frase "Ronda
  realizada: vegetação nível 3 e sujidade nível 2" na tabela.

### Estados — nunca um zero falso

| Na tela | Quando |
|---|---|
| número (inclusive 0) | medido: a usina tem `cobertura` no mês e a aba foi publicada (contagem na `atualizacao`, mesmo 0) |
| "—" nos números | sem monitoramento daquilo no mês, ou aba ainda sem contagem na `atualizacao` (coluna vazia = não publicada) |
| "sem leitura no mês" | usina ligada no de-para, sem ronda com nível no mês ("sem leitura nesta ronda" = a última ronda não leu aquele item) |
| "—" na zeladoria (`sem_cadastro`) | usina sem `usina_id` no de-para (13 em 08/10: Ouro Branco I a V, AP. do Taboado, Lyon...) — não sabemos, não é "não houve ronda" |
| "Atualizando os dados de operação" (`motivo: carregando`) | 1ª carga depois do boot sem cache em disco; a tela tenta de novo a cada 5 s por até 2 min |
| "—" com `motivo: aguardando a plataforma publicar o plant_id` | linha de tracker DESTA usina sem `plant_id` (servidor ainda sem o código novo): melhor nenhum número que a Brodowski pela metade |
| card escondido, tabela antiga | antes de 10/2026 |
| card escondido, "Comentários pelas OS do Fracttal indisponíveis no momento" | 10/2026 em diante com `THOPEN_OPERACAO=0` (`motivo: desligado`) ou erro na rota — nunca o comentário da equipe |
| "Mês em andamento, até dd/mm" | mês corrente, pelo `periodo_fim` da `atualizacao` (não pelo relógio); mês que virou e não fechou: "Dados até dd/mm" |

### Leitura (`fonte_operacao.py`)

- **A requisição nunca espera a rede**: serve o que tem e, vencido o TTL, dispara UMA recarga em segundo plano (thread
  `thopen-operacao`), fora do `_lock` do `_wb()` e do `/api/t/reload` — o botão Atualizar não relê a Operação no Mês. A
  1ª requisição depois do boot lê o cache em disco; cache gravado antes de uma aba nova entrar em `ABAS` é descartado.
- Ids das abas resolvidos pelo nome a cada carga (`/api/sheets`), páginas de 1.000 linhas.
- **Lista branca** (`ABAS`): do livro do App só são lidas as colunas de `rondas_cliente.APP` (OS, usina, ativo, início,
  fim, os dois níveis, o checklist); ficam `usina_id`, dia, horas, níveis, nº da OS, unidade e os itens do checklist.
  Técnico (nome e HMAC), nota da ronda, falhas internas, situação e texto livre não entram na memória nem no disco. Das OS de string, o número só
  serve para não contar a mesma OS duas vezes. O `/api/t/operacao` devolve só `operacao_mes.CHAVES`.
- **Conferência**: a soma das linhas de cada mês, em cada aba, tem de bater com a contagem da `atualizacao`, e linha de
  mês que a `atualizacao` não tem reprova (o sync troca linhas no lugar). Não bateu: 2ª tentativa 5 s depois; falhou
  de novo, fica a última leitura boa e espera 60 s. **Nunca deduplicar linha**: duas iguais podem ser dois trackers de
  cadastros diferentes (Assis, out/2026).
- Cache: memória + `cache_operacao.json.gz` ao lado do módulo (no `.gitignore`), troca atômica com `.tmp` por processo
  (com 2 workers do gunicorn os dois gravariam o mesmo `.tmp`). O cache leva `versao`: o de outra
  rodada não sobe (o da rodada 2 tinha as rondas sem OS e sem checklist — a janela abriria vazia até a recarga; o da
  rodada 3 não tem a `disponibilidade_dia`; `VERSAO_CACHE = 8` desde 14/10 à noite, com a `disponibilidade_os_dia` no
  lugar da `disponibilidade_os`).
- `disponibilidade_dia`: só `mes, dia, usina, usina_fracttal, pot_kwp, disp, h_perdidas`; a leitura põe `usina_ids`
  pelo nome do Fracttal no de-para (`("nome", chave(usina_fracttal))`).

### Rota `GET /api/t/operacao?usina=&ano=&mes=`

400 se faltar usina ou ano/mês inválido. Devolve exatamente `CHAVES`: `disponivel, motivo, usina, ano, mes, strings,
trackers, zeladoria {data, sujidade {nivel, frase}, vegetacao {nivel, frase}} | {sem_cadastro}, regua, parcial_ate,
atualizado_em, por_dia [{dia "DD/MM", strings, trackers, disp, ronda {sujidade, vegetacao} | null}], avisos [texto],
disponibilidade, contestar {performance, cos, zeladoria}, trip_pendente`. `contestar` diz que setores a janela pode oferecer: todos com
o banco configurado (19/10/2026); sem ele, só o que tem fluxo do Teams (item sem destino fica desabilitado). `trip_pendente`: o trip de alguma OS do mês
ainda vem do Fracttal em segundo plano (a tela relê a cada 6 s por até 1 min). Nunca técnico nem texto da OS (o 5080 é
de cliente): da OS saem só o nº (desde 15/10/2026), o tipo, o que parou e o trip. Chave nova na resposta = entrar em
`CHAVES` + teste.

### Tela (`dashboard_thopen.html`)

- **O cabeçalho em duas faixas** (Levi, 26/10/2026: "estou achando esse cabeçalho meio bagunçado"; "Proposta A com
  certeza!"): em cima as páginas (`.nav`, botões `.tab` com `data-page`), com o traço laranja na aberta e a Metodologia à
  direita; embaixo (`.toolbar`) carteira, usina e mês com o rótulo ao lado, a hora dos dados (`#subinfo`, "6,90 MWp ·
  dados de 26/10 às 17:49"; cliente e cidade no mouse) e as ações da mesma altura: Atualizar em ícone (gira enquanto relê),
  PDF da carteira e PDF da usina. O rótulo dos PDFs é o `.rb` (trocar o `textContent` do botão apagava o ícone). Até ali
  eram seis botões de tamanhos diferentes e a barra empurrava a página para o lado no celular; em 375 px as abas rolam na
  faixa delas e as ações descem para uma linha própria. Prova: `tests/test_thopen_cabecalho.py`.
- **Layout (rodada 4, Levi 09/10; 15/10)**: com o card na tela (`.com-op`), a coluna da direita fica Energia Acumulada,
  Irradiação, Disponibilidade e, abaixo delas, o card da **Zeladoria** e depois a "Produção de Energia Anual" (15/10/2026,
  Levi: "Bote a zeladoria acima de produção de energia anual"; desde 14/10, a grade única abaixo). **Só com o card**: sem ele o HTML é o de antes (o anual ao lado da tabela) —
  `_anualLugar` move o `#anualCard` entre `#colDiario` e a `.grid2` a cada `_opAjusta`. Com o anual em cima também em
  setembro, a folha saiu com a tabela partida em duas e o gráfico diário cortado.
- **Card da Zeladoria** (`#opCard`; até 15/10/2026 "Operação no Mês"; Levi: "Desse card tire OPERAÇÃO DO MÊS, deixe só
  zeladoria!"): o título é "Zeladoria" com a data da ronda, a sujidade e a vegetação com a cor do nível e a frase (a
  escala inteira no título), o ícone das fotos das rondas e a nota "Última ronda do mês, de 1 (limpo) a 5 (crítico)".
  Strings e trackers saíram do card e ficam só na tabela Ronda e Performance, que ganhou na nota a origem deles e os
  avisos da rota (parte das strings estimada em outubro). A rota não mudou (ainda manda `strings` e `trackers` do mês).
  Mostrar/esconder o card refaz o tamanho do gráfico diário (`Plotly.Plots.resize`). O PDF Carteira espera o Diário
  inteiro (`await renderDiario`, que espera o card).
- **Card "Disponibilidade Usina"**: de 10/2026 em diante, a `disponibilidade` da rota (Gerencial, 2 casas e "%");
  antes, o modelo anterior (`k.disp` do `/api/t/diario`). Sem valor no Gerencial: "—". **A tabelinha** (Levi,
  22/10/2026: "um ícone de tabelinha no canto superior direito; ao clicar mostra os dias do período e a disponibilidade!
  os que é abaixo de 100% mostra o comentário"): o ícone `#dispTab` (o mesmo botão das fotos das rondas, fora do PDF) só
  de 10/2026 em diante e com a disponibilidade das OS publicada; a janela `#dpFundo` (`abrirDisponibilidade`) lista os
  dias do mês até o último com disponibilidade, o comentário das OS só no dia abaixo de 100% (as mesmas frases da tabela
  de Comentários) e a média do mês com 2 casas, igual ao card (`tests/test_thopen_disp_tabela.py`).
- **Grade única do Diário com o card (14/10, Levi: "Energia (kWh) × Irradiação ocupando muito espaço, limita ele ao
  tamanho de Energia Acumulada no Mês até Disponibilidade Usina (%). O resto sobe!")**: o invólucro `.dg` vira uma grade
  só (`.com-op .dg`, áreas `graf graf acum / graf graf irr / graf graf disp / cmt rp op / cmt rp anual / cmt rp .`): o
  gráfico tem a altura dos três cards da direita e as duas tabelas sobem para baixo dele, ao lado do card da Zeladoria
  e, abaixo dele, da Produção Anual (15/10/2026, Levi: "Bote a zeladoria acima de produção de energia anual"). `.grid`, `.grid2` e `#colDiario` viram `display:contents`; a última linha (1fr) fica com a sobra
  das tabelas (sem ela, a tabela comprida esticava a linha do anual e empurrava o card da Operação). Sem o card, o `.dg`
  é um bloco: setembro saiu igual ao HEAD, só com a unidade "(kWh)" nos títulos. Ctrl+P de outubro (Altair, GV) em 2
  folhas e PDF Carteira em 4.
- **Duas tabelas do Diário, de 10/2026 em diante (rodada 5, Levi 13/10: "duas tabelas no espaço da mesa", "lado a
  lado")**, abaixo do gráfico:
  - **Comentários** (`_cmtPorDia`): Usina | Data | Comentário | Disponibilidade — o dia abaixo de 100%, com as OS do
    Fracttal que o formaram (ver "De 10/2026 em diante, comentário e disponibilidade são SÓ das OS do Fracttal"); cada
    OS é uma linha (`cmt-an`). Disp com 1 casa e "%", vermelho abaixo de 99. Usina fora do Gerencial: "Sem a
    disponibilidade pelas OS do Fracttal para esta usina no mês."; card carregando: "Atualizando os dados de operação.";
    sem a resposta do card (desligado, erro): "Comentários pelas OS do Fracttal indisponíveis no momento." — nunca o
    comentário da equipe. As bolinhas do gráfico Energia × Irradiação seguem a tabela (`_cmtBolinhas`, os dias com OS).
  - **Ronda e Performance** (`_rpPorDia`, `#rpCard`): Data | Vegetação | Sujidade | Trackers | Strings — o dia com
    ronda, tracker parado ou string sem corrente. O nível vem na cor da régua (a frase dela no título da célula);
    "—" sem ronda no dia. Escondida antes de 10/2026, sem o card e com erro (o Diário de antes).
  - Nas duas, **dias seguidos iguais viram uma linha** ("01 a 05/10", `_cmtGrupos`); dia com ronda nunca junta; o mesmo
    comentário com disponibilidade diferente segue como "continua". Dia fora do `por_dia`: 0 se o mês tem número, "—"
    se não. O total do card não é a soma das linhas (cada string e cada tracker contam uma vez no mês). Até a rodada 4
    era uma tabela só, com o "!" de contestação em cada linha; a frase dos números (`_opFrase`, 09/10 de manhã) saiu
    antes.
- **Nota do fim de cada tabela** (`_cmtNada(..., tipo)`, Levi 13/10: "uma observação no fim dos comentários [com] os
  dias que não aparecem por não ter acontecido nada"). Comentários: "Os dias 07 a 12/10 não aparecem na tabela porque
  não tiveram desligamento nem comentário (disponibilidade de 100%)" — sem a disponibilidade, só "comentário". Ronda e
  Performance: "… não tiveram ronda, tracker parado nem string sem corrente", só com o que foi medido (sem cadastro
  das rondas, sem "ronda"; tracker "—", sem "tracker parado"). Só até o último dia com a disponibilidade fechada (sem
  ela, o dia antes do `parcial_ate`).
- **Contestação pelo gráfico** (rodada 5, Levi 13/10: "ao invés de ficar pelas tabelas bote para contestar no gráfico
  de geração e irradiação"): clicar no dia do gráfico Energia × Irradiação (`plotly_click` → `_ctClique`, ligado uma
  vez no `#chDiario`) abre a janela do dia. Dica "Clique na barra de um dia para contestar os dados dele" sob o título
  e cursor de mão (`.contesta`) só de 10/2026 em diante, com o card e com algum canal; fora de todo PDF. Dia futuro
  do mês corrente não abre.
- **Geração possível pelo IPOA, de 10/2026 em diante** (Levi, 20/10/2026, a regra completa que trocou a conta kWp ×
  IPOA × PR da manhã do mesmo dia; spec `docs/superpowers/specs/2026-10-20-thopen-geracao-possivel-design.md`). A conta
  mora em `geracao_possivel.py` (puro) e vale na Visão Geral e na linha preta do Diário; antes de outubro, tudo como era
  (a Visão Geral de 10 colunas, a linha da irradiação). Conferido em 20/10: a Visão Geral de setembro idêntica à da
  `main`; o Diário de setembro volta à linha da irradiação (a conta kWp × IPOA × PR da `a32a688` sai de todos os
  meses). As regras:
  - **Dia que entra**: geração > 0, ou 0 com irradiação medida (a usina parada com sol). O 0 sem medição é a linha que o
    BD cria de antemão (em 20/10, hoje e ontem assim em 93 e 92 de 98 usinas): fica de fora. É **furo** ("N dias sem
    dado" na célula da usina, com os dias no título) todo dia do calendário sem dado até o **último dia coletado da
    carteira** (o mais recente em que ao menos metade das usinas tem geração: uma usina adiantada não marca as outras;
    revisão de 20/10: na Polaris, 7 de 23 usinas tinham parado em 14/10 com a carteira em 18/10 e sumiam sem
    marca). Nenhum dia coletado no mês (dia 1): "sem ETM" com o motivo "nenhum dia com geração coletado ainda".
  - **Meta e meta de IPOA do período** = Σ (mensal ÷ dias do mês) nesses dias (`_meta2026`: `meta`, `metairr`).
  - **IPOA do dia** = o da ETM se 0,3 a 12 kWh/m²; senão o GHI (coluna "GHI" da aba diária, `_ghi_por_dia`, leitor
    próprio: o `_daily_records` não muda de formato) se 1,0 a 10; senão sem medição. Os tetos: uma usina tinha GHI de
    até 25,7 "kWh/m²" (parece MJ/m²) e 41 dias de outubro IPOA de 10 a 11,6 (tracker). Cobertura (dias medidos ÷ dias
    que entram) abaixo de metade, ou sem meta de IPOA: **sem ETM** — sem possível, "sem ETM" em cinza na tabela e, no
    Diário, sem a linha e com a nota sob o gráfico. IPOA medido ajustado = Σ medido ÷ cobertura.
  - **Possível** = meta do período × ajustado ÷ meta de IPOA (o PR já está na meta); **com expurgos** = × disponibilidade
    efetiva (a `disponibilidade_dia` das OS, isolada da geração como em 15/10 — o Levi escolheu manter assim em 20/10 —,
    ponderada pelo IPOA do dia ou a meta de IPOA do dia sem medição; operação carregando = "—").
  - **Visão Geral**: Meta, Irradiação Esperada e Medida passam a ser as do período (ajustada); 4 colunas novas
    (Geração Possível, Dif. Possível, Possível c/ Expurgos, Dif. c/ Expurgos), 14 no total; o **Total** vem do servidor
    (`/api/t/geral` → `total`, `geracao_possivel.portfolio`): meta e produzida das usinas com meta, possível e real só
    das usinas com ETM, IPOA ponderado pela potência, Disponibilidade na média simples de sempre. Na folha, a tabela
    ocupa a largura e o cabeçalho quebra (1.330 de 1.330 px; sem isso ia a 1.658 e o PDF cortava).
  - **Diário**: `pontos[].possivel` = meta mensal × IPOA medido do dia ÷ meta mensal de IPOA, com `ipoa_med` e
    `fonte_ipoa` (o mouse: "Possível pelo IPOA 21.705 kWh · IPOA 4,65 kWh/m² (ETM)"); `possivel_info` diz a cobertura.
  - **As linhas do gráfico e o seletor** (Levi, 26/10/2026: "Quero que no gráfico também dê para escolher qual quer
    mostrar"; 27/10/2026: "tira o possível pelo POA e deixa só o POA medido mesmo!"): de outubro em diante a linha é o
    **IPOA medido** (`ipoa_med`, ETM ou GHI, no eixo da direita; preto e sólido; o dia sem medição fica sem ponto), com a
    Meta; antes, a irradiação de sempre. A geração possível saiu do gráfico e segue nas colunas da Visão Geral. Sem
    botões em cima ("tire esses botões de cima também, deixe só a legenda!", 27/10/2026): o clique na legenda tira e põe
    IPOA e Meta (a tirada fica cinza na legenda, para voltar); a escolha fica no navegador (`localStorage`
    `thopen_linhas`) e no Ctrl+P, no Baixar PDF e no PDF Carteira a linha tirada sai do gráfico e da legenda
    (`body.printing`). Mês com medição em
    menos da metade dos dias: a nota sob o gráfico diz quantos dias têm irradiação medida. O desenho mora no
    `_desenhaDiario` (o `renderDiario` busca e chama).
  - Medido em 20/10, carteira Thopen de outubro (59 usinas): 8 sem ETM, 11 com furo. Altair: meta do período 596.874
    kWh (1.027.950 ÷ 31 × 18), irradiação 95,18 contra 127,92 esperados, possível 444.128 kWh, produzida 439.566 (−1,03%).
  - Prova: `tests/test_thopen_geracao_possivel.py` (a regra, números à mão) e `tests/test_thopen_geracao_possivel_rotas.py`
    (rotas, setembro como era, a tela e a folha); as linhas e o seletor, `tests/test_thopen_diario_linhas.py`.
- **Zero dos eixos** (14/10/2026: "o zero do IPOA deve sempre casar com o zero de geração"): com a linha do IPOA na
  tela (a irradiação antes de 10/2026, o IPOA medido desde 26/10/2026), o eixo da direita vai SEMPRE de 0 ao maior IPOA do mês (× 1,08; sem irradiação, de 0 a 1) e o da geração é
  "não negativo"; o do Mensal também. A Assis tem IPOA 0 em todo dia de outubro: o Plotly centrava o eixo em 0 (de -1 a
  1) e o zero da irradiação ficava no meio. Só "não negativo" no IPOA não bastava (a Altair começava em 1,82). Vale em
  todo mês.
- **O valor ao passar o mouse, em todos os gráficos** (Levi, 15/10/2026: "ao passar o mouse na coluna não precisa
  mostrar o dia mas precisamos da unidade de medida certa"; "Precisa ajustar o valor e unidade de medida nessas colunas
  também"): só o valor com a unidade, no formato do Brasil (`_fmtU` + `customdata` + `_HOV`). Energia × Irradiação:
  "31.249,5 kWh" na barra, "Possível pelo IPOA 21.705 kWh · IPOA 4,65 kWh/m² (ETM)" na linha preta (ou "5,43 kWh/m²"
  na irradiação, antes de 10/2026), "Meta 31.000 kWh" na meta; Energia Acumulada no Mês e Produção
  Anual: "379.788 kWh", "3.343.983 kWh"; Mensal (cinco séries por mês): "Produzida 2026: 828,3 MWh". O padrão do Plotly
  dizia "(9, 31.2495k)", "(Meta, 379.7882k)", "(3.343983M, Meta 2026)": o "k"/"M" no lugar da unidade.
- **Unidade nos títulos** (Levi, 13/10: "está em caps lock, troque por kWh e kWh/m²"): o `.card h3` é caixa alta; a
  unidade vai num `<span class="un">` com `text-transform:none` ("ENERGIA (kWh) × IRRADIAÇÃO (kWh/m²)"). Vale em todo mês.
- **"Zeladoria"** é título (Levi, 09/10: "mesmo tamanho e fonte"): a letra do `.card h3`; "ronda de dd/mm" embaixo, menor.
- **Aba Metodologia** (mockup v3 aprovado): as fórmulas de cada número e a régua da zeladoria. **Fora do Ctrl+P, do
  Baixar PDF e do PDF Carteira.** Disponibilidade em dois blocos: "De 10/2026 em diante" (a régua do Gerencial, horas
  perdidas das OS do Fracttal sobre 12 h do dia; desde 15/10/2026 diz que a OS aberta conta e que a geração não entra,
  `test_metodologia_disponibilidade_so_das_os_sem_geracao`) e "Antes de 10/2026", que segue marcada **"A CONFIRMAR"** até o Levi
  validar o texto — não tirar o selo sem esse OK.
- **Impressão (A4)**: tudo preso ao card na tela (`#pageDiario.com-op`); sem o card, a folha sai como antes. Na folha o
  card fica compacto (nível ao lado da frase) e o Diário com o card leva `zoom: .88` (medido no PDF do Edge com o pior
  caso, Altair com dois níveis 5: até .90 cabia; .88 dá folga). A tabela por dia fica compacta na folha (eram 18 dias na
  folha do Diário; com o layout da rodada 4, a tabela abaixo da linha mais alta, cabem uns 9 com os Comentários
  adicionais); o resto vai para a folha seguinte com o cabeçalho repetido. O `beforeprint` refaz os gráficos diário,
  acumulado e anual no tamanho da folha. Rodada 4: na folha com o card as barras do anual ficam mais finas
  (`_anualAltura`: 30 px por barra, 44 na tela) — com o anual na coluna da direita, a Altair (5 barras) mandava o
  bloco "Comentários adicionais" sozinho para uma 3ª folha, no Ctrl+P e no PDF Carteira. Medido em 09/10: Altair e
  Guaratinguetá V de outubro numa folha (Ctrl+P e PDF Carteira); com o mês cheio a tabela continua na folha seguinte.
  Rodada 5: na folha a pílula do nível da Ronda e Performance encolhe (`.com-op #tblRp .rp-n`: com 12 dias a Altair
  mandava "Comentários adicionais" para uma 3ª folha); medido em 13/10, ao vivo: Altair e GV de outubro em 2 folhas
  no Ctrl+P e o PDF Carteira da Altair em 4; setembro idêntico ao HEAD pixel a pixel (mesmo cache do BD nas duas
  portas).

### Variáveis

- `THOPEN_OPERACAO=0` desliga o card e a tabela por dia sem mexer no código (o Diário volta ao de antes de 10/2026).
  Lida a cada requisição, do ambiente do processo: no PC, vale no próximo start do `servir_thopen.py`.
- `THOPEN_OPERACAO_TTL` (600 s) — intervalo entre releituras.
- `THOPEN_OPERACAO_CACHE` — arquivo da última leitura boa (padrão `thopen/cache_operacao.json.gz`).
- `THOPEN_RONDAS=0` desliga a janela das rondas e as fotos (as três rotas da rodada 3). Não mexe na contestação.
- `FRACTTAL_CLIENT_ID` / `FRACTTAL_CLIENT_SECRET` (SECRETAS, as da plataforma) — fotos das rondas e o trip das OS.
- `THOPEN_TRIP=0` tira o trip do comentário (a frase volta à de antes); `THOPEN_TRIP_TTL` (21600 s) — quanto o trip lido
  fica guardado; `THOPEN_TRIP_CACHE` — o arquivo dele (padrão `thopen/cache_trip_os.json`, gitignorado).
- `THOPEN_CONTESTACAO_CHAVE_PUBLICA` (rodada 5) — a chave pública das contestações no banco (não é segredo: só cifra);
  `GRIDCO_SQL_TOKEN` (SECRETA, o tokens.txt da raiz serve) — o token de escrita do banco. Desde 19/10/2026 são elas que
  ligam a contestação (o banco é o destino); sem as duas, só o setor com fluxo do Teams aparece na janela.
- `THOPEN_TEAMS_PERFORMANCE` / `THOPEN_TEAMS_COS` / `THOPEN_TEAMS_ZELADORIA` (SECRETAS, rodada 4; a do COS desde
  15/10/2026) — URL do fluxo do Teams de cada canal da contestação (O&M › Performance, COS e O&M › Zeladoria). Opcionais desde
  19/10/2026: aviso a mais, o registro é o banco. O COS não tem fluxo (`THOPEN_TEAMS_COS` vazia) e a contestação dele
  vai só ao Nexus. Sem banco e sem fluxo, o item fica desabilitado ("Indisponível no momento"). A `THOPEN_DUVIDA_TEAMS` da rodada 3 saiu com a dúvida.
- Os segredos vêm do ambiente ou, sem ele, do `.env`/`tokens.txt` da RAIZ do clone (`fonte_api.segredo`). O clone do
  cliente (`C:\GridcoAuto\PerformancePainel`) não tem `.env`: criar com as seis linhas no deploy (FRACTTAL_*, os dois
  THOPEN_TEAMS_*, a THOPEN_CONTESTACAO_CHAVE_PUBLICA e o GRIDCO_SQL_TOKEN, se o tokens.txt da raiz não tiver). Nunca imprimir.

### Rondas do mês (rodada 3, 09/10/2026)

**Para que serve.** Levi, 09/10: "um ícone de imagem no campo superior direito carregando a imagem das rondas em uma
estrutura parecida com" o detalhe de ronda do painel do App. Mockup aprovado ("boa! segue"; dado real da Guaratinguetá
V, OS 15176, 19 fotos). A "Dúvida sobre esta ronda" da rodada 3 saiu na rodada 4 ("deixará de existir pelo motivo do
ponto 2.6"): a ronda se contesta pelo "!" da linha do dia, abaixo.

- **O que o cliente vê** ("Checklist + fotos, sem nome"): os itens do checklist com a resposta, sujidade e vegetação
  com o nível, a frase da régua e o tipo marcado ("Poeira / areia"), Pragas/dejeto/sombreamento e Ocorrências pela
  foto do App ("Pragas — pontual"; o livro não traz os achados), as fotos de cada item, o nº da OS e o horário
  (Brasília). **Nunca**: técnico, observação escrita, falhas internas ("ronda longa pendente"), a nota da ronda (vai na
  descrição da capa — por isso a capa vira "Capa da ronda"), GPS. Foto que não casa com item do checklist
  vira "Foto da ronda" (a descrição pode ser texto do técnico: "Zona valetas critica").
- **Montagem** (`rondas_cliente.py`, puro): `do_mes` lista as rondas com OS da usina no mês (dia em Brasília; a mesma
  ronda em mais de uma OS fica numa só). `detalhe` casa cada foto ao item pelo começo da descrição ("Sujidade dos
  módulos — 2"); duas miniaturas por linha e o resto atrás do "+N" (OS 15910 da Altair: 39 fotos). OS sem anexo no
  Fracttal existe (15654, GV 07/10): a janela diz "Esta ronda não tem fotos anexadas". `da_os` é a TRAVA: só OS de
  ronda de usina do de-para do 5080 e de 10/2026 em diante — sem ela, qualquer nº de OS do Fracttal (de qualquer
  cliente) viraria foto na tela pública.
- **Fotos** (`fotos_ronda.py`): o caminho do Nexus (`nexus/campo/ronda_fotos.py`): lista dos anexos pela API REST
  (`work_orders_attachments?folio=`, 1 pedido por OS, guardado 20 min), arquivo pelo link assinado do S3 (não conta na
  cota), miniatura 240 px pelo Pillow (sem Pillow, a inteira). O link nunca sai para o navegador. Cota do Fracttal
  (200/min por EMPRESA) recusada → `Ocupado` na hora, a janela mostra a ronda e "tente de novo em 1 minuto".
- **Rotas**: `GET /api/t/rondas?usina=&ano=&mes=` (lista, sem Fracttal) · `GET /api/t/ronda/<os>` (detalhe +
  `fotos_erro`) · `GET /api/t/ronda/<os>/foto/<i>[?mini=1]`. OS fora da trava = 404.
- **Tela**: ícone (`#opFotos`) no canto do card; janela `#rdFundo` (datas das rondas no topo, pontos de atenção que
  levam à linha, seções, "Outras fotos" recolhidas, foto ampliada em `#rdLuz`, Esc fecha). Ícone e janela fora do
  Baixar PDF (`body.printing`), do Ctrl+P e do PDF Carteira (`#printArea`).

### Contestação do cliente (rodada 4, 09/10/2026)

**Para que serve.** Levi, 09/10: "ao passar o mouse em cima da linha do dia aparecerá uma exclamação no lado extremo
direito da tabela; clicando, o cliente poderá contestar um ou mais números — disponibilidade, desligamento, string,
tracker ou ronda. Ronda notificará o time de zeladoria do Teams."

- **Janela** (`#ctFundo`): usina e dia, o que o cliente viu naquele dia — geração e irradiação (do gráfico),
  Disp, tracker, string, comentário (o do analista ou o registro da OS) e ronda —, as caixas Geração ·
  Disponibilidade · Desligamento · String · Tracker · Ronda (item sem destino fica desabilitado), "O que está
  diferente?" (opcional), nome e e-mail ou telefone (obrigatórios). Até a rodada 4 abria pelo "!" da linha da tabela.
- **Canais** (`contestacao.py`, `ITENS`): ronda → O&M › **Zeladoria**; disponibilidade e desligamento → **COS** (Levi,
  15/10/2026: "Disponibilidade e desligamento vão para o setor de COS"; `THOPEN_TEAMS_COS`); geração (rodada 5:
  "adiciona geração na contestação, será direcionado a performance"), string e tracker → O&M › **Performance**. **O destino é o Nexus** (Levi, 19/10/2026: "vai direto para contestações do Nexus e a
  gente resolve lá, esquece teams" — sem o fluxo do Teams do COS, Disponibilidade e Desligamento nem marcavam): uma
  linha por setor no banco, que o Nexus mostra na aba do setor; o Teams, onde o setor tem fluxo (Performance e
  Zeladoria), recebe também uma mensagem com só os itens dele. Os setores daqui são os das abas do Nexus: o teste cruzado de lá confere.
  Teams por fluxo do app Workflows ("Enviar alertas de webhook para um canal"), cartão Adaptive Card com usina, dia,
  o que contesta, o que estava na tela (`TELA`: geração, irradiação, Disp, tracker, string, comentário, ronda), a
  mensagem, nome e contato. E-mail não serve (envio barrado no tenant).
  Resposta ao cliente é por fora, pelo contato informado.
- **No banco, para o Nexus** (rodada 5, item 4, Levi 13/10: "contestação ligada ao Nexus"; "ficaria na API do PG, pode
  aplicar e construir!"): `contestacao_banco.py` grava o livro `thopen_contestacoes · contestacoes`, 1 linha por
  contestação × setor (com `avisado_teams`: "sim", "não" = o Teams recusou, "sem canal" = o setor não tem fluxo), que o Nexus mostra em Contratos e clientes → Contestações. Nome,
  contato, mensagem e o que estava na tela vão só em `dados_cifrados`, com cifra ASSIMÉTRICA (X25519 + HKDF + AES-GCM,
  prefixo `cx1:`, presa à linha): o 5080 tem só a chave PÚBLICA (`THOPEN_CONTESTACAO_CHAVE_PUBLICA`) e não abre nada; o
  Nexus abre com a privada. O livro é trocado inteiro (sync-xlsx com replace) sob trava, relido antes — leitura que não
  bate com a contagem da API NÃO regrava (apagaria contestações) — e conferido depois. **Na hora** desde 19/10/2026
  (`registrar_contestacao`; até então em segundo plano, quando o Teams era o registro): o cliente só lê "enviada"
  depois de o livro conferir. Sem a chave pública ou sem o GRIDCO_SQL_TOKEN (`configurado()` falso), não grava. O par de
  chaves de 13/10 está em `C:\GridcoAuto\entrega-ti\contestacoes-chaves-2026-10-13\` (a pública vai no `.env` do clone do
  cliente; a privada, no do Nexus). Contrato com o Nexus: `LIVRO`, `ABA`, `CAB`, `PREFIXO` e a receita da cifra iguais
  aos de `nexus/contratos/contestacoes.py` — o teste cruzado de lá (`PLATAFORMA_REPO`) cifra com este código.
- **Rota** `POST /api/t/contestar` (`usina, ano, mes, dia_ini, dia_fim, itens, mensagem, nome, contato, site,
  tela{}`): só de 10/2026 em diante, dia dentro do mês, usina do painel (o 5080 é público) → 400/404. Setor sem banco e
  sem fluxo do Teams → 503 (nunca "enviada" sem ter registrado). Proteções: 3 por endereço por hora (CF-Connecting-IP — atrás
  do túnel o remote_addr é sempre 127.0.0.1), 40 por dia no total → 429; campo-isca `site` (robô recebe "ok" e
  ninguém é avisado); mensagem até 1.000 caracteres, cada campo de `tela` até 400; e-mail ou telefone com DDD. Vale
  quando cada setor ficou no banco ou no Teams: Teams recusado com o banco gravado é "enviada"; banco fora, só os setores
  que o Teams recebeu, e 502 dizendo para onde foi e para onde não foi.
- Provado em 09/10 com dado real (Guaratinguetá V, 02/10, Disponibilidade + Ronda) num Teams falso: uma mensagem no
  caminho do Performance e uma no da Zeladoria, cada uma com o seu item. Rodada 5 (13/10, dado ao vivo): clique na
  barra do dia 06/10 da Guaratinguetá V, Geração + Ronda → Performance com "Geração" e Zeladoria com "Ronda", as duas
  com a geração (4.429 kWh) e a irradiação (2,03 kWh/m²) do dia.

### Trip das OS (23/10/2026)

Levi, 23/10/2026: "Nos comentários quero que inclua a informação do trip (...) Desligamento Usina Trip X de 13/10 às
17:02h a 14/10 às 07:29h; religamento, OS 16249 / VOCÊ BUSCARÁ PRIMEIROS NAS SUBTAREFAS Categoria e proteção, CASO NÃO
TENHA VAI PROCURAR NA NOTA DA OS. GOSTARIA QUE O BOTÃO ATUALIZAR PUXASSE DIRETAMENTE". Código: `trip_os.py`.

- **De onde.** O COS do Nexus abre a OS com a subtarefa "Categoria e proteção" ("Proteção atuou — 27 e 86") e a nota
  "UFV: ... | Proteção: 27/86 | Ação: ... | Falha: ..." (`cos_spec.observacao`). Primeiro a subtarefa
  (`work_orders_subtasks/?folio=`); sem código nela, o campo Proteção da nota (`work_orders/?folio=`, `task_note`). Só os
  códigos da lista do COS (27, 32, 46, 47, 50, 51, 59, 67, 78, 81, 86 e os N), como palavra inteira: o "ALT100" do ativo e
  o "51" da Falha não são trip. "Sem proteção/trip ativo" na subtarefa decide (sem trip, a nota nem é lida); "--/--" na
  nota = sem trip. Caso real: a OS 16249 tem "Religamento " na subtarefa e o 27/86 só na nota; a 15991 não tem subtarefa
  e a nota diz 59/86.
- **Quando.** A rota `/api/t/operacao` nunca espera o Fracttal: usa o guardado e põe o que falta numa linha só em
  segundo plano (`thopen-trip`, meio segundo entre pedidos: a cota é de 200/min para a EMPRESA). O guardado vale 6 h, em
  memória e em disco, com o "sem trip" também. O **Atualizar** manda `?usina=&ano=&mes=` ao `/api/t/reload`, que busca
  de novo, direto, as OS da usina na tela (até 25 s; o resto segue em segundo plano). **429**: para tudo por 2 min e o
  comentário sai sem o trip, nunca com erro; sem credencial, igual.
- **Medido em 23/10/2026** (cópia de prova, Fracttal real): Altair de outubro, "Desligamento Cabine 2 Trip 59/86 de
  09/10 às 16:29h a 13/10 às 18:21h; religamento, OS 15991" e "Desligamento Usina Trip 27/86 de 13/10 às 17:02h a 14/10
  às 07:29h; religamento, OS 16249" (2 OS, 4 pedidos).

### Como provar

- Testes (a partir da raiz): `python -m pytest -q tests/test_thopen_operacao_mes.py tests/test_thopen_fonte_operacao.py
  tests/test_thopen_operacao_rota.py tests/test_thopen_operacao_tela.py` (contas e erros previstos, leitura sem rede,
  rota e lista branca, tela e impressão), da rodada 3 `tests/test_thopen_rondas_cliente.py
  tests/test_thopen_fotos_ronda.py tests/test_thopen_rondas_rota.py`, da rodada 4 `tests/test_thopen_contestacao.py`
  (Fracttal e Teams falsos), da rodada 5 `tests/test_thopen_contestacao_banco.py` (a contestação cifrada no banco), do
  login `tests/test_thopen_acessos.py tests/test_thopen_login_rota.py`, do trip `tests/test_thopen_trip_os.py` (Fracttal
  falso), dos Registros `tests/test_thopen_registros.py` e, do lado da plataforma,
  `tests/test_falhas_operacao_cliente.py` e `tests/test_falhas_publicar.py`. Os testes cruzados moram no Nexus
  (`tests/test_contratos_contestacoes.py` e `tests/test_contratos_acessos_clientes.py`, com `PLATAFORMA_REPO=<este clone>`):
  conferem a cifra, os livros, as carteiras e os setores dos dois lados. Os do
  `thopen/` rodam em segundos com `--noconftest` (o `conftest.py` da raiz importa o `app.py` da plataforma: ~2 min).
  Depois, a suíte inteira.
- Porta de teste (nunca a 5080): `python -c "import sys; sys.path.insert(0, r'<repo>\thopen'); import dashboard_thopen
  as d; d.app.run(host='127.0.0.1', port=5081, threaded=True)"`. Rotas antigas: `_snap_dash.py` na 5080 e na 5081 +
  `_diff_snap.py` = 0 diferença. Rota nova: `/api/t/operacao?usina=Altair&ano=2026&mes=10` — antes do deploy da
  plataforma tem de dizer "aguardando a plataforma publicar o plant_id" (é a barreira funcionando).
- Para ver números antes de a plataforma publicar: um script que importa o módulo, põe `fonte_operacao._estado` com
  `dados` montados do pacote local e `ts = time.time()` (com `ts` 0 a recarga em segundo plano troca pelo dado real) e
  sobe o app na 5081.
- Tela: o Diário de 10/2026 (Altair, Guaratinguetá V) no navegador e no PDF (Edge `--print-to-pdf`, Ctrl+P e PDF
  Carteira); o de 09/2026 igual ao de antes — em 09/10 a folha de setembro foi comparada pixel a pixel com a do HEAD
  (o `thopen/` do HEAD por `git archive` numa porta ao lado, mesmo cache do BD): diferença nenhuma.
- Disponibilidade: a média do mês de cada usina contra o `frac_disp_index.json` do Gerencial (mesmo mês).
- No cliente, depois do pull: `/api/t/fonte`, `/api/t/operacao` de Altair e Guaratinguetá V e um print do Diário.
