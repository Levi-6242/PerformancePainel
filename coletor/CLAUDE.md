# Coletor automatizado de dados

Scripts que puxam geração e irradiância das APIs e gravam nas planilhas-base
(`BD_Performance.xlsx`, `BD_Thopen.xlsx`). Ver o `CLAUDE.md` da raiz para as convenções gerais.

| Arquivo | O que faz |
|---|---|
| `collect_energy.py` | Energia por período (`--start/--end` ou `--days`), saída em `.xlsx` |
| `coletar_geracao_hoje.py` | Geração do dia, alimenta o Check Diário |

## Atenção: o que roda agendado NÃO é este código

A Tarefa Agendada do Windows **"Coletor GridCo - 22h30"** executa um **executável compilado** em
`%LOCALAPPDATA%\Coletor GridCo\Coletor GridCo.exe`, não estes `.py`. Ou seja:

- mexer aqui **não** muda o que roda agendado — é preciso regerar e redistribuir o `.exe`;
- e mover estes arquivos **não** quebra a coleta agendada.

Se o comportamento em produção divergir do código daqui, essa é a explicação mais provável.

## Cuidados com as planilhas

- Ambos leem `.env` da **raiz** do repositório (`load_dotenv` com caminho relativo ao arquivo).
- Escrever em planilha é destrutivo: teste em cópia e faça backup antes.
- O OneDrive sobrescreve o arquivo se ele estiver aberto na nuvem enquanto o script grava — a
  gravação do dia pode ser perdida. Confirme que ninguém está com a planilha aberta.
- Gravação de meta/geração deve ser **cirúrgica** (linha da data existente), nunca reescrever a aba.
