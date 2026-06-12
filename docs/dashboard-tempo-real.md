# Dashboard em Tempo Real — Blueprint (Histórico do BD + Vivo da API)

> Objetivo: replicar o dashboard de **PR por usina/inversor** do Power BI
> (`BD_Performance`) numa visão **em tempo real** dentro do próprio dashboard web
> (Flask, `app.py`, porta 5050). **Retroativo** vem do banco/planilha; **o "agora"**
> vem das APIs que o app já consome. Última atualização: 2026-06-11.

---

## 1. Decisão de arquitetura

| Camada | Fonte | Já existe no app? |
|---|---|---|
| **Retroativo** (PR diário oficial) | `BD_Performance.xlsx` (consolidado diário do Power BI) | parcial — falta o consolidado |
| **Série plotada** (diário/intradiário) | **Banco**: PostgreSQL (`dbt`, Thopen) + BD_Performance/BD_Thopen — ver §9 | **sim** (subaba "📊 Geração") |

> **Escopo: SÓ HISTÓRICO.** Sem KPI "ao vivo" da apipv — a apipv tem PR em tempo real,
> mas não entra nesta tela em nenhuma forma. Tudo plotado vem do banco.
| **Metas / previsto** | `BD_Performance` → abas **Info Geral** + **Info Mensal** | **sim, implementado** (`load_metas`) |
| Render | `templates/index.html` + Plotly, nova aba "Tempo Real" | a fazer |

O motor histórico (Power BI) e o motor vivo (`app.py`) **compartilham o mesmo
cadastro mestre** (`BD_Performance`: Equipamentos, Info Geral, Info Mensal) e os mesmos
`idusina`. A construção é, essencialmente, **fazer os dois conversarem**.

## 2. A fórmula de PR é a mesma dos dois lados

```
Power BI:  PR% = (Geração kWh / 1000) / (IPOA_DEF × Potência_MWp) × Validação
app.py:    PR_inv = Eday / (IPOA × Potência_inv)        ← /api/pv/pr (já existe)
```

São idênticas. O "PR ao vivo" **já está calculado**. O que faltava era a **meta**
(`PR Previsto`) e o tratamento de **dia parcial** — agora resolvidos pelos helpers
`pr_previsto()` / `geracao_alvo_mwh()`.

## 3. Gotcha central: dia parcial

O PR do Power BI usa IPOA do **dia fechado**. Ao vivo, às 11h só ~metade da
irradiância foi integrada. Portanto:

- **PR instantâneo já é justo** — IPOA e Eday crescem juntos, a razão se mantém
  (`/api/pv/pr` integra a POA por trapézio até o último ponto).
- **A meta NÃO pode ser comparada cheia** — use `geracao_alvo_mwh(usina, ipoa_ate_agora)`,
  que multiplica pela IPOA parcial, não a do dia todo.
- ⚠️ Telemetria que não fechou dá valor uniforme baixo → re-coletar no dia seguinte.

## 4. Metas — o que foi implementado (passo 1, FEITO)

`load_metas()` no `app.py` (espelha as queries M `InfoGeral`/`InfoMensal` do Power BI):

- **Globais:** `INFO_GERAL` (148 usinas) e `PR_PREVISTO` (152 usinas × meses).
- **Regra do Power BI replicada:** `PR Previsto = PR Previsto 1° Ano (%) + Perdas por degradação`.
- **Helpers:**
  - `info_geral(usina_display)` → `{potencia_kwp, potencia_mwp, qtd_inv, p50_mwh, degradacao, cliente}`
  - `pr_previsto(usina_display, ano, mes)` → fração (fallback p/ mesmo mês de outro ano)
  - `geracao_alvo_mwh(usina_display, ipoa, ano, mes)` = `IPOA × PR_Previsto × Potência_MWp`
- **Recarga:** entra no mesmo `maybe_reload_equipamentos` (mtime do BD_Performance).

### ⚠️ Reconciliação de nomes (CRÍTICO)
`INFO_GERAL`/`PR_PREVISTO` são chaveadas pelo **nome de EXIBIÇÃO** da coluna `Usina`
("Araputanga", "Cedro 1", "Macaiba 1", "Irece 2") — exatamente os nomes dos dashboards.
O lado vivo precisa produzir o mesmo nome (via `nome_usina()` / `USINA_DISPLAY`) para o
join casar. Usinas **sem API** (ex.: Cedro 1/2) são **história-only** — aparecem só no
retroativo. NÃO confundir com o nome da *tabela* do Power BI (`TCedroI`, numeral romano).

## 5. Próximos passos

2. **Endpoint híbrido** `/api/realtime/pr` (e `/api/realtime/pr/<id>`): por usina/inversor
   devolve `pr_atual` (de `/api/pv/pr`), `pr_previsto` (meta), `dif = pr_atual − pr_previsto`,
   `geracao_ate_agora`, `geracao_alvo` (parcial), `cobertura%`. Reusa `/api/pv/pr` + helpers.
3. **Retroativo**: ler o **consolidado diário** que o Power BI produz, ou reconstruir em
   Python a query mestre (bloco "1 - Consolidado Diário", linhas ~416 do .txt original)
   lendo as abas `T<Usina>` do BD_Performance + BD_Thopen. Curvas mensal/diária = leitura direta.
4. **Aba "Tempo Real"** no `index.html` (Plotly), 3 painéis das imagens de referência:
   Top 10 piores inversores · Performance por inversor (PR × Dif) · PR Realizado × Previsto.
   Auto-refresh alinhado ao `CACHE_TTL` (5 min) — ou menor para a parte instantânea.
5. **PR GRID / PR UFV** = agregação ponderada por energia (ver §8).

## 8. Regra de AGREGAÇÃO de PR (correção crítica — do DAX `PR Agregado Mensal`)

O Power BI **nunca tira média de PRs**. Ele soma numerador e denominador separadamente e
só então divide — **ponderado por energia** — e **filtra `validação > 0`** (geração e IPOA
saem dos mesmos dias válidos; um dia com IPOA furada sai dos dois somatórios juntos):

```
PR(nível) = Σ Geração (validação>0)  /  ( Σ IPOA (validação>0) × Potência )
```

A mesma regra vale em todo nível de agregação (NÃO usar média simples):

| Nível | Fórmula |
|---|---|
| Inversor | `Eday / (IPOA × Potência_inv)` |
| **Usina** | `Σ Eday(inv) / (IPOA × Σ Potência_inv)` |
| **PR UFV / PR GRID** (frota) | `Σ Geração(usina) / Σ(IPOA_usina × Potência_usina)` |

No intradiário, o equivalente do filtro `validação > 0` é o `cobertura%`/flag de sensor
(descartar inversor/usina cuja curva de POA não fechou). A meta tem duas formas
consistentes: `PR Previsto` (%) **ou** `Meta Geração = IPOA × PR_Previsto × Potência` (kWh,
somável) — usar a forma em geração ao agregar metas no mês.

**Assimetria (intencional, agora explicada):** em `PR Agregado Mensal`, IPOA e Geração
levam `FILTER validação>0`, mas `Meta Mensal Alternativa = SUM(Meta Mensal Geração)` **não
filtra**. Faz sentido com o SWITCH: a meta cobre o mês INTEIRO (dias sem dado válido entram
via `P50 ÷ dias`), enquanto realizado/IPOA só somam dias medidos. Reproduzir igual:
`meta_geracao_dia()` por dia (todos os dias) e somar; geração/IPOA só `validação>0`.

## 6. Divergência JCD100 (78,8% × 74,5%) — ESCLARECIDA

Não era erro do loader: são métricas diferentes.
- **78,8%** = `PR Previsto` cru da Info Mensal (junho). Correto como *insumo*.
- **74,5%** = PR Alvo *exibido* = `Σ Meta Mensal Geração ÷ (Σ IPOA × Potência)` agregado no
  período. Nenhum mês de 2026 do JCD100 dá 74,5% → é agregação por período, não meta mensal.
- Verificado: metas mensais JCD100/2026 variam de 63,3% (fev) a 78,8% (jun).

**RESOLVIDO** — a coluna `Meta Mensal Geração` (DAX) é um SWITCH com fallback P50:
1. `Validação = 0` → `P50 mensal ÷ dias do mês`
2. `IPOA > 0` (validado) → `IPOA × PR Meta × Potência`
3. `IPOA ≤ 0`/nulo → `P50 mensal ÷ dias do mês`

É **por isso** que o PR Alvo agregado desvia do `PR Previsto` puro: dias sem irradiância
válida usam P50 rateado, não a meta proporcional. Implementado fielmente em
`meta_geracao_dia(usina, data, ipoa, validacao)` no `app.py` (3 ramos validados).
⚠️ Assumido `PR Meta` == `PR Previsto` (= `pr_previsto()`); confirmar se forem colunas distintas.

## 9. Hierarquia de CONFIANÇA das fontes (regra do usuário)

A apipv tem PR em tempo real, **mas só os dados do BANCO são confiáveis para gráfico**.
**Escopo é só histórico** — a apipv NÃO entra nesta tela (nem como KPI).

| Uso | Fonte de verdade | Observação |
|---|---|---|
| Série intradiária plotada (Thopen) | **PostgreSQL** `dbt` (subaba 📊 Geração) | IPOA/GHI por trapézio, 5 min |
| PR oficial / histórico (todos) | **BD_Performance / BD_Thopen** (fonte Power BI) | diário validado (`validação>0`) |
| apipv (PR ao vivo) | — | **fora de escopo** (não plotar nem exibir) |

⚠️ **PostgreSQL ~50% de cobertura** → se o gráfico confia no PG, a flag `cobertura%`
é **OBRIGATÓRIA** (gap de IPOA subestima o denominador e infla o PR sem aviso).
Em aberto: fonte de gráfico confiável para clientes **fora do PG** (Athon/SunOp,
RenoGrid/SolarEdge, 2C) — provável BD_Performance/BD_Thopen diário até existir banco próprio.

## 7. Riscos herdados (de `arquitetura.md`)

- `BD_Performance` desidrata no OneDrive → `_bd_perf_path()` já prioriza versão online.
- apipv lenta (~65 s 1ª carga) e POA inconsistente por usina (`_pick_irr` trata).
- Tokens (SunOp, Plataforma) expiram ~7 dias → meta parcial cai se a fonte cair.
- PostgreSQL ~50% de cobertura → IPOA subestima (flag de cobertura mitiga).
