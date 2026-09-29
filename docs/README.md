# Documentação — Dashboard O&M Grid Co.

Documentação técnica do projeto. Para o Monitoramento (Strings, ETM, Trackers, Entrada,
alertas), comece pelo [Tempo real](tempo-real.md); os demais documentos aprofundam regras e
integrações específicas.

| Documento | O que cobre |
|---|---|
| [**Tempo real**](tempo-real.md) | **Referência atual do Monitoramento (29/09/2026).** Worker × web e snapshot, o ciclo e os TTLs, as 9 fontes, a régua de strings (diferença por inversor, inversor desligado, pouca luz, OS atribuída), o status da usina na tela, usina calada e relógio, tickets, ETM, trackers (régua v2), drill-down, Entrada e macro, sino e ronda, o estado medido no servidor e os defeitos conhecidos. |
| [**Arquitetura & Operação**](arquitetura.md) | Visão geral de junho: stack, as fontes de dados (auth/endpoints), cadastro mestre e de/para de nomes, armazenamento, automações, riscos. Defasado no tempo real (fala em 6 fontes e não tem worker nem snapshot) — vale o [Tempo real](tempo-real.md). |
| [**Regras de Negócio**](regras-de-negocio.md) | Detalhamento funcional de junho. As seções de string ativa, ETM e trackers estão defasadas — vale o [Tempo real](tempo-real.md); planilha Check Diário e estado compartilhado seguem valendo. |
| [**API PV Operation**](api-pv-operation.md) | Referência da apipv (Thopen): autenticação, endpoints, o que existe e o que não existe, como os scripts de coleta funcionam. |
| [**API SunOp**](coleta-sunop.md) | Referência da SunOp (Athon): endpoint `analog_values` (histórico), pathnames, cálculo de energia (EPD) e irradiância, autenticação JWT. |
| [**Criador de Relatório**](criador-de-relatorio.md) | A página `/relatorio`: o motor `_relatorio_build` passo a passo (série, trackers, OS do Fracttal, déficit medido, confiabilidade), as seções, o PDF, o que gera hoje e o que não gera, e como incluir um tipo novo (o semanal). |
| [**PR ao vivo (blueprint)**](dashboard-tempo-real.md) | Blueprint de junho para replicar o PR por usina/inversor do Power BI numa visão ao vivo: histórico do BD + tempo real da API, fórmula de PR, dia parcial, loaders de metas (Info Geral/Mensal). Não descreve o Monitoramento — para isso, [Tempo real](tempo-real.md). |

## Convenções

- Documentos em **PT-BR** (idioma do projeto).
- Datas no formato em que cada doc foi atualizado (cabeçalho de cada arquivo).
- Credenciais **nunca** aparecem na documentação — sempre referenciadas pelas variáveis
  do [`.env.example`](../.env.example).
