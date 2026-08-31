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

**A fonte é o PostgreSQL** (Levi, 28/08/2026): a coleta continua ESCREVENDO no `BD_Thopen.xlsx`,
o `sync_gridco_api.py` leva o arquivo para o banco, e o dashboard só LÊ do banco. `fonte_api.py`
monta o mesmo workbook em memória a partir da Gridco Performance API — por isso todos os
leitores continuam sendo código de worksheet.

- `GRIDCO_API_TTL` (600 s) é o intervalo de recarga; `/api/t/reload` derruba o cache na hora.
- `THOPEN_FONTE=xlsx` força o arquivo — é como se compara antes/depois de mudar algo.
- **Fallback:** se a API não responder, cai no `.xlsx` (local ao vivo, ou o snapshot de `data/`
  na nuvem; `THOPEN_DATA_DIR` sobrescreve a pasta). Isto é produto de cliente — banco fora do ar
  não pode deixar a tela muda.
- Ler `.xlsx` sempre por cópia (`_open_wb`): o Excel/OneDrive tranca o arquivo aberto.
- Trocar a fonte é a mudança mais arriscada que existe aqui. Prove com número: `_snap_dash.py`
  fotografa as ~1.300 respostas dos endpoints e `_diff_snap.py` compara antes/depois.

## Acoplamento com a plataforma

`plataforma/app.py` importa este módulo para usar três leitores do `BD_Thopen.xlsx`:
`_CARTEIRA_DE`, `_registro()` e `_daily_records()`. **Não mude a assinatura nem o formato de
retorno dessas três sem checar o uso lá** — é o único ponto de contato entre os dois projetos.

## Carteiras

Os botões de carteira saem do dicionário `CARTEIRAS` neste arquivo (de-para carteira → usinas).

Nenhuma carteira depende mais de Excel externo: Copel, Matrix, Caroá e Piancó moram na aba
**Histórico Carteira** (a coluna `Fonte` separa) e a Polaris tem aba diária por usina + a aba
**Histórico Polaris**, que é a camada de CORREÇÃO MANUAL — o que estiver escrito lá sobrescreve
o automático campo a campo, e célula vazia não apaga nada. Os Excel de Budget/Matrix/Copel
seguem no código só como fallback do snapshot antigo da nuvem.
