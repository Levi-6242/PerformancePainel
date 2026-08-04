# Dashboard BD_Thopen — produto do cliente

Flask na porta **5080** (`dashboard_thopen.py`, ~960 linhas). Réplica do Power BI que o cliente
Thopen acessa, publicada no **Railway**. Lê o `BD_Thopen.xlsx` — o mesmo arquivo que o Power BI
consome. Ver o `CLAUDE.md` da raiz para as convenções gerais.

**É produto de cliente, não ferramenta interna.** Mudança aqui é visível para fora: teste antes
e evite alterar layout sem pedido.

## Rodar

Local: `python dashboard_thopen.py` → porta 5080.

Nuvem: o Railway usa `deploy/Procfile` e `deploy/railway.toml`. Como o app desceu para `thopen/`
na separação por projeto, ambos passam **`--chdir thopen`** ao gunicorn:

```
gunicorn dashboard_thopen:app --chdir thopen --bind 0.0.0.0:$PORT --workers 2 --timeout 180
```

Se mover este arquivo de novo, esses dois arquivos precisam acompanhar — senão o deploy do cliente
quebra.

## Dados

- **Local:** lê o `BD_Thopen.xlsx` ao vivo do OneDrive/SharePoint (dados sempre atuais).
- **Nuvem:** lê o snapshot versionado em `data/` (o repositório é privado). Atualizar a nuvem =
  novo push da pasta `data/`, que também traz as planilhas externas de Polaris, Matrix e Copel.
- `THOPEN_DATA_DIR` sobrescreve a pasta de dados.
- Ler `.xlsx` sempre por cópia (`_open_wb`): o Excel/OneDrive tranca o arquivo aberto.

## Acoplamento com a plataforma

`plataforma/app.py` importa este módulo para usar três leitores do `BD_Thopen.xlsx`:
`_CARTEIRA_DE`, `_registro()` e `_daily_records()`. **Não mude a assinatura nem o formato de
retorno dessas três sem checar o uso lá** — é o único ponto de contato entre os dois projetos.

## Carteiras

Os botões de carteira saem do dicionário `CARTEIRAS` neste arquivo (de-para carteira → usinas).
Polaris vem por Excel de Budget separado; Matrix e Copel combinam planilha externa antes de uma
data de corte com o BD depois dela.
