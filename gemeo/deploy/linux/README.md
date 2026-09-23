# Gêmeo Digital no servidor Linux — roteiro

O gêmeo já vem junto com o clone da plataforma (pasta `gemeo/`). Falta instalá-lo como serviço. Hoje o
servidor responde **503 "Gêmeo Digital fora do ar"** em `https://app.gridco.com.br/gemeo/`: a plataforma
está pronta e repassa o pedido, só não há ninguém atendendo na porta 5075.

São três processos, os mesmos das Tarefas Agendadas do Windows:

| Serviço | O que faz | Como roda |
|---|---|---|
| `gemeo-app` | telas e API, em `127.0.0.1:5075` | sempre ligado, volta sozinho se cair |
| `gemeo-ingest` | coleta das fontes (SunOp, API PV, Postgres) | sempre ligado, volta sozinho se cair |
| `gemeo-modelar` | esperado, cascata e assinaturas | a cada 15 min, pelo `gemeo-modelar.timer`, com teto de 14 min |

Os caminhos abaixo são exemplos: `/srv/PerformancePainel` (o clone), `/srv/venvs/gemeo` (o Python do
gêmeo), usuário `gridco`. Use os do servidor e ajuste os três arquivos `.service` iguais.

## 1. Python e dependências

```bash
python3 --version                       # precisa de 3.12 ou mais novo
python3 -m venv /srv/venvs/gemeo
/srv/venvs/gemeo/bin/pip install -e /srv/PerformancePainel/gemeo
```

## 2. Segredos e caminhos

```bash
sudo mkdir -p /etc/gridco/gemeo /var/lib/gridco/gemeo
sudo cp /srv/PerformancePainel/gemeo/deploy/linux/gemeo.env.exemplo   /etc/gridco/gemeo/gemeo.env
sudo cp /srv/PerformancePainel/gemeo/deploy/linux/servico.env.exemplo /etc/gridco/gemeo/servico.env
sudo chown -R gridco: /etc/gridco/gemeo /var/lib/gridco/gemeo
sudo chmod 600 /etc/gridco/gemeo/gemeo.env
```

Preencha o `gemeo.env`. **Obrigatórias** — sem elas o gêmeo nem sobe, e diz qual falta:

- `SUNOP_API_TOKEN` — o mesmo do `tokens.txt` da plataforma (o token de **API**, não o web);
- `GRIDCO_SQL_TOKEN` — o mesmo do `tokens.txt`;
- `GEMEO_SENHA` — **igual** à `GEMEO_SENHA` do `tokens.txt`. É com ela que a plataforma entra no gêmeo.

Exigidas pelo piloto atual: `POWERPLANTS_DSN` (usinas do Postgres da Thopen — o IP do servidor precisa
estar liberado no banco) e `PV_OEM_USERNAME`/`PV_OEM_PASSWORD` (as três usinas da 2C).

No `servico.env`, confira `GEMEO_CONFIG` (o `config.toml` do clone) e `GEMEO_DB_CAMINHO`. O banco **tem de**
ter caminho no Linux: o padrão do código é `%LOCALAPPDATA%`, que só existe no Windows. O `TZ` já vem
como `America/Sao_Paulo`, igual ao da plataforma.

O usuário do serviço precisa escrever em `gemeo/cache/` dentro do clone (é onde o gêmeo guarda cache).

## 3. O banco

**Com histórico** (recomendado — o gêmeo guarda 90 dias):

1. Na máquina do Levi, **pare o gêmeo** — as três tarefas "Gemeo App", "Gemeo Ingest" e "Gemeo
   Modelar" (Agendador de Tarefas → Desabilitar). Copiar o banco com ele gravando dá arquivo pela metade.
2. Copie `C:\GridcoAuto\gemeo\gemeo.sqlite` (≈ 2,2 GB) para `/var/lib/gridco/gemeo/gemeo.sqlite`.
   Se existirem, copie junto `gemeo.sqlite-wal` e `gemeo.sqlite-shm`.
3. `sudo chown gridco: /var/lib/gridco/gemeo/*`

**Sem histórico:** pule a cópia e crie as tabelas vazias:

```bash
cd /srv/PerformancePainel/gemeo
sudo -u gridco env $(grep -v '^#' /etc/gridco/gemeo/servico.env | xargs) /srv/venvs/gemeo/bin/python -m gemeo.cli migrate
```

## 4. Instalar e ligar

```bash
sudo cp /srv/PerformancePainel/gemeo/deploy/linux/gemeo-*.service /srv/PerformancePainel/gemeo/deploy/linux/gemeo-modelar.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now gemeo-app gemeo-ingest gemeo-modelar.timer
```

## 5. Conferir

```bash
systemctl status gemeo-app gemeo-ingest --no-pager
journalctl -u gemeo-ingest -f                 # a coleta imprime cada fonte que lê
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5075/gemeo/     # 302 = no ar (pede login)
```

E de fora: `https://app.gridco.com.br/gemeo/` deixa de responder 503 e mostra a tela de login do gêmeo.

## 6. O corte — nunca duas coletas

Com o `gemeo-ingest` do servidor ligado, **a coleta da máquina Windows não pode voltar**: são dois bancos
divergindo e o dobro de chamadas às fontes (a SunOp tem teto diário, `[sunop]` no `config.toml`). Mantenha
as três tarefas do Windows desabilitadas. Guarde o `gemeo.sqlite` da máquina antiga por duas semanas, sem
apagar, como reserva.

## 7. Atualização de código

O código do gêmeo chega com o mesmo `git pull` da plataforma, mas **o deploy automático reinicia só a
plataforma**. Depois de um pull que mude `gemeo/`, reinicie os dois serviços — senão eles seguem rodando
o código antigo:

```bash
sudo systemctl restart gemeo-app gemeo-ingest
```

O ideal é pôr essa linha no mesmo gancho que hoje reinicia a plataforma.

## Se não subir

- `SegredoAusente: faltam em .../gemeo.env: ...` — preencha a chave citada (item 2).
- A tela abre mas pede senha e não aceita — a `GEMEO_SENHA` do `gemeo.env` não é a mesma do `tokens.txt`.
- Leituras com 3 h de diferença — o `TZ=America/Sao_Paulo` não está no `servico.env`.
- `/gemeo/` segue em 503 com o app no ar — a plataforma procura o gêmeo em `127.0.0.1:5075` (`GEMEO_URL`
  no `tokens.txt`); se o gêmeo estiver em outra máquina ou porta, ajuste ali.
