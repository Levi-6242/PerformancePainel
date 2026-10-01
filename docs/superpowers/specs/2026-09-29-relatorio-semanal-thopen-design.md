# Relatório Semanal de Performance — Thopen (desenho)

> 29/09/2026. Parte do mockup `Mockup_Relatorio_Semanal_Thopen_R00.pdf` e da reunião interna de 28/09/2026 (Levi Maia
> e Ana Patrícia Barros). Desenho aprovado pelo Levi em 29/09. Entrega à Ana prevista para 30/09.

## 1. O que é

É um relatório de performance da carteira Thopen, **para o cliente**, sem jargão interno. Ele sai toda segunda-feira
até as 12h, por e-mail, independentemente da reunião. O analista escolhe o período (De, Até); o padrão é a semana
anterior, de segunda a domingo. Entra no relatório tudo o que cruza o período. O analista revisa, escreve os
direcionamentos na própria página e salva o PDF pelo navegador.

É um tipo novo do Criador de Relatório (`docs/criador-de-relatorio.md`), com página e motor próprios. O Criador de
hoje (uma usina, meta do 1º ano) não muda.

## 2. Escopo

- **Usinas:** as Full O&M da Thopen que o Fracttal acompanha — as do índice de disponibilidade com cliente Thopen (83
  em 29/09/2026). É o "só as O&M" da reunião.
- **Período:** `ini` e `fim` inclusivos, em datas de Brasília. Uma semana que atravessa dois meses funciona.
- **Nesta fase:** os blocos 01 a 05. O bloco 06 (pendências que dependem da Thopen) fica para depois, como a Ana
  pediu: ainda não se sabe como a supervisão vai cadastrar.

## 3. Fontes

Nenhuma consulta nova ao Fracttal nem a API de supervisório na hora de gerar. Tudo já está em disco, preparado pelo
worker ou lido do BD.

| Dado | Fonte | Leitor na plataforma |
|---|---|---|
| Geração e IPOA diários | BD_Thopen, aba de cada usina | `dashboard_thopen._daily_records` |
| Potência (MWp) | BD_Thopen `T_Usinas` e, na falta, Info Geral | `_g_th_pot` |
| Meta mensal de geração, irradiação e PR | BD_Thopen `Historico` (lista de metas da Thopen), a mesma do Dashboard 5080 | `dashboard_thopen._meta2026` |
| Disponibilidade e desligamentos | índice do worker `frac_disp_index.json` (mês corrente e anterior) | `_frac_disp_dados` |
| OS por tipo e status | linhas do worker `frac_mtta_linhas.json` | leitura do arquivo |
| Strings e trackers | pacote da aba de falhas `falhas_AAAA-MM.json` | `_falhas_ler(_falhas_arquivo(mes))` |
| Direcionamentos, leitura, responsável, versões | `relatorio_semanal.json` (novo) | módulo novo |

## 4. As contas

Todas em módulo puro (`plataforma/relatorio_semanal.py`), sem rede e sem arquivo.

### 01 Resumo da semana

- **PR real da usina** = Σ geração ÷ Σ (IPOA × potência), só nos dias com geração e IPOA > 0,3 kWh/m². É a régua do
  Histórico PR (`api_g_diario`); o semanal de uma usina tem de bater com ele.
- **Meta de PR da usina** = a meta mensal do cliente, ponderada pelo denominador do dia:
  Σ (meta do mês × IPOA × potência) ÷ Σ (IPOA × potência). Uma semana entre dois meses pesa cada meta pelo que o dia
  pesou.
- **PR e meta do portfólio:** as mesmas somas, em todas as usinas.
- **Fora da meta:** PR real < 97% da meta de PR ("tolerância: PR ≥ 97% da meta").
- **Geração real × meta** = Σ geração ÷ Σ meta diária (meta mensal ÷ dias do mês, nos dias do período).
- **IPOA real × meta** = Σ IPOA ÷ Σ meta diária de irradiação.
- **Disponibilidade** (ver bloco 04) contra a meta de 97%.
- **Leitura da semana:** 2 a 3 linhas escritas pelo responsável.

### 02 Evolução desde a assunção

PR mensal do portfólio (mesma conta, mês a mês) contra a meta ponderada, de **jan/2026** (provisório, até a Ana
confirmar a data real) ao mês corrente. Mostra o PR do primeiro mês, o do mês corrente e o ganho em pontos.

### 03 O que a Grid executou

OS dos sites Thopen Full O&M com **data do evento no período**, pelo status atual (2 e 3 = concluída; 0, 1, 5 e 6 =
aberta; 4 = cancelada, fora):

- **Corretivas:** tipo Corretiva ou Corretiva Emergencial — concluídas de abertas no período.
- **Preventivas realizadas × planejadas:** tipo Preventiva — concluídas de todas as não canceladas no período.
- **Strings que voltaram a gerar:** strings cujo episódio da aba de falhas terminou no período.
- **Tempo médio de religamento após queda:** média de (fim − início) das OS de queda de rede do índice de
  disponibilidade que terminaram no período.
- **Rondas de zeladoria e roçadas/limpezas:** pendentes — o Levi estrutura o mapeamento no Fracttal. As linhas só
  aparecem quando ele existir.

### 04 Disponibilidade e desligamentos

Do diário do índice de disponibilidade (`diario[usina][dia]`: `h_eq`, `h_q`, `h_e`, `disp`):

- **Disponibilidade da usina** = 1 − Σ h_eq ÷ (12 h × dias do período). Dia fora do diário = 100%.
- **Portfólio:** média ponderada pela potência (kWp).
- **Indisponibilidade atribuível à Grid** = as horas de equipamento (`h_e`); **externa** = as de queda de rede
  (`h_q`), ambas ponderadas pela potência. As duas famílias podem se sobrepor no mesmo horário e não somam
  exatamente o total — a regra do módulo `disponibilidade`.
- **Quedas de energia (rede):** OS de origem queda que cruzam o período — quantidade e horas solares dentro dele.
- **Desligamentos por equipamento:** o mesmo para origem equipamento.
- **Usinas com disponibilidade < 97%:** quantas e quais.

### 05 Usinas fora da meta — causa e ação

Uma linha por usina fora da meta, ordenada pela perda estimada.

- **PR real / meta.**
- **Perda estimada (MWh)** = (meta de PR − PR real) × Σ (IPOA × potência). É o que a usina teria gerado a mais na
  meta de PR, com o sol que veio.
- **Ofensores medidos** — o pré-diagnóstico, com número:
  - desligamentos (horas e kWh do índice, OS de queda e de equipamento);
  - trackers parados (episódios da aba de falhas no período);
  - strings sem corrente (episódios da aba de falhas no período);
  - IPOA não confiável: sem IPOA em mais da metade dos dias do período, ou PR de algum dia acima de 130% (IPOA
    subestimada — o alerta do Criador de hoje).
- **Causa sugerida** = o ofensor de maior energia. Sem ofensor medido: "Sem ofensor medido — verificar sujidade,
  vegetação ou limitação".
- **Ação da Grid · status:** sugerida pela OS aberta da usina no Fracttal (folio, tipo, status).
- **Previsão:** texto ou data.
- O analista **confirma ou corrige** causa, ação e previsão na linha. Isso é o "direcionamento" da reunião.

## 5. Direcionamentos e emissão

- **Onde:** na própria página. Cada linha do bloco 05 e a leitura da semana são campos editáveis na tela, que viram
  texto no PDF. Salvam sozinhos (com uma pausa curta depois da digitação).
- **Arquivo:** `relatorio_semanal.json`, estado da plataforma (`_p_dado`), escrito só pelo processo web:

  ```json
  {"2026-09-21|2026-09-27": {
     "leitura": "...", "responsavel": "...",
     "linhas": {"Altair": {"causa": "...", "acao": "...", "previsao": "...", "em": "…", "por": "…"}},
     "emissoes": [{"versao": "R00", "em": "2026-09-28T10:12", "por": "…"}]}}
  ```

- **Emitir PDF** só libera com a leitura da semana, o responsável e todas as linhas do bloco 05 com causa e ação. A
  causa "Sem ofensor medido…" conta como vazia: é o convite para o analista escrever a causa. Sem isso, a página marca
  os campos e diz o que falta. Com tudo preenchido, registra a emissão (R00, R01… por período) com o que foi ao
  cliente — o texto dos campos e os números da página (`resumo`, PR, meta e perda de cada linha) —, preenche o
  cabeçalho e chama a impressão do navegador.
- **Reimprimir:** sem mudança depois da emissão, o botão vira "Imprimir de novo (R0N)" e não gera versão. Qualquer
  edição, ou reabrir a página, volta a "Emitir PDF" (versão nova): os números podem ter mudado.
- **Ctrl+P sem emitir** imprime, mas o papel sai com a faixa "PRÉVIA — emissão não registrada".
- **Página do PDF:** A4 retrato, rodapé "Grid Co. · Relatório Semanal Thopen · período · versão" e "Página N de M". A
  caixa de margem própria tira o cabeçalho e o rodapé do Chrome, que levavam data, título e a URL interna.
- **Contato** ("Dúvidas:") é opcional: vazio, some do PDF. Responsável e contato sem nada salvo no período vêm da
  última vez que alguém os preencheu (`_padrao` no arquivo).
- **Arquivo ilegível** não é regravado (a rota devolve 500 e a tela avisa): gravar por cima apagaria o que os analistas
  escreveram.
- **Cabeçalho:** emitido em (data da emissão), responsável, próximo envio (a segunda-feira seguinte à emissão), versão.

## 5b. Respostas do Levi em 30/09/2026

- **Tempo de religamento** = da criação da OS ao fim da tarefa de religamento (Religamento ou Religamento Remoto), nas
  OS em que essa tarefa terminou no período; com mais de uma, vale a última. A mediana vai ao cliente. OS registrada
  depois do religamento (fim da tarefa antes da criação) fica fora e é contada à parte (`religamentos_retroativos`).
- **Quedas de energia** = do evento ao fim da tarefa — o `ini`/`fim` que o módulo disponibilidade já dá a cada OS
  ("estamos cientes desses atrasos"). Sem mudança.
- **Disponibilidade** = a régua da plataforma (`disponibilidade.py`): Religamento e Religamento Remoto = queda (externa),
  Corretiva Emergencial = equipamento (Grid); início = evento, fim = fim da tarefa; janela 06–18h; escopo pelo ativo da
  OS; sobreposição com teto de 100% da usina; dia que a geração desmente sai (OS longa fechada com atraso).
- **Corretivas e preventivas por tarefa**; finalizada = a tarefa tem data de fim (`mtta.CAMPOS` guarda `final_date`).
  Preventiva "planejada" ainda depende da programação semanal.
- **Assunção** = 01/01/2026 (`ASSUNCAO`); usina que entrou depois entra no mês em que passa a ter dia válido.
- **Aviso geração × disponibilidade** (tela, não PDF): dia sem geração no BD com a usina disponível pelas OS, ou gerando
  com a usina indisponível. Um aviso por usina e tipo.
- **Rondas** (bloco 03): workbook `rondas_app_campo` da Gridco API — total, curtas, longas e usinas no período. Nível de
  sujidade/vegetação e roçadas não estão lá.
- **Bloco 05**: a Ana já contava com ele longo (reunião de 28/09: "como nós temos muitas usinas, esse resumo vai ficar
  muito extenso"); fica com todas as usinas abaixo da tolerância.

## 6. Arquitetura

| Peça | Onde | O que faz |
|---|---|---|
| Contas | `plataforma/relatorio_semanal.py` (novo, puro) | Recebe as séries, o diário de disponibilidade, as OS e os episódios; devolve os blocos. É o que os testes travam. |
| Coleta e rotas | `plataforma/app.py`, bloco do Criador | `GET /relatorio/semanal` (página), `GET /api/relatorio/semanal?ini=&fim=` (monta), `POST /api/relatorio/semanal/direcionamento` (salva um campo), `POST /api/relatorio/semanal/emitir` (valida e registra a versão). Atrás do login. |
| Página | `plataforma/templates/relatorio_semanal.html` (novo) | Layout do mockup em A4 retrato, claro. Cores, fontes e tamanhos tirados do PDF, não no olho. |
| Entrada | página do Criador de Relatório | Link para o semanal. |

Roda no processo web, sob demanda: só lê arquivos que já existem, e o BD_Thopen já fica em memória depois da primeira
carga.

## 7. Confiabilidade

A tela (não o PDF) mostra os avisos:
- usina sem meta ou sem potência, que fica fora das contas;
- dias sem IPOA;
- índice de disponibilidade antigo ou período fora dos dois meses que ele cobre;
- pacote da aba de falhas antigo;
- linhas de OS antigas.

O rodapé do PDF diz só o que é verdade. Nesta fase, o dia sem IPOA sai do PR; a irradiância de satélite no dia de
sensor reprovado fica para depois.

## 8. Testes e conferência

- `tests/test_relatorio_semanal.py`, com o motor em fixtures:
  - PR e meta ponderados, e a semana entre dois meses;
  - fora da meta a 97%;
  - disponibilidade do período a partir do diário;
  - quedas e desligamentos recortados no período;
  - OS por tipo e status;
  - strings que voltaram;
  - perda estimada e causa sugerida.
- Rotas pelo cliente de teste do Flask, com os leitores trocados por stubs. Cobre também a persistência: salvar um
  campo, emissão recusada sem preenchimento e versão sequencial.
- A validação de preenchimento da página rodada no node, no padrão dos testes de tela.
- **Conferência com dado real**, antes de dar por pronto:
  - o PR semanal de três usinas tem de bater com o Histórico PR no mesmo período;
  - a disponibilidade de setembro tem de bater com o painel de Disponibilidade.

## 9. Fora desta fase

- Bloco 06 (pendências da Thopen).
- Rondas de zeladoria e roçadas/limpezas.
- Irradiância de satélite no dia de sensor reprovado.
- Nível de sujidade e vegetação das rondas (workbook das OS de ronda, citado na reunião).
- Emissão automática no worker e envio por e-mail.

## 10. Pendências abertas

- Mês da assunção dos ativos pela Grid: jan/2026 provisório.
- Meta de disponibilidade: 97%, do mockup.
- Mapeamento de rondas e roçadas no Fracttal: Levi, 29/09.
