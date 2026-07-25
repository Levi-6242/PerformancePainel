# Plataforma de Performance — Guia de Instalação (T.I)

Aplicação web **Flask (Python)** que consolida a operação das usinas (strings, trackers, painéis NOC/PR).
Sobe **um único processo** e escuta em **`http://0.0.0.0:5050`** (servidor embutido *waitress*; **não** precisa de IIS/nginx).

> Este pacote é uma **instalação COMPLETA e do zero**: já vem com o `tokens.txt` preenchido, então o app
> sobe **autenticado** em todas as fontes. O `tokens.txt` contém **segredos** — trate o zip como sigiloso
> (não subir em git, não mandar por canal aberto).

---

## 1. O que vem no pacote (`oem-app.zip`)

| Item | Papel |
|---|---|
| `app.py` | A aplicação (servidor da porta 5050) |
| `dashboard_thopen.py` | Motor de carteiras/gerencial (importado pelo `app.py`) |
| `tracker_watch.py` | Livro de ocorrências de trackers (importado pelo `app.py`) |
| `ronda_guardian.py` | Vigia opcional: religa o servidor se a porta 5050 cair |
| `templates/` · `static/` | Interface web |
| `data/` | BD_Thopen.xlsx + planilhas Copel/Matrix/Polaris (dados dos painéis) |
| `docs/` | Documentação + telas do redesign (a rota `/v2` lê `docs/redesign`) |
| `BD_Performance.xlsx` | Cadastro de usinas/equipamentos (fallback local) |
| `trackers_garantia.json` | Referência: trackers com chamado de garantia aberto |
| `requirements.txt` | Dependências Python |
| **`tokens.txt`** | **Credenciais consolidadas — o ÚNICO arquivo de segredo. Editar aqui p/ atualizar tokens.** |
| `.env.example` | Modelo de referência das variáveis (o `tokens.txt` já substitui isto) |

**O que o app CRIA sozinho depois (estado de runtime — nunca apagar num update):**
`sunop_token.txt` / `axis_token.txt` (tokens auto-renovados) · `cache_snapshot.json` · `ufv_state.json`
(comentários dos analistas) · `tracker_issues.json` / `trk_eventos.json` (histórico de trackers) ·
`owen_accum.json` · `fracttal_index.json` · `string_notas.json`.

---

## 2. Instalação do zero (o caso desta entrega)

1. **Python 3.12+** (desenvolvido no 3.14) com `pip` no PATH.
2. Apagar a pasta antiga da aplicação (se existir) e **extrair o `oem-app.zip`** na pasta de destino.
3. Instalar as dependências:
   ```bat
   cd <pasta_da_aplicacao>
   python -m pip install -r requirements.txt
   ```
4. **Conferir o `tokens.txt`** na raiz — já vem preenchido. Nada a fazer se as credenciais estão válidas.
5. Subir:
   ```bat
   python app.py
   ```
   Console mostra `[server] waitress em http://0.0.0.0:5050`.
   Para rodar **sem janela** (background): `pythonw.exe app.py` ou a tarefa da seção 5.

**Validar (2 checagens):**
```bat
curl http://localhost:5050/healthz          &:: → responde OK, sem login
```
e abrir `http://<ip-do-servidor>:5050` no navegador → tela de login → entrar com a senha (`DASH_PASSWORD` do `tokens.txt`).

> **Aquecimento:** nos primeiros ~5–10 min os contadores de trackers/strings podem aparecer zerados/parciais
> enquanto os caches reconstroem. É normal — não reiniciar por causa disso.

---

## 3. Atualizar credenciais (rápido) — o `tokens.txt`

Todas as credenciais ficam em **um só arquivo**, o `tokens.txt` na raiz. Para trocar qualquer token:

1. Abrir `tokens.txt` num editor de texto.
2. Editar o valor da linha (formato `CHAVE=VALOR`; linhas com `#` são comentário).
3. Salvar e **reiniciar o app** (seção 4).

Cada bloco do arquivo tem a instrução de **como renovar** aquele token. Os mais sensíveis:

| Token | Comportamento | Quando mexer |
|---|---|---|
| `PLAT_TOKEN` (Plataforma) | **Manual, ~7 dias, NÃO auto-renova** | Renovar quando a tela avisar "vencido". `plataforma.pvoperation.com` → F12 → header `x-auth-token-update`. |
| `SUNOP_TOKEN` / `AXIS_TOKEN` | **Auto-renova** sozinho | Só recolar se o servidor ficar **dias desligado**. |
| `PV_*`, `SE_*` | Login automático (usuário/senha) | Só se a senha mudar. |
| `PG_*`, `FRACTTAL_*` | Fixos | Raramente. |

> Uma credencial ausente/vencida **não derruba o app** — só deixa aquela fonte "indisponível" no painel.

---

## 4. Reiniciar o servidor

```bat
:: 1) descobre o PID na porta 5050 e mata
netstat -ano | findstr :5050
taskkill /PID <PID_ENCONTRADO> /F
:: 2) sobe de novo
cd <pasta_da_aplicacao>
python app.py          &:: (ou pythonw app.py p/ background)
```

> Se houver a **tarefa vigia** (seção 5), desabilite-a antes de matar o processo e reabilite depois —
> senão ela religa o servidor no meio da parada.

Usuários com a página aberta devem dar **Ctrl+F5** (hard-refresh) após um update de código.

---

## 5. Manter no ar (recomendado): tarefa vigia

O `ronda_guardian.py` é idempotente: se a 5050 responde, ele sai; se caiu, sobe o servidor sem janela.
Criar uma tarefa no **Agendador de Tarefas** a cada 5 minutos:

- Programa: `pythonw.exe`
- Argumentos: `"<pasta_da_aplicacao>\ronda_guardian.py"`
- Marcar "Executar estando o usuário conectado ou não".

Log das intervenções: `<pasta>\logs\ronda_guardian.log`.

---

## 6. Atualização futura (quando vier um zip novo)

O estado de runtime (seção 1) e o `tokens.txt` **não devem ser sobrescritos** por engano.
Rotina segura: (1) desabilitar a tarefa vigia → (2) parar o servidor (seção 4) → (3) **backup da pasta** →
(4) extrair o zip novo por cima, **mantendo o `tokens.txt` atual se as credenciais de lá estiverem mais novas** →
(5) `pip install -r requirements.txt` → (6) subir → (7) reabilitar a vigia.

---

## 7. Problemas comuns

| Sintoma | Causa / ação |
|---|---|
| `python app.py` morre na hora | Porta 5050 ocupada → seção 4 (matar o processo antigo) |
| Todas as fontes "indisponíveis" | `tokens.txt` ausente/vazio, ou não está na MESMA pasta do `app.py` |
| Fonte X "indisponível" (só uma) | Credencial daquela fonte vencida no `tokens.txt` — ver seção 3 |
| Login não abre / 401 em tudo | `DASH_PASSWORD` vazia no `tokens.txt`, ou o arquivo não foi lido |
| Página velha / botão sumido após update | Cache do navegador → **Ctrl+F5** |
| "Trackers 0 parados" logo após subir | Aquecimento de cache (~5–10 min) — aguardar |
| Erro de módulo no boot | Faltou `pip install -r requirements.txt` (ou Python < 3.12) |

---

## 8. O que NÃO roda neste servidor

- **Ronda automática de WhatsApp** e **Monitor da Ronda**: dependem de um serviço local (chip WhatsApp)
  na máquina da equipe de Performance — as telas existem, mas o envio fica inativo aqui.
- **Coletores de dados** (`coletar_geracao_hoje.py` etc.): rodam agendados na máquina da equipe, não no servidor.

Dúvidas: equipe de Performance (Levi) — `performance@gridco.com.br`.
