# Instruções de integração — App de Campo → Plataforma de Performance

Para o desenvolvedor do middleware/puxador (lado `gridco-campo`). A plataforma expõe a **ronda de
trackers por usina**; o app de campo consome. A régua e os tokens das fontes ficam na plataforma.

> **Estado (05/08): o lado da plataforma está LIGADO e verificado (`200` ao vivo).**
> Falta só o `PERF_API_BASE` do lado de vocês (o endereço estável — ver §4).

## 1. O que a plataforma expõe
```
GET  {PERF_API_BASE}/api/campo/ronda?usina=<nome>     Header: x-api-key: <chave>
GET  {PERF_API_BASE}/api/campo/usinas                 Header: x-api-key: <chave>
```
Contrato completo (campos da resposta, filtros, erros): **`api-campo-ronda.md`** neste pacote.
- `usina` aceita 3 formatos do mesmo nome: catálogo Fracttal (`Thopen - Ibaté 1 - SP`), display
  (`Mandaguaçu 4 (143)`) ou nome da fonte (`TIM100`). Use `/api/campo/usinas` para popular o seletor.
- Padrão = **parados + sem comunicação**. `?desvios=1` inclui fora-do-alvo agora; `?tudo=1` = todos.
- **Sub-usinas:** nome de catálogo que cobre várias sub-usinas (Ceilândia 2 = 4, Altair 1-5…)
  devolve `400` com `subusinas[]` — consulte cada uma pelo próprio nome e some no seu lado.
  `/api/campo/usinas` traz `grupos` com o mapeamento pronto (19 grupos hoje). Relevante para o
  diagnóstico no Ceilândia 2: espere o `400` estruturado no nome do grupo, e `200` nas 4 sub-usinas.

## 2. Autenticação — a chave NÃO está aqui (de propósito)
- Header `x-api-key`. A chave é entregue por **canal privado** (arquivo
  `CHAVE_para_plataforma_performance_NAO_COMPARTILHAR.txt`), nunca num documento que circula.
- No lado de vocês ela já está como App Setting **`PERF_API_KEY`**.
- No lado da plataforma ela vira **`CAMPO_API_KEY`** no `tokens.txt` (passo do time de Performance).

## 3. Ligar — dois lados, nenhum deploy de código

**Lado Plataforma (time de Performance) — ✅ FEITO (05/08):**
`CAMPO_API_KEY` já está no `tokens.txt`, o web foi reiniciado, e o endpoint responde `200`
(verificado ao vivo com ronda real). Nada pendente do nosso lado.

**Lado Middleware (vocês) — falta 1:**
1. `PERF_API_BASE = <endereço base ESTÁVEL da plataforma>`  ← **o único bloqueio** (ver §4).
2. `PERF_API_KEY` — já configurada.
3. `PERF_PULL_ATIVO = 1`.

## 4. Endereço estável (PERF_API_BASE) — decisão SUA (delegada em 06/08)
O puxador roda **todo dia 06:10** e precisa de um endereço **fixo**. Estado real do nosso lado,
auditado em 06/08: a plataforma sai por **túnel Cloudflare QUICK** (nome sorteado a cada subida);
**nunca houve túnel nomeado** nesta máquina, e não temos hoje conta Cloudflare com a zona DNS de
um domínio da Grid. Ou seja: o endereço estável **ainda não existe** — e a escolha da rota é sua
(você é o dono do `PERF_API_BASE` e de quem o consome).

**Opções na mesa** (todas atendem seus 2 requisitos: nome fixo + alcançável da internet):
| | Rota | O que exige | Prazo |
|---|---|---|---|
| A | **Túnel nomeado em domínio da Grid** (ex.: `perf.gridco.com.br`) | acionar o T.I.: zona DNS do domínio numa conta Cloudflare | ~15 min de config depois do acesso |
| B | **Túnel nomeado em domínio que VOCÊ controla** | nada do T.I.; endereço "fora da marca" | ~15 min |
| C | **Hospedagem do T.I.** (junto da migração pro PC dedicado) | redeploy do app atual lá; prazo do T.I. | semanas |

**Compromisso do nosso lado:** escolhida a rota, executamos a nossa parte (config do `cloudflared`
como serviço, identidade fixa, HTTPS). O túnel nomeado **sobrevive à migração de máquina** (a
credencial viaja junto — o endereço não muda depois). O que **não** serve: `*.trycloudflare.com`
(efêmero — quebraria calado na primeira queda, como você mesmo apontou).

## 5. Antes de ligar de vez — diagnóstico
Rodem o `/api/perf/diag?usina=Thopen - Ibaté 1 - SP` de vocês: ele confere se a chave passou, se o
nome resolve dos dois lados e quantos trackers casam com o Fracttal — **sem gravar nada**. Só ligue
o `PERF_PULL_ATIVO=1` depois que os três pontos baterem.

## 6. Realidade dos dados (não é defeito da integração)
A trava de vocês — comparar `total_trackers` do supervisório com a contagem do catálogo, e só
resolver o ativo Fracttal quando batem — **está exatamente certa**. OS de garantia no equipamento
errado é pior que OS nenhuma. Expectativa medida:
- Das **87** usinas nossas com tracker, o supervisório reporta ~**56** → ~30 ficam sem lista.
- Dessas 56, a numeração é confiável em ~**22** → o botão de chamado aparece nessa fração.
- Isso **se corrige sozinho** conforme a relação supervisório↔Fracttal fecha, sem mexer no código.
- A lista de trabalho, usina por usina, é o **`levantamento_supervisorio_x_fracttal.xlsx`** (neste pacote).

## 7. Fracttal deferido
Por enquanto o `tracker` vem pelo **número do supervisório** (a relação com o ativo Fracttal está
sendo lapidada). Quando fechar, entra um campo novo (ex.: `ativo_fracttal`) **sem quebrar o contrato**.
