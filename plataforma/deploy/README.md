# Plataforma de Performance — Guia de Instalação (T.I)

Aplicação web **Flask (Python)** que consolida a operação das usinas (strings, trackers, painéis NOC/PR).
Escuta em **`http://0.0.0.0:5050`** (servidor embutido *waitress*; **não** precisa de IIS/nginx).

> **São DOIS processos, e os dois precisam estar no ar.** O `worker.py` reconstrói os dados; o
> `app.py` só entrega as telas. Subir só o `app.py` dá um painel que abre normalmente e **nunca
> atualiza** — é a falha mais fácil de cometer aqui, e ela não aparece como erro. Ver seção 3.

> Este pacote é uma **instalação COMPLETA e do zero**: já vem com o `tokens.txt` preenchido, então o app
> sobe **autenticado** em todas as fontes. O `tokens.txt` contém **segredos** — trate o zip como sigiloso
> (não subir em git, não mandar por canal aberto).

---

## 1. O que vem no pacote (`oem-app.zip`)

O repositório tem quatro projetos; este zip traz só a plataforma e o que ela importa.

| Item | Papel |
|---|---|
| `plataforma/app.py` | **Processo web** — serve a porta 5050 |
| `plataforma/worker.py` | **Processo pesado** — reconstrói os dados e publica p/ o web |
| `plataforma/ronda_guardian.py` | Vigia: religa **os dois** processos se algum cair |
| `plataforma/tracker_watch.py` · `trk_regua_v2.py` · `strings_regua_v2.py` | Réguas e livro de ocorrências |
| `plataforma/push_bases.py` | Cliente de envio das planilhas — **roda na máquina do analista**, não aqui (seção 5) |
| `plataforma/templates/` · `static/` | Interface web |
| `plataforma/BD_Performance.xlsx` | Cadastro de usinas/equipamentos (semente do 1º boot) |
| `plataforma/trackers_garantia.json` | Referência: trackers com chamado de garantia aberto |
| `thopen/dashboard_thopen.py` | Motor de carteiras/gerencial — **importado pelo `app.py`** |
| `thopen/data/` | BD_Thopen.xlsx + planilhas Copel/Matrix/Polaris |
| `docs/` | Documentação + a tela principal (`/` lê `docs/redesign/`) |
| `requirements.txt` | Dependências Python |
| **`tokens.txt`** | **Credenciais consolidadas — o ÚNICO arquivo de segredo. Editar aqui p/ atualizar tokens.** |
| `.env.example` | Modelo de referência das variáveis (o `tokens.txt` já substitui isto) |

**O que o app CRIA sozinho depois (estado de runtime, tudo dentro de `plataforma/` — nunca apagar
num update):** `tokens_runtime.json` (tokens auto-renovados) · `cache_snapshot.json` ·
`ufv_state.json` (comentários dos analistas) · `tracker_issues.json` / `trk_eventos.json` /
`trackers_parados_hist.jsonl` (histórico de trackers) · `perdas_strings.json` · `paradas_book.json` ·
`bases/` (planilhas recebidas por push) · `logs/`.

---

## 2. Instalação do zero

1. **Python 3.12+** (desenvolvido no 3.14) com `pip` no PATH.
2. Extrair o `oem-app.zip` na pasta de destino (ex.: `C:\GridCo\painel` — a pasta `plataforma\` aparece dentro dela).
3. Instalar as dependências **a partir da raiz do pacote**:
   ```bat
   cd C:\GridCo\painel
   python -m pip install -r requirements.txt
   ```
4. **Conferir o `tokens.txt`** na raiz — já vem preenchido. Nada a fazer se as credenciais estão válidas.

> O `tokens.txt` fica na **raiz**, não dentro de `plataforma\`. O app procura nesse nível de propósito:
> a coleta também lê o mesmo arquivo.

---

## 3. Subir os dois processos

Sempre a partir da pasta **`plataforma\`** (os dois processos resolvem caminhos relativos a ela):

```bat
cd C:\GridCo\painel\plataforma
start "" pythonw.exe worker.py
start "" pythonw.exe app.py
```

Ordem não importa; o web funciona sem o worker (servindo o último dado publicado) e o worker
funciona sem o web. Para depurar, troque `pythonw.exe` por `python.exe -u` e veja o console:
o `app.py` deve imprimir `modo WEB — quem reconstrói é o worker.py`.

**Validar (3 checagens):**

```bat
curl http://localhost:5050/healthz
```
```bat
tasklist /FI "IMAGENAME eq pythonw.exe"
```
O `healthz` responde `OK` sem login, e o `tasklist` tem de mostrar **dois** processos. Por fim,
abrir `http://<ip-do-servidor>:5050` no navegador → tela de login → senha (`DASH_PASSWORD` do
`tokens.txt`).

> **Aquecimento:** nos primeiros ~5–10 min os contadores de trackers/strings podem aparecer
> zerados/parciais enquanto o worker reconstrói os caches. É normal — não reiniciar por causa disso.

**Saída de emergência:** se o worker não subir de jeito nenhum, `set GRIDCO_SOLO=1` antes de iniciar
o `app.py` volta ao modo antigo (um processo faz tudo). Funciona, mas traz de volta o gargalo: com
3+ analistas simultâneos as páginas ficam lentas durante cada reconstrução. Nesse modo **não** suba
o worker — seriam dois processos reconstruindo o mesmo dado.

---

## 4. Manter no ar (recomendado): tarefa vigia

O `ronda_guardian.py` é idempotente e vigia **os dois** processos: quem estiver de pé ele deixa
quieto, quem caiu ele sobe sem janela. Criar uma tarefa no **Agendador de Tarefas** a cada 5 minutos:

- Programa: `pythonw.exe`
- Argumentos: `"C:\GridCo\painel\plataforma\ronda_guardian.py"`
- Iniciar em: `C:\GridCo\painel\plataforma`
- Marcar "Executar estando o usuário conectado ou não".

Log das intervenções: `plataforma\logs\ronda_guardian.log`.

> O caminho fica gravado na tarefa. Se a pasta mudar de lugar, **atualize a tarefa** — senão o vigia
> falha em silêncio e ninguém percebe até o servidor cair.

---

## 5. As bases vêm da API — o servidor NÃO usa OneDrive

Três bases alimentam o painel (`BD_Performance`, `BD_Thopen`, `Tickets de Performance`). Este
servidor tem uma porta exposta, e sincronizar OneDrive numa máquina exposta significa que um
comprometimento alcança as bases da empresa — e o estrago sobe para a nuvem junto. Por isso
**não instale OneDrive aqui**, e desde 25/08/2026 não é mais preciso: as bases vêm da **Gridco
Performance API**.

O `bd_api.py` baixa as linhas de `https://app.gridco.com.br/db_performace` e monta as planilhas
**em memória** (`BD_MEM=1`, o padrão) — não há arquivo em disco no caminho normal. Um laço no
`worker.py` revalida a cada 30 min, e a revalidação é barata: uma chamada compara o `updated_at`
do workbook e só rebaixa as ~25 mil linhas quando a fonte mudou de verdade.

Consequência prática: **o servidor precisa de saída HTTPS para `app.gridco.com.br`**. Sem isso o
painel sobe sem cadastro nenhum — sem usinas, sem inversores esperados, sem Full O&M.

O botão **Atualizar** da tela chama `GET /api/check/reload?force=1`, que pergunta à API se a fonte
mudou e, só nesse caso, reconstrói o cadastro (usinas visíveis, inversores esperados, strings,
metas, tracker↔inversor). A reconstrução roda em thread e a resposta volta na hora;
`GET /api/check/reload/status` diz como terminou. Ou seja: alterou no banco, clicou, apareceu.

### Saídas de rede que a T.I. precisa liberar

| Destino | Para quê | Sem isso |
|---|---|---|
| `app.gridco.com.br` | **bases (cadastro, metas, tickets)** | painel sobe vazio — bloqueio mais grave |
| `44.214.183.214:5432` | PostgreSQL de telemetria (fonte PG) | fonte "Banco de Dados" fica cega |
| `gridco-api.sunop.net`, `axis-api.sunop.net` | SunOp/Athon e Axis | trackers e strings dessas usinas |
| `apipv.pvoperation.com.br`, `plataforma.pvoperation.com`, `apiplataforma.pvoperation.com` | API PV Operation | trackers, strings e combiner da maior fonte |
| `monitoring.solaredge.com` | SolarEdge | usinas SolarEdge |
| `app.fracttal.com` | Fracttal (OS, disponibilidade) | OS e disponibilidade por OS |
| `login.microsoftonline.com` | login Microsoft (se habilitado) | SSO |

**Fallback, se um dia a API estiver fora:** o envio por push continua existindo. Na máquina de
quem tem o OneDrive, `python push_bases.py --url https://<servidor>` grava em `plataforma\bases\`,
e o resolvedor usa o espelho quando a API não responde. Conferir o que chegou: `GET /api/admin/bases`.

---

## 6. Atualizar credenciais (rápido) — o `tokens.txt`

Todas as credenciais ficam em **um só arquivo**, o `tokens.txt` na raiz. Para trocar qualquer token:

1. Abrir `tokens.txt` num editor de texto.
2. Editar o valor da linha (formato `CHAVE=VALOR`; linhas com `#` são comentário).
3. Salvar e **reiniciar os dois processos** (seção 7).

Cada bloco do arquivo tem a instrução de **como renovar** aquele token. Os mais sensíveis:

| Token | Comportamento | Quando mexer |
|---|---|---|
| `PLAT_TOKEN` (Plataforma) | **Manual, ~7 dias, NÃO auto-renova** | Renovar quando a tela avisar "vencido". |
| `SUNOP_TOKEN` / `AXIS_TOKEN` | **Auto-renova** sozinho | Só recolar se o servidor ficar **dias desligado**. |
| `PV_*`, `SE_*` | Login automático (usuário/senha) | Só se a senha mudar. |
| `PG_*`, `FRACTTAL_*` | Fixos | Raramente. |

> Uma credencial ausente/vencida **não derruba o app** — só deixa aquela fonte "indisponível" no painel.

**Sem editar arquivo:** a tela **`/tokens`** mostra a validade de cada credencial e aceita colar um
token novo pela interface. Vale na hora, sem reiniciar. É o caminho preferido para o `PLAT_TOKEN`,
que vence toda semana.

---

## 7. Reiniciar

```bat
taskkill /IM pythonw.exe /F
cd C:\GridCo\painel\plataforma
start "" pythonw.exe worker.py
start "" pythonw.exe app.py
```

> Se houver a tarefa vigia (seção 4), **desabilite antes** e reabilite depois — senão ela religa no
> meio da parada. E o `taskkill` acima derruba **todo** `pythonw.exe` da máquina; se houver outro
> serviço Python aqui, mate por PID (`netstat -ano | findstr :5050`).

Usuários com a página aberta devem dar **Ctrl+F5** (hard-refresh) após um update de código.

---

## 8. Atualização futura (quando vier um zip novo)

O estado de runtime (seção 1) e o `tokens.txt` **não devem ser sobrescritos** por engano.
Rotina segura: (1) desabilitar a tarefa vigia → (2) parar os dois processos (seção 7) → (3) **backup
da pasta** → (4) extrair o zip novo por cima, **mantendo o `tokens.txt` atual se as credenciais de lá
estiverem mais novas** → (5) `pip install -r requirements.txt` → (6) subir os dois → (7) reabilitar a vigia.

O zip novo **não** traz estado de runtime, então extrair por cima não apaga histórico nem comentários.

---

## 8b. Deploy por git (substitui o zip)

Combinado com o Igor em 03/08/2026: em vez de mandar zip a cada versão, o servidor
acompanha o repositório. Atualizar vira `git pull` + reiniciar os dois processos.

**O que o git traz e o que ele NÃO traz.** O repositório tem só código (38 arquivos em
`plataforma/`). Segredo e estado ficam de fora **por regra do `.gitignore`**, não por
descuido: `.env`, `tokens.txt`, `tokens_runtime.json`, `*.migrado`, `cache_snapshot.json`,
os `*.json` de estado e os `.log`. Isso é proposital — um `git pull` **nunca** pode
sobrescrever o token vivo nem o histórico de comentários das usinas.

Consequência prática: **a primeira instalação continua precisando dos segredos à mão.**
O `.env` e o `tokens.txt` chegam por canal seguro (seção 2), uma vez. Da segunda
atualização em diante, é só `git pull`.

```
cd <pasta do projeto>
git pull
pip install -r requirements.txt        # só se o requirements mudou
# reiniciar os dois processos (seção 7)
```

**Nunca rode `git add -A` no servidor.** O servidor é destino, não origem: o estado de
runtime muda o tempo todo e commitá-lo cria conflito no próximo `pull`. Se precisar
descartar alteração local acidental, `git checkout -- <arquivo>`.

⚠️ **`git checkout` de branch apaga arquivo rastreado que não existe na branch de
destino.** Aconteceu em 03/08: trocar para uma branch sem a pasta `plataforma/` apagou
os `.py` do disco e o serviço só continuou de pé porque os processos já tinham o código
em memória. No servidor, fique **sempre na mesma branch** e use só `git pull`.

---

## 8c. Rodar atrás do proxy reverso (sub-caminho)

A plataforma roda sob **`/plat-performance`** no proxy do T.I., em vez de ocupar a raiz
da porta. Basta o proxy encaminhar com o cabeçalho:

```
X-Forwarded-Prefix: /plat-performance
```

Funciona das duas formas: se o proxy encaminhar o caminho inteiro
(`/plat-performance/api/data`) a aplicação tira o prefixo sozinha; se o proxy já tirar
antes de encaminhar, também funciona. Não é preciso saber qual dos dois é.

Alternativa sem cabeçalho: definir a variável de ambiente `APP_PREFIX=/plat-performance`
antes de subir os processos.

**Vazio = raiz**, que é o comportamento de sempre. Quem roda local em `localhost:5050`
não precisa configurar nada.

O front-end se adapta em tempo de execução — um shim injetado em cada página reescreve
os caminhos absolutos (`fetch`, `XMLHttpRequest`, `EventSource`, links e formulários).
Por isso trocar o nome do caminho é trocar uma string, não mexer no código.

---

## 9. Problemas comuns

| Sintoma | Causa / ação |
|---|---|
| Painel abre mas os números **não mudam nunca** | O `worker.py` não está rodando — seção 3 |
| `python app.py` morre na hora | Porta 5050 ocupada → seção 7 (matar o processo antigo) |
| Todas as fontes "indisponíveis" | `tokens.txt` ausente/vazio, ou não está na **raiz** do pacote |
| Fonte X "indisponível" (só uma) | Credencial daquela fonte vencida — ver seção 6 ou a tela `/tokens` |
| Login não abre / 401 em tudo | `DASH_PASSWORD` vazia no `tokens.txt`, ou o arquivo não foi lido |
| Dados congelados numa data antiga | Nenhum push chegou — conferir `GET /api/admin/bases` e a tarefa da seção 5 |
| Página velha / botão sumido após update | Cache do navegador → **Ctrl+F5** |
| "Trackers 0 parados" logo após subir | Aquecimento de cache (~5–10 min) — aguardar |
| Erro de módulo no boot | Faltou `pip install -r requirements.txt` (ou Python < 3.12) |
| `ModuleNotFoundError: dashboard_thopen` | A pasta `thopen\` não foi extraída — o `app.py` importa dela |
| Vigia não religa; log diz `FALHA ao subir` | `pythonw` não está no PATH do usuário da tarefa agendada — usar o caminho completo do `pythonw.exe` |

---

## 10. O que NÃO roda neste servidor

- **Ronda automática de WhatsApp** e **Monitor da Ronda**: dependem de um serviço local (chip WhatsApp)
  na máquina da equipe de Performance — as telas existem, mas o envio fica inativo aqui.
- **Coletores de dados**: rodam agendados na máquina da equipe, alimentando as planilhas.
- **`push_bases.py`**: vem no pacote por conveniência, mas roda na máquina do analista (seção 5).

## 11. O token que NÃO se renova sozinho — leia antes de colocar no ar

Quase todos os tokens do `tokens.txt` se renovam sozinhos. **Um não:** o `PLAT_TOKEN`, da PV
Operation, que serve os trackers e o combiner box. Ele tem CAPTCHA e MFA, vale **7 dias** e
precisa ser recolado por uma pessoa.

Isto não é detalhe: em 31/08/2026 ele venceu às 13:30 e, às 15:49, **72 de 72 usinas** apareciam
como "sem comunicação" e as strings como falha — alarme falso em tudo, porque o app não distingue
"a API respondeu 401" de "o equipamento parou". Ninguém percebeu por horas.

Como renovar (vale na hora, **sem reiniciar** — o `tokens_runtime.json` é relido a cada uso):

```
POST /api/pv/trackers/token     {"token": "<colado>"}
```

Como saber que está perto de vencer: `GET /api/tokens` devolve `dias` restantes por fonte.
**Vale a pena um alerta** quando `plat` ficar com menos de 1 dia — é o único ponto do sistema em
que a expiração de credencial se disfarça de falha de campo.

Dúvidas: equipe de Performance (Levi) — `performance@gridco.com.br`.

## 12. Gêmeo Digital (`/gemeo/`)

Serviço separado (pasta `gemeo/` do repositório, porta 5075 local). A plataforma só faz **proxy** de `/gemeo/*` e
manda a senha compartilhada no header `X-Gemeo-Senha`. No `tokens.txt`: `GEMEO_SENHA=<mesma do gemeo.env>` e,
se a porta mudar, `GEMEO_URL=http://127.0.0.1:5075`. O proxy passa a existir **no próximo reinício** da plataforma;
a entrada "Gêmeo Digital" do menu aparece sozinha quando `/gemeo/healthz` responde. Instalação do gêmeo:
`gemeo/deploy/README.md`.
