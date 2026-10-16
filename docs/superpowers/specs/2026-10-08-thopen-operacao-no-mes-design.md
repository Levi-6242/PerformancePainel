# Dashboard Thopen (5080): "Operação no Mês" — strings, trackers e zeladoria por usina

Spec de 08/10/2026. Pedido do Levi: no Dashboard Thopen, por usina e mês, **quantas strings tiveram saída**, **quantos
trackers distintos pararam** e o **nível de zeladoria** (BD das Rondas do Nexus). "Tem que garantir a confiabilidade e
prever possíveis erros." Mockup aprovado em 08/10 (card na aba Diário, zeladoria centralizada com a legenda da régua).

## Decisões do Levi (08/10)

| Tema | Decisão |
|---|---|
| Onde calcular | O **5080 lê o workbook bruto** `falhas_performance`; a plataforma só acrescenta colunas no fim das abas |
| Tracker parado sem comunicação | "Quando fica parado sem comunicação essa ocorrência é ignorada; se a usina comunicou inversor ou string, então conta" |
| Fonte da zeladoria | Os workbooks da API que têm ronda, usina e nível (`campo_nexus · rondas` e `nexus_rondas_checklist · fato_checklist_ronda`) |
| Onde aparece | Aba **Diário**, ao lado de "Energia × Irradiação" (coluna da direita, abaixo de Disponibilidade) |
| Desde quando | **Só a partir de 10/2026.** Antes disso o card não aparece e o Diário fica como hoje |
| Régua da zeladoria | 5 níveis com a frase de cada um (cartão "A régua: cinco níveis"), cor por nível |

## Revisão de 08/10, à tarde (feedback da Ana + decisões do Levi) — VALE SOBRE O RESTO DESTE SPEC

Ana: "acho que eles esperam algo sobre dias também" (ex.: `Guaratinguetá V | 01/10 | Desligamento UG XX, proteção YY
(4h) | 4 strings | 3 trackers`) e "ter a especificação de metodologia e fórmulas". Levi decidiu:

| Tema | Decisão |
|---|---|
| Strings (card E tabela) | **Vêm das OS do Fracttal** de recomposição de string ("Strings é OS"), não da régua de 2 h da plataforma |
| Quantidade de strings da OS | Hoje o texto da OS nem sempre traz. O Levi vai adaptar o OS Creator (em outro chat) para escrever a quantidade nas observações. **Outubro: completar do nosso lado, sem tocar no Fracttal** — strings citadas no texto; sem citação, as strings que a plataforma viu sem corrente naquele inversor no dia do evento, marcadas "estimado" |
| Dia da string | **A data do evento da OS** no Fracttal (`event_date`) |
| Trackers | "Ocorrências mesmo, de acordo com a plataforma" (o registro de trackers parados, com a usina comunicando) |
| Tabela do Diário | **Uma linha por ocorrência** (de 10/2026 em diante): cada dia com OS de string (data do evento) ou ocorrência de tracker vira linha — Usina \| Data \| Comentário do dia (se houver) \| Strings \| Trackers. Antes de 10/2026, a tabela de comentários fica como hoje |
| Metodologia | Aba nova "Metodologia" com as fórmulas (mockup v3 aprovado); **fora do PDF**. A regra da disponibilidade diária fica "a confirmar" até a Ana/Levi validarem o texto |
| Commit | **Nada é commitado** até o Levi terminar de testar e validar |

Contrato do texto que o OS Creator vai escrever nas observações (o leitor da plataforma casa por esta linha):
`Strings sem corrente: N (Ipv3, Ipv7, Ipv11, Ipv12)` — o número é a quantidade; a lista entre parênteses, quando houver,
dá as strings (lida pelo `_falhas_os_citadas`, o mesmo leitor das OS abertas). Sem a lista, vale a quantidade.

Consequência no desenho: a plataforma passa a publicar, no `falhas_performance`, as OS de string do mês (data do evento,
usina, inversor, strings, quantidade, origem `texto`/`quantidade`/`estimado`) e as ocorrências de tracker por dia (usina,
dia, trackers com a usina comunicando). O 5080 conta o card e monta a tabela a partir dessas duas abas. O que já foi
implementado (plant_id, dias_comunicou, cobertura, leitura com cache, card, rota) continua valendo.

## O que o card mostra (por usina × mês, mês ≥ 10/2026)

- **Strings com saída**: strings DISTINTAS — chave `(fonte, plant_id, inversor normalizado, string)` — com pelo menos um
  episódio no mês na aba `strings_episodios`. É a régua da aba Falhas (2 h seguidas sem corrente, 06–18 h, inversor
  gerando), que já tira entrada vazia, sombra em rampa, string trancada e ocorrência desconsiderada.
- **Trackers parados**: trackers DISTINTOS — chave `(fonte, plant_id, tracker)` — com pelo menos um episódio no mês em que
  `dias_comunicou > 0` (coluna nova). O tracker-dia sem comunicação do próprio tracker já fica fora na régua da plataforma.
- **Zeladoria**: a ÚLTIMA ronda do mês com leitura (a mesma régua do Relatório Semanal e do Nexus): sujidade dos módulos
  e altura da vegetação, de 1 (limpo) a 5 (crítico), com a frase do nível e a data da ronda.
- **Estados, nunca um zero falso:** número medido; "—" quando a usina não tem monitoramento daquela coisa no mês
  (sem linha na aba `cobertura`); "sem leitura no mês" na zeladoria; o card some antes de 10/2026.
- **Mês corrente** leva "Mês em andamento, até dd/mm" (do `periodo_fim` da aba `atualizacao`).

## Parte 1 — plataforma (servidor publica; nada existente muda)

`plataforma/falhas_job.py` (montagem do mês) e `plataforma/falhas_publicar.py` (workbook):

1. **`plant_id` no fim** de `strings_episodios` e `trackers_episodios` (o pacote já tem o campo; a `strings_inversor_dia`
   agrega por usina × inversor × dia, não tem plant_id e fica como está — o 5080 conta pelos episódios).
2. **`dias_comunicou` no fim** de `trackers_episodios`: quantos dias do episódio (dentro do mês) a USINA comunicou.
   "Comunicou no dia" = existe no registro da régua de strings (`falhas_strings.json`, qualquer fonte e plant_id) uma
   entrada da MESMA usina (nome canônico) nesse dia com leitura de produção (`vivas` ou `mortas` — a mesma régua que o
   `montar` já usa para "a usina apareceu"; o registro de madrugada sem nada gerando não conta), **ou** a geração do dia
   da usina é > 0. Conferido
   no dado do PC: 104 dos 112 plant_id de tracker de outubro têm registro de strings; a Brodowski 297381 (metade 1.x) não
   tem, mas a 297378 (mesma usina) tem todos os dias — por isso a regra é por usina, não por plant_id. A geração sozinha
   não serve: ela é D-1 (o dia corrente sai sempre "sem geração").
3. **Aba nova `cobertura`**: 1 linha = mês × fonte × plant_id (`mes, fonte, cliente, usina, plant_id, dias_strings,
   dias_trackers, dias_comunicou`). É o que separa "0" de "sem monitoramento".
4. **`atualizacao`** ganha `cobertura` (contagem) no fim.
5. A marca SHA1 do workbook muda uma vez (sobe de novo na volta seguinte). Colunas só no FIM: quem lê por posição
   (BI, Nexus) não quebra.
6. **Governança (Nexus, regra 10):** registrar a aba `cobertura` e as colunas novas no `nexus/dados/catalogo.py`
   (fatos `falha_string` e `falha_tracker`).

## Parte 2 — 5080 (`thopen/`)

1. **`thopen/operacao.py`** (puro, sem rede): régua da zeladoria (`ler_respostas`, `REGUA` com as 10 frases, dedupe da
   ronda repetida em 2–3 OS por `usina_id + dia + hora_inicio + hora_fim`, última do mês), contagem distinta de strings e
   trackers, de-para de nomes falhas → 5080, estados.
2. **`thopen/fonte_operacao.py`**: lê pela mesma API (`fonte_api._get`) as abas `falhas_performance · strings_episodios,
   trackers_episodios, cobertura, atualizacao`, `campo_nexus · rondas`, `nexus_rondas_checklist · fato_checklist_ronda`
   e `cadastro_nexus · de_para` (ids das abas resolvidos pelo nome, a cada carga). **Cache próprio** (memória + gzip em
   disco, TTL 600 s) **recarregado em segundo plano** — nunca dentro do `_lock` do `_wb()` nem do `/api/t/reload`, e a
   requisição do cliente nunca espera a rede (hoje a recarga do BD_Thopen já segura o 1º acesso por ~130 s). Lista
   branca: das rondas só saem `usina_id`, dia, hora, sujidade e vegetação.
3. **Conferência da leitura:** a soma das linhas de cada mês tem de bater com a aba `atualizacao` (o sync troca linhas
   no lugar). Não bateu → nova tentativa; falhou de novo → fica a última leitura boa. Nunca deduplicar linha do workbook
   (duas linhas iguais podem ser dois trackers de plant_id diferentes — Assis, out/2026).
4. **Rota `GET /api/t/operacao?usina=&ano=&mes=`**: valida ano/mês (400 se inválido), devolve só agregados
   `{disponivel, motivo, strings, trackers, zeladoria{data, sujidade{nivel, frase}, vegetacao{nivel, frase}}, regua,
   parcial_ate, atualizado_em}`. As frases da régua moram SÓ no Python (`operacao.REGUA`); a tela não as repete.
   `mes < 2026-10` → `disponivel: false, motivo: "antes de 10/2026"`. Chave `THOPEN_OPERACAO=0` desliga.
5. **Tela (`dashboard_thopen.html`)**: o card do mockup aprovado, abaixo de "Disponibilidade Usina", com
   `Plotly.Plots.resize` do gráfico diário depois de mostrar/esconder. Entra no PDF da usina e no PDF Carteira (o render
   do Diário espera a resposta antes de fotografar).
6. **De-para de nomes** (falhas → 5080): igualdade normalizada + aliases explícitos (`Primavera 1/2 → Primavera`,
   `Nova Londrina 1/2 → Nova Londrina`, `Marajoara I → Marajoara 1`, `Piracicaba I → Piracicaba 1`,
   `Santo Antonio do Platina → Santo Antonio da Platina`, `Corrego do Sapucaia → Córrego do Sapucaia`). Só cliente
   `Thopen` (a `Ipixuna do Pará` da 2C nunca entra). Ouro Branco (um nome nas falhas, I a V no 5080) fica sem número até
   haver de-para por plant_id. Zeladoria pelo `cadastro_nexus · de_para` (sistema "BD_Thopen · Dados Gerais Usinas"),
   N:N: usina do 5080 com 2 ids soma os dois; id comum a 2 usinas vale para as duas.
7. **Não muda nada que existe:** nenhuma rota, assinatura ou formato atual (a plataforma importa 7 atributos do
   `dashboard_thopen`); nada roda no import (sem thread, sem rede).

## Erros previstos e como cada um fica barrado

| Erro | Barreira |
|---|---|
| Trackers pela metade (Brodowski 51 × 103) | chave com `plant_id` (coluna nova) + teste com as duas metades |
| Fantasmas Ipv29–32 (5 usinas em out) | correção da sessão paralela no `falhas_job`; **não libera ao cliente antes**; teste com a Fazenda Limão |
| Zero que é "sem dado" | aba `cobertura` → "—"; teste com usina sem cobertura |
| Parada durante falha de comunicação | `dias_comunicou`; teste com usina sem registro e sem geração |
| Ronda repetida em 3 OS | dedupe por usina+dia+horário; teste |
| Hora do `campo_nexus` em UTC | ordenação do dia pela hora convertida; teste com ronda às 21:30 de Brasília |
| Nome que não casa (5 usinas) | aliases + teste que falha se usina Thopen com dado não ligar |
| Mistura de cliente (Ipixuna 2C) | filtro `cliente == Thopen` + teste |
| Dado pessoal ao cliente (técnico, texto livre) | lista branca na leitura + teste das chaves da resposta |
| Leitura no meio do sync | conferência com `atualizacao` + última leitura boa |
| Cliente esperando a rede | recarga em segundo plano + cache em disco |
| Quebra do 5080 atual / da plataforma | foto das ~1.300 respostas antes × depois (0 diferença) + suíte inteira + import sem rede |
| Zeladoria velha lida como atual | data da ronda sempre visível; "sem leitura no mês" |

## Fora do escopo (avisado ao Levi)

- Publicar o nível de zeladoria como rotina (as duas fontes pararam em 02/10 e 06/10; pendência 2 do Nexus).
- A recarga de ~130 s do BD_Thopen no 1º acesso do cliente (mudança à parte, se ele quiser).
- Disponibilidade 0,00% da Altair em outubro (dado do BD_Thopen).
- O link trycloudflare do cliente, que troca de endereço.

## Como provar

- Plataforma: `python -m pytest -q` (inteira) + testes novos do `falhas_publicar`/`falhas_job`; montar outubro com os
  dados do PC e conferir `dias_comunicou` e `cobertura` em Brodowski, Altair e Guaratinguetá V.
- 5080: testes puros + rota; porta de teste (5081) com o código novo e as ~1.300 respostas atuais iguais antes e depois;
  o card conferido no navegador e no PDF (A4) com Altair e Guaratinguetá V.
- Para o cliente: só depois do push (servidor publica as colunas), da correção das Ipv29–32 e do "ok" do Levi; pull no
  clone `C:\GridcoAuto\PerformancePainel` e restart só do `servir_thopen.py`, sem tocar no túnel.

## Rodada 3 (09/10/2026) — texto por dia, título da Zeladoria, fotos das rondas e dúvida do cliente — VALE SOBRE O RESTO

Pedido do Levi (09/10): "1 - Transforme esses números em texto: dia 02: 46 trackers parados. X strings sem corrente.
2 - o nome ZELADORIA tem que ter o mesmo tamanho e fonte, pois é um título. 2b - um ícone de imagem no campo superior
direito carregando a imagem das rondas em uma estrutura parecida com" o detalhe de ronda do painel do App. "3 - um campo
onde o cliente possa tirar dúvidas e tem que chegar uma notificação para a gente de alguma maneira". Mockup aprovado em
09/10 ("boa! segue"; scratchpad `m4/`, dado real da Guaratinguetá V, OS 15176 com 19 fotos).

| Tema | Decisão (Levi, 09/10) |
|---|---|
| Tabela do Diário | Sem as colunas Strings/Trackers: o Comentário traz a frase "46 trackers parados. 1 string sem corrente." e, embaixo, o comentário do analista. Sem o prefixo "Dia 02:" (a Data está ao lado). "—" (sem medição) não vira frase |
| Zeladoria | Título com a letra do "Operação no Mês" (`.card h3`); "ronda de dd/mm" numa linha menor embaixo |
| O que o cliente vê da ronda | "Checklist + fotos, sem nome": itens do checklist com a resposta, níveis com a frase da régua e o tipo de sujidade, achados (praga, dejeto, sombreamento, trincado — pela foto) e todas as fotos (2 por linha, o resto no "+N"), mais o número da OS e o horário. NUNCA: técnico, observação escrita, falhas internas, nota da ronda, GPS. Foto que não casa com item do checklist sai como "Foto da ronda" (a descrição pode ser texto livre do técnico) |
| Fotos | Anexos da OS de ronda no Fracttal (o mesmo caminho do Nexus, `nexus/campo/ronda_fotos.py`): 1 pedido à API por OS aberta, guardado 20 min; o arquivo vem do S3 pelo link assinado, que nunca sai para o navegador. Credencial `FRACTTAL_CLIENT_ID/SECRET` |
| Aviso da dúvida | Teams, por um fluxo do app Workflows ("Postar em um canal quando uma solicitação de webhook for recebida"); URL em `THOPEN_DUVIDA_TEAMS`. Sem URL o formulário não aparece. E-mail não serve (envio barrado no tenant) |
| Resposta ao cliente | Por fora: o formulário pede nome e e-mail ou telefone. Nada é guardado no 5080 — o registro é a mensagem no canal |

**Proteções (o 5080 é público, sem senha).** Foto e dúvida só de OS de ronda de usina ligada no de-para do 5080 e de
10/2026 em diante (sem isso, qualquer número de OS do Fracttal, de qualquer cliente, virava foto na tela). Dúvida: 3 por
endereço por hora, 40 por dia no total, campo-isca, até 1.000 caracteres, contato validado. Ícone e janela fora do PDF
(Baixar PDF, Ctrl+P e PDF Carteira). `THOPEN_RONDAS=0` desliga janela, fotos e dúvida.

**Dado que a janela usa — fonte dinâmica (Levi, 09/10: "as rondas já foram atualizadas até hoje porém no server não
está atualizando, tem que ser dinâmico").** O livro do App `rondas_app_campo · OS de ronda`, que o servidor do App
regrava de hora em hora e que desde a v249 (09/10) traz o checklist. Substitui o `campo_nexus · rondas` (coletor do
Nexus parado em 02/10) e a carga única das rondas sem OS (06/10): tem as 125 sem OS e 580 das 584 rondas do
`campo_nexus`. Só as colunas OS, usina, ativo, início, fim, os dois níveis e o checklist são lidas; o técnico (nome e
HMAC), a nota e as falhas internas nunca. O `usina_id` sai do de-para do Nexus (código do ativo ou nome no Fracttal);
os achados (praga, dejeto, sombreamento, trincado), da descrição das fotos. Em 09/10: 113 rondas de usinas do 5080 em
outubro, até o próprio dia. O cache em disco ganha versão: o de antes não sobe.

## Rodada 4 (09/10/2026) — tabela com Disp, contestação por dia, layout — VALE SOBRE O RESTO

Pedido do Levi (09/10, com o gráfico anual sem a Produzida 2025) e respostas: "1 - Sim, a partir de outubro somente
viu. Antes disso é modelo anterior" e "2 - Sim. Mas a disponibilidade está em decimal, poderia botar um % no final do
valor; fora isso segue!".

- **Produzida 2025 sumida**: nome da usina diferente na aba Historico (Nova Londrina × "Nova Londrina 1" e mais 6).
  Corrigido à parte e já no ar (`fb322ce`, `_HIST_NOME`); a rodada precisa da `main` mesclada antes do push.
- **Tabela do Diário (10/2026 em diante)**: Usina | Data | Comentário | Disp (%) | Tracker (Parado) | String (Sem
  corrente), Usina e Data centralizadas; o Comentário só com desligamentos e falhas de comunicação (o do analista) e,
  no dia com ronda, "Ronda realizada: vegetação nível X e sujidade nível Y"; só os dias com alguma coisa; Disp com 1
  casa e "%". A frase dos números (rodada 3) saiu.
- **Disponibilidade** pela régua do Gerencial (OS do Fracttal): a plataforma publica `falhas_performance ·
  disponibilidade_dia` do `frac_disp_index.json`; o 5080 calcula pelas horas perdidas e liga pelo nome antes do
  Fracttal (um site pode ser de duas usinas). O card "Disponibilidade Usina" usa a do Gerencial de 10/2026 em diante;
  antes, o modelo anterior. Conferido: 80 usinas iguais ao Gerencial, menos uma por 0,01 (Araçoiaba da Serra 1).
- **Contestação**: "!" na ponta da linha ao passar o mouse; o cliente marca disponibilidade, desligamento, string,
  tracker e/ou ronda; ronda vai ao canal O&M › Zeladoria, o resto ao O&M › Performance (fluxos do Workflows). A
  "Dúvida sobre esta ronda" da rodada 3 saiu.
- **Layout**: com o card, a Produção Anual abaixo da Disponibilidade (ao lado do gráfico diário) e o card ao lado da
  tabela. Sem o card (antes de 10/2026), o Diário de antes — com o anual em cima também em setembro a folha saiu com a
  tabela partida e o gráfico cortado. Na folha com o card, barras do anual mais finas: Altair e Guaratinguetá V de
  outubro cabem numa folha (Ctrl+P e PDF Carteira); setembro idêntico ao HEAD, pixel a pixel.
