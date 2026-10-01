# Relatório Semanal Thopen — Plano de implementação

> **Para quem executa:** use superpowers:executing-plans (inline) — o contexto do Fracttal, do BD_Thopen e da aba de
> falhas está nesta sessão. Os passos usam caixas (`- [ ]`).

**Objetivo:** o relatório semanal de performance da carteira Thopen, para o cliente: blocos 01 a 05 do mockup R00, na
ordem da reunião de 28/09, com os direcionamentos preenchidos na própria página e o PDF pelo navegador.

**Arquitetura:** as contas ficam num módulo puro novo, `plataforma/relatorio_semanal.py`, que recebe as séries e os
índices já lidos e devolve os blocos. `app.py` só coleta, com os leitores que já existem, os dados que o worker e o
BD_Thopen já deixam prontos, e expõe as rotas. A página nova, `relatorio_semanal.html`, desenha e edita. Os
direcionamentos ficam em `relatorio_semanal.json`, escrito só pelo processo web.

**Stack:** Python 3.14, Flask, pytest; HTML, CSS e JS sem framework; node para testar a lógica da página.

**Especificação:** `docs/superpowers/specs/2026-09-29-relatorio-semanal-thopen-design.md`

## Restrições globais

- pt-BR em tudo, inclusive nos comentários; sem emoji na interface.
- Comentário explica **por quê**, citando o caso real.
- Nenhuma chamada nova a Fracttal ou a API de supervisório na geração: só arquivos do worker e o BD_Thopen.
- Régua do PR = a do Histórico PR: geração ÷ (IPOA × potência), só nos dias com IPOA > 0,3 kWh/m².
- Meta = a do cliente no BD_Thopen (`dashboard_thopen._meta2026`), não a do 1º ano.
- Fora da meta: PR < 97% da meta. Meta de disponibilidade: 97%. Janela solar: 12 h por dia (06–18h).
- A página segue o mockup, com tokens tirados do PDF, não no olho. Os tokens medidos são:
  - faixa `#181528`, verde `#a9db21`;
  - texto `#191528`, mudo `#504c63`, borda `#ddd9e7`, painel `#f4f2f7`, fio `#edecf4`;
  - positivo `#2e7d32`, atenção `#b7791f`;
  - números em IBM Plex Mono (22,5 pt nos grandes, 13,5 pt nos médios, 9,8 pt na tabela);
  - largura de 960 px.
- O relatório só vai para o PDF depois de o Levi validar a tela (regra "mostrar antes de seguir").
- Commit só quando o Levi mandar. Testes a partir da raiz: `python -m pytest -q`.

## Arquivos

| Arquivo | Papel |
|---|---|
| `plataforma/relatorio_semanal.py` (novo) | Contas puras: PR/meta, disponibilidade, desligamentos, OS, strings, ofensores e montagem. |
| `plataforma/app.py` (bloco do Criador) | Coleta dos insumos, rotas `/relatorio/semanal` e `/api/relatorio/semanal[...]`, persistência. |
| `plataforma/templates/relatorio_semanal.html` (novo) | Página e PDF. |
| `plataforma/templates/relatorio.html` | Link para o semanal na barra. |
| `tests/test_relatorio_semanal.py` (novo) | Motor puro. |
| `tests/test_relatorio_semanal_rotas.py` (novo) | Rotas, persistência e emissão. |
| `tests/test_relatorio_semanal_tela.py` (novo) | Lógica da página no node. |
| `docs/criador-de-relatorio.md`, `plataforma/CLAUDE.md` | Documentação. |

---

### Tarefa 1: PR, meta e perda por unidade e no portfólio (blocos 01, 02 e 05)

**Arquivos:** criar `plataforma/relatorio_semanal.py`; testes em `tests/test_relatorio_semanal.py`.

**Produz:**
- `dias(ini: date, fim: date) -> list[date]`
- `pr_unidade(diario: list[dict], pot_mwp: float, metas: dict, ini: date, fim: date) -> dict`. `diario` é
  `[{data: date, ger: kWh, ipoa: kWh/m²}]`; `metas` é `{mes: {meta: kWh, metairr: kWh/m², pr: fração}}`.
  Devolve `{ger_kwh, den_mwh, pr, pr_meta, meta_kwh, ger_total_kwh, ipoa, ipoa_meta, dias_validos, dias_sem_ipoa,
  dias_pr_alto, dias}`.
- `soma(partes: list[dict]) -> dict` — mesma forma, somando numerador, denominador e metas.
- `fora_da_meta(r) -> bool` e `perda_estimada_mwh(r) -> float`.
- `pr_mensal(unidades: list[tuple[list, float, dict]], ano: int, meses: list[int], hoje: date) -> list[dict]`.

- [ ] **Passo 1:** escrever os testes. Casos:
  - PR ponderado: 2 dias, `ger` 10.000 e 20.000 kWh, IPOA 5 e 5, potência 5 MWp → PR = 30 ÷ (10 × 5) = 0,6.
  - O dia com IPOA 0,2 fica fora do PR, mas entra em `ger_total_kwh` e em `dias_sem_ipoa`.
  - Meta entre meses: 30/09 (meta 0,80) e 01/10 (meta 0,70), IPOA 6 e 2 → meta = (0,8 × 6 + 0,7 × 2) ÷ 8 = 0,775.
  - `meta_kwh` = meta mensal ÷ dias do mês, somada nos dias do período.
  - Fora da meta: PR 0,77 com meta 0,80 → fora (0,77 < 0,776); PR 0,777 → dentro.
  - `perda_estimada_mwh` = (0,80 − 0,70) × den_mwh; nunca negativa.
  - Dia com PR > 1,30 conta em `dias_pr_alto`.
  - `soma` de duas unidades = PR pela soma dos numeradores e denominadores, não pela média dos PRs.
- [ ] **Passo 2:** rodar e ver falhar (`python -m pytest -q tests/test_relatorio_semanal.py`).
- [ ] **Passo 3:** implementar. A régua do Histórico PR, com o dia sem IPOA fora do PR, fica num comentário que cita
  `api_g_diario`.
- [ ] **Passo 4:** rodar e ver passar.

### Tarefa 2: Disponibilidade e desligamentos do período (bloco 04)

**Produz:**
- `disponibilidade(diario_disp: dict, ini: date, fim: date) -> dict`. `diario_disp` é
  `{"AAAA-MM-DD": {h_eq, h_q, h_e}}`; devolve `{disp, h_eq, h_q, h_e, dias}` com disp = 100 × (1 − Σh_eq ÷ (12 × dias)).
  Dia ausente = 100%.
- `disponibilidade_portfolio(itens: list[tuple[dict, float]]) -> dict`: pondera pelo kWp e devolve `{disp,
  indisp_grid, indisp_ext}`, as duas em % da energia possível (h_e e h_q).
- `desligamentos(oss: list[dict], ini: date, fim: date, usinas: set | None) -> dict`. `oss` é a lista `oss` do
  índice (`origem` queda/equip, `ini`, `fim`, `usinas`, `aberta`). Devolve `{queda: {n, h}, equip: {n, h},
  religamento_medio_min}`, com as horas recortadas no período e na janela 06–18h.

- [ ] **Passo 1:** testes:
  - `h_eq` 1,553 num dia de 7 → disp = 100 × (1 − 1,553 ÷ 84) = 98,15.
  - Dias fora do período não contam.
  - Portfólio 1.000 kWp a 90% e 3.000 kWp a 100% → 97,5.
  - OS de queda das 17:00 de um dia às 07:00 do seguinte → 1 h + 1 h de janela solar.
  - OS aberta sem fim: conta na quantidade, 0 h, e fica fora da média de religamento.
  - O filtro de usinas limita as OS às da unidade.
  - A média de religamento é em minutos, só das OS de queda terminadas no período.
- [ ] **Passo 2:** ver falhar. **Passo 3:** implementar. **Passo 4:** ver passar.

### Tarefa 3: O que a Grid executou, strings e ofensores (blocos 03 e 05)

**Produz:**
- `os_executadas(linhas: list[dict], sites: set[str], ini: date, fim: date) -> dict`. `linhas` são as de
  `frac_mtta_linhas.json`. Devolve `{corretivas: {concluidas, total}, preventivas: {realizadas, planejadas}}`, pelo
  evento no período (Brasília = UTC−3). Status 2 e 3 = concluída; 4 = cancelada, fora; o resto = aberta. Uma OS é
  contada uma vez (`wo_folio`).
- `strings_voltaram(episodios: list[dict], ini: date, fim: date, usinas: set | None) -> int`: episódios de string da
  aba de falhas com `fim` dentro do período.
- `ofensores(disp: dict, deslig: dict, trk: list[dict], strs: list[dict], pr: dict, kwh_indisp: float) -> list[dict]`:
  `[{tipo, texto, kwh}]`, com o maior primeiro. Os tipos são `desligamento`, `tracker`, `string` e `ipoa`.
- `causa_sugerida(ofensores: list[dict]) -> str`.

- [ ] **Passo 1:** testes:
  - Corretiva e Corretiva Emergencial somam; Administrativa não conta.
  - Cancelada fica fora; OS com duas tarefas conta uma vez.
  - Evento às 01:00 UTC do dia 29 é dia 28 em Brasília.
  - Preventiva realizada × planejada.
  - Strings: um episódio que termina no período conta; um sem fim não conta.
  - Ofensores ordenados pelo kWh.
  - IPOA não confiável quando mais da metade dos dias não tem IPOA, ou quando há dia com PR > 130%.
  - Sem ofensor → "Sem ofensor medido — verificar sujidade, vegetação ou limitação".
- [ ] **Passo 2:** ver falhar. **Passo 3:** implementar. **Passo 4:** ver passar.

### Tarefa 4: Unidades e montagem do relatório

**Produz:**
- `unidades(indice: list[dict], bd_nomes: set[str], chave, grupos: list[dict], alias: dict) -> list[dict]`. `indice`
  são as usinas Thopen do índice de disponibilidade; `chave` é `_usina_chave_solta`. Devolve `[{nome, bd: [abas do
  BD], disp: [usinas do índice], sites: [sites Fracttal], kwp}]`.
- `montar(ini, fim, unids, leitores) -> dict`, o payload inteiro: `periodo`, `resumo`, `evolucao`, `executado`,
  `disponibilidade`, `fora_da_meta` (com `ofensores` e `causa_sugerida`) e `avisos`. `leitores` é um objeto com
  `diario(aba)`, `pot(aba)`, `metas(aba)`, `disp_diario(usina)`, `oss()`, `linhas_os()`, `falhas()` e `hoje` — o
  app passa os reais e o teste passa stubs.

- [ ] **Passo 1:** testes:
  - Nova Londrina 1+2 viram uma unidade (a aba "Nova Londrina"), com a disponibilidade ponderada pelo kWp das duas.
  - Ouro Branco soma as abas I a V.
  - A grafia casa pela chave solta (Corrego × Córrego); Vargem Grande IB = Vargem Grande 1 pelo alias.
  - Usina sem aba ou sem meta vai para `avisos` e fica fora das contas.
  - O payload tem os cinco blocos, e `fora_da_meta` vem ordenado pela perda.
- [ ] **Passo 2:** ver falhar. **Passo 3:** implementar. **Passo 4:** ver passar.

### Tarefa 5: Rota de leitura e página (somente leitura) — CHECKPOINT com o Levi

**Arquivos:** `plataforma/app.py` (bloco `═══ CRIADOR DE RELATÓRIO ═══`), `plataforma/templates/relatorio_semanal.html`,
`tests/test_relatorio_semanal_rotas.py`.

- [ ] **Passo 1:** testes de rota com stubs:
  - `GET /api/relatorio/semanal?ini=2026-09-21&fim=2026-09-27` devolve `ok` e os blocos.
  - Datas inválidas ou `ini > fim` devolvem 400.
  - `GET /relatorio/semanal` devolve 200.
- [ ] **Passo 2:** implementar a coleta com os leitores de hoje, sem chamada de rede:
  - `dashboard_thopen._daily_records`, `_meta2026` e `_registro`;
  - `_g_th_pot`, `_frac_disp_dados()`;
  - `frac_mtta_linhas.json` (lido e guardado pelo mtime);
  - `_falhas_ler(_falhas_arquivo(mes))`;
  - `_usina_chave_solta`, `_GER_GRUPOS` e o alias da Vargem Grande.
- [ ] **Passo 3:** a página, no layout do mockup e na ordem nova (01 Resumo, 02 Evolução, 03 Executado,
  04 Disponibilidade, 05 Fora da meta). Barra: De, Até, Gerar e Semana passada. A fonte do texto é conferida lado a
  lado com o PDF (IBM Plex Sans × Poppins).
- [ ] **Passo 4:** rodar os testes. Gerar a semana de 21 a 27/09 com dado real na plataforma local de teste (porta
  livre, sem mexer na 5050), tirar a captura de tela e abrir no navegador do Levi.
- [ ] **Passo 5 — CHECKPOINT:** mostrar ao Levi os números e a tela. Seguir só com o "ok".

### Tarefa 6: Direcionamentos, emissão e PDF

- [ ] **Passo 1:** testes:
  - `POST /api/relatorio/semanal/direcionamento {ini, fim, usina, campo, valor}` grava em `relatorio_semanal.json`; o
    GET seguinte devolve o campo.
  - campo trocado é recusado (400): causa, acao e previsao vão **com** a usina; leitura, responsavel e contato,
    **sem**; e campo fora dessas seis.
  - `POST /emitir` sem leitura ou com linha do bloco 05 sem causa ou ação devolve `ok: false` e a lista do que falta.
  - Com tudo preenchido, devolve `R00`, e a segunda emissão `R01`.
  - Na página (node): a função que lista o que falta.
- [ ] **Passo 2:** implementar:
  - campos editáveis, que viram texto na impressão;
  - auto-salvar com pausa de 800 ms;
  - "Emitir PDF" valida, registra a versão, preenche o cabeçalho, troca o `document.title` e chama `window.print()`.
- [ ] **Passo 3:** rodar os testes e mostrar ao Levi uma emissão de ponta a ponta, com o PDF salvo.

### Tarefa 7: Conferência com dado real e documentação

- [ ] Conferir o PR semanal de três usinas contra o Histórico PR no mesmo período, e a disponibilidade de setembro
  contra o painel de Disponibilidade. Diferença = 0 ou explicada.
- [ ] Link na barra do `relatorio.html`.
- [ ] Atualizar `docs/criador-de-relatorio.md` (o tipo novo) e `plataforma/CLAUDE.md`.
- [ ] Rodar a suíte inteira (`python -m pytest -q`), com `TRK_REGUA_V2=1` e com `0`.
- [ ] Reportar ao Levi o que ficou pronto, os números e o que ficou para depois. Commit só quando ele mandar.
