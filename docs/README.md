# Documentação — Dashboard O&M Grid Co.

Documentação técnica do projeto. Comece pela [Arquitetura](arquitetura.md) se está
chegando agora; os demais documentos aprofundam regras e integrações específicas.

| Documento | O que cobre |
|---|---|
| [**Arquitetura & Operação**](arquitetura.md) | Visão geral completa: stack, as 6 fontes de dados (auth/endpoints), cadastro mestre e de/para de nomes, armazenamento, gotchas já resolvidos, automações, riscos e como operar. **Documento principal de handover.** |
| [**Regras de Negócio**](regras-de-negocio.md) | Detalhamento funcional: regra de "string ativa", pré-análise ETM, critérios de trackers (parado/desvio/atraso), planilha Check Diário, estado compartilhado da equipe. |
| [**API PV Operation**](api-pv-operation.md) | Referência da apipv (Thopen): autenticação, endpoints, o que existe e o que não existe, como os scripts de coleta funcionam. |
| [**API SunOp**](coleta-sunop.md) | Referência da SunOp (Athon): endpoint `analog_values` (histórico), pathnames, cálculo de energia (EPD) e irradiância, autenticação JWT. |

## Convenções

- Documentos em **PT-BR** (idioma do projeto).
- Datas no formato em que cada doc foi atualizado (cabeçalho de cada arquivo).
- Credenciais **nunca** aparecem na documentação — sempre referenciadas pelas variáveis
  do [`.env.example`](../.env.example).
